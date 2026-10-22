"""Semantic review admission, distinct from source-integrity and permission gates.

The model supplies judgments; these checks enforce their completeness, binding and
consistency. A structurally valid review is not a deterministic proof of truth.
"""
from hashlib import sha256
import json

from devwatch.review.contracts import (FindingCandidate, VerificationPhaseResult,
    CausalReview, ClaimAssessment, ReviewObservation, ArithmeticReceipt)
from devwatch.review.arithmetic import check_claim, check_counterexample


CLAIM_FIELDS = frozenset(('title', 'description', 'impact', 'remediation'))
CHALLENGE_POLICY = 'independent-arithmetic-v1'


def candidate_digest(candidate):
    claim = FindingCandidate.model_validate(candidate).model_dump(mode='json')
    return sha256(json.dumps(claim, sort_keys=True, ensure_ascii=False,
                             separators=(',', ':')).encode()).hexdigest()


def validate_decision(candidate, decision, *, allow_unreviewed=False, independent=True):
    if independent and enforce_arithmetic(candidate, decision).verdict != decision.verdict:
        raise ValueError('Decision conflicts with independent arithmetic evidence.')
    review = decision.causal_review
    if review is None:
        if decision.verdict == 'rejected':
            return
        if allow_unreviewed and decision.verdict == 'uncertain' and decision.confidence <= .5:
            return
        raise ValueError('Non-rejected decisions require a complete candidate-bound causal_review.')
    if review.candidate_digest != candidate_digest(candidate):
        raise ValueError('Causal review belongs to a different candidate.')
    fields = [assessment.field for assessment in review.assessments]
    if len(fields) != len(CLAIM_FIELDS) or set(fields) != CLAIM_FIELDS:
        raise ValueError('Causal review must assess title, description, impact and remediation exactly once.')
    if not review.causal_basis.strip() or any(not item.explanation.strip() for item in review.assessments):
        raise ValueError('Causal basis and field explanations cannot be blank.')
    allowed = set(decision.evidence_refs)
    if any(not set(item.evidence_refs).issubset(allowed) for item in review.assessments):
        raise ValueError('Field assessments must cite the decision evidence.')
    statuses = {item.status for item in review.assessments}
    if 'unsupported' in statuses and decision.verdict != 'rejected':
        raise ValueError('An unsupported clause requires rejection of the whole candidate; request a narrower follow-up.')
    if decision.verdict in {'confirmed', 'advisory'} and statuses != {'supported'}:
        raise ValueError('Positive decisions require support for every field.')
    if decision.verdict == 'uncertain' and ('uncertain' not in statuses or decision.confidence >= .8):
        raise ValueError('Uncertainty requires a recorded evidence gap and confidence below confirmation threshold.')


def combine_verification(previous, current):
    if previous is None:
        return current.model_copy(deep=True)
    return VerificationPhaseResult(**{field: getattr(previous, field) + getattr(current, field)
                                     for field in VerificationPhaseResult.model_fields})


def checkpoint_verification(raw):
    """Old decisions, including rejections, cannot bypass the current policy."""
    value = raw.get('verification')
    if value is None:
        return None
    result = VerificationPhaseResult.model_validate(value)
    if raw.get('verification_policy') != CHALLENGE_POLICY and result.decisions:
        return None
    return result


def arithmetic_receipts(candidate):
    claim = FindingCandidate.model_validate(candidate)
    digest = candidate_digest(claim)
    return [ArithmeticReceipt(candidate_digest=digest, claim_index=index, field=item.field,
        statement=item.statement(), result=check_claim(item))
        for index, item in enumerate(claim.arithmetic_claims)]


def _uncertain(candidate, decision, reason):
    claim = FindingCandidate.model_validate(candidate)
    # Do not launder either review's disputed prose into an authoritative fact.
    refs = list(claim.evidence_refs)
    return decision.model_copy(deep=True, update={'verdict': 'uncertain',
        'confidence': min(decision.confidence, .5), 'rationale': reason,
        'evidence_refs': refs, 'arithmetic_counterexamples': [],
        'causal_review': CausalReview(candidate_digest=candidate_digest(claim),
            causal_basis=reason, assessments=[ClaimAssessment(field=field, status='uncertain',
                explanation='Unresolved judgment; independent whole-field support is not established.',
                evidence_refs=refs) for field in sorted(CLAIM_FIELDS)])})


def enforce_arithmetic(candidate, decision):
    """Calculations may refute or weaken a judgment; they never promote one."""
    claim = FindingCandidate.model_validate(candidate)
    receipts = arithmetic_receipts(claim)
    false_fields = {item.field for item in receipts if item.result.status == 'contradicted'}
    invalid_counterexample = False
    for example in decision.arithmetic_counterexamples:
        status = (check_counterexample(claim.arithmetic_claims[example.claim_index], example.point)
            if example.claim_index < len(claim.arithmetic_claims) else 'out_of_domain')
        if status == 'contradicts':
            false_fields.add(claim.arithmetic_claims[example.claim_index].field)
        else:
            invalid_counterexample = True
    if false_fields:
        result = decision.model_copy(deep=True)
        result.verdict = 'rejected'
        result.rationale = 'Independent arithmetic found an in-domain counterexample to an explicit candidate assertion.'
        if result.causal_review is not None:
            for assessment in result.causal_review.assessments:
                if assessment.field in false_fields:
                    assessment.status = 'unsupported'
                    assessment.explanation = 'The exact declared predicate has a computed in-domain counterexample.'
        return result
    if invalid_counterexample:
        return _uncertain(claim, decision, 'The proposed arithmetic counterexample does not establish a contradiction in the declared domain.')
    if decision.verdict in {'confirmed', 'advisory'} and any(item.result.status == 'unknown' for item in receipts):
        return _uncertain(claim, decision, 'An explicit arithmetic assertion exceeds supported verification; its truth remains unknown.')
    if decision.verdict == 'rejected' and decision.causal_review is not None:
        unsupported = {item.field for item in decision.causal_review.assessments if item.status == 'unsupported'}
        exact_supported = {item.field for item in receipts if item.result.status == 'supported'
                           and getattr(claim, item.field) == item.statement}
        if unsupported and unsupported.issubset(exact_supported):
            return _uncertain(claim, decision, 'The rejected field is an independently supported arithmetic assertion; source relevance still requires review.')
    return decision.model_copy(deep=True)


def reconcile_challenge(candidates, previous, current):
    """Preserve conflicting observations; only computed falsehood is a veto."""
    passes = []
    for result in (previous, current):
        by_id = {item.finding_id: item for item in result.decisions}
        if set(by_id) != set(candidates) or len(by_id) != len(result.decisions):
            raise ValueError('Challenge requires the same distinct candidate set.')
        for identity, item in by_id.items():
            validate_decision(candidates[identity], item, independent=False)
        passes.append(by_id)
    rank = {'rejected': 0, 'uncertain': 1, 'advisory': 2, 'confirmed': 3}
    result = current.model_copy(deep=True)
    result.decisions = []
    result.review_observations = []
    changed = False
    for identity in candidates:
        first, second = (items[identity] for items in passes)
        result.review_observations.extend([ReviewObservation(pass_number=1, decision=first.model_copy(deep=True)),
                                           ReviewObservation(pass_number=2, decision=second.model_copy(deep=True))])
        if first.verdict != second.verdict and 'rejected' in {first.verdict, second.verdict}:
            selected = _uncertain(candidates[identity], second,
                'The two model reviews disagree; no independent whole-claim resolution is established.')
        else:
            selected = first if rank[first.verdict] < rank[second.verdict] else second
        selected = selected.model_copy(deep=True, update={'confidence': min(first.confidence, second.confidence)})
        if selected.verdict == 'uncertain':
            selected.confidence = min(selected.confidence, .5)
        # Retain counterexamples from both passes for independent adjudication.
        examples = first.arithmetic_counterexamples + second.arithmetic_counterexamples
        claim = FindingCandidate.model_validate(candidates[identity])
        contradictions = [example for example in examples if example.claim_index < len(claim.arithmetic_claims)
            and check_counterexample(claim.arithmetic_claims[example.claim_index], example.point) == 'contradicts']
        # One computed counterexample suffices. Keep every original in observations.
        selected.arithmetic_counterexamples = (contradictions or examples)[:1]
        selected = enforce_arithmetic(candidates[identity], selected)
        validate_decision(candidates[identity], selected)
        result.decisions.append(selected)
        changed |= first.verdict != second.verdict or selected.verdict != second.verdict
    result.conflicts = list(dict.fromkeys(previous.conflicts + current.conflicts))
    result.followup_requests = []
    for request in previous.followup_requests + current.followup_requests:
        if request not in result.followup_requests:
            result.followup_requests.append(request.model_copy(deep=True))
    if changed:
        result.duplicate_groups, result.duplicate_reviews, result.disagreements = [], [], []
        result.conflicts.append('Review disagreement or independent arithmetic changed a verdict; original judgments are retained and unproven relations were discarded.')
    return result


def validate_relations(candidates, result, inspected_evidence):
    by_id = {decision.finding_id: decision for decision in result.decisions}
    observed = set()
    for observation in result.review_observations:
        record = observation.decision
        key = (record.finding_id, observation.pass_number)
        if record.finding_id not in by_id or key in observed:
            raise ValueError('Original reviews require distinct known candidate/pass bindings.')
        validate_decision(candidates[record.finding_id], record, independent=False)
        observed.add(key)
    if any((identity, other) not in observed for identity, _ in observed for other in (1, 2)):
        raise ValueError('Original reviews require both observations for each challenged candidate.')
    inspected = set(inspected_evidence)
    reviews = {frozenset(review.finding_ids): review for review in result.duplicate_reviews}
    groups = [frozenset(group) for group in result.duplicate_groups]
    if (len(reviews) != len(result.duplicate_reviews) or len(set(groups)) != len(groups)
            or set(reviews) != set(groups)):
        raise ValueError('Every duplicate group requires exactly one causal-equivalence review.')

    def members(review):
        identities = set(review.finding_ids)
        if len(identities) != len(review.finding_ids) or not identities.issubset(by_id.keys() & candidates.keys()):
            raise ValueError('Relations require distinct known candidates with recorded decisions.')
        refs = set(review.evidence_refs)
        allowed = {ref for identity in identities for ref in by_id[identity].evidence_refs}
        if not review.rationale.strip() or not refs.issubset(allowed & inspected):
            raise ValueError('Relation explanations require inspected decision evidence.')
        return identities

    for group in result.duplicate_groups:
        identities = members(reviews[frozenset(group)])
        if len(group) != len(identities) or len(identities) < 2:
            raise ValueError('Duplicate groups require distinct candidates.')
        claims = [FindingCandidate.model_validate(candidates[identity]) for identity in identities]
        if (len({claim.location.file_path for claim in claims}) != 1
                or max(claim.location.start_line for claim in claims) > min(claim.location.end_line for claim in claims)):
            raise ValueError('Duplicate claims must cover the same source location; keep other findings separate.')
        verdicts = {by_id[identity].verdict for identity in identities}
        reviews_for_group = [by_id[identity].causal_review for identity in identities]
        if (len(verdicts) != 1 or not verdicts.issubset({'confirmed', 'advisory', 'uncertain'})
                or any(review is None for review in reviews_for_group)
                or len({tuple(sorted((item.field, item.status) for item in review.assessments))
                        for review in reviews_for_group}) != 1):
            raise ValueError('Only reviewed equivalent findings of the same classification and evidence gaps may merge.')
    for disagreement in result.disagreements:
        identities = members(disagreement)
        verdicts = [by_id[identity].verdict for identity in identities]
        if disagreement.resolution == 'unresolved':
            if not set(verdicts).issubset({'uncertain', 'rejected'}) or 'uncertain' not in verdicts:
                raise ValueError('Unresolved disagreements must remain uncertain, without positive findings.')
        elif sum(verdict in {'confirmed', 'advisory'} for verdict in verdicts) != 1 or any(
                verdict not in {'confirmed', 'advisory', 'rejected'} for verdict in verdicts):
            raise ValueError('A resolved disagreement must retain one supported position and reject its alternatives.')
