"""Semantic review admission, distinct from source-integrity and permission gates.

The model supplies judgments; these checks enforce their completeness, binding and
consistency. A structurally valid review is not a deterministic proof of truth.
"""
from hashlib import sha256
import json

from devwatch.review.contracts import FindingCandidate, VerificationPhaseResult


CLAIM_FIELDS = frozenset(('title', 'description', 'impact', 'remediation'))
CHALLENGE_POLICY = 'counterexample-v1'


def candidate_digest(candidate):
    claim = FindingCandidate.model_validate(candidate).model_dump(mode='json')
    return sha256(json.dumps(claim, sort_keys=True, ensure_ascii=False,
                             separators=(',', ':')).encode()).hexdigest()


def validate_decision(candidate, decision, *, allow_unreviewed=False):
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
    """Legacy positive checkpoints cannot bypass canonical challenge admission."""
    value = raw.get('verification')
    if value is None:
        return None
    result = VerificationPhaseResult.model_validate(value)
    if raw.get('verification_policy') != CHALLENGE_POLICY and any(
            item.verdict in {'confirmed', 'advisory'} for item in result.decisions):
        return None
    return result


def reconcile_challenge(candidates, previous, current):
    """A second review may veto or weaken a first judgment, never upgrade it."""
    passes = []
    for result in (previous, current):
        by_id = {item.finding_id: item for item in result.decisions}
        if set(by_id) != set(candidates) or len(by_id) != len(result.decisions):
            raise ValueError('Challenge requires the same distinct candidate set.')
        for identity, item in by_id.items():
            validate_decision(candidates[identity], item)
        passes.append(by_id)
    rank = {'rejected': 0, 'uncertain': 1, 'advisory': 2, 'confirmed': 3}
    result = current.model_copy(deep=True)
    result.decisions = []
    changed = False
    for identity in candidates:
        first, second = (items[identity] for items in passes)
        selected = first if rank[first.verdict] < rank[second.verdict] else second
        selected = selected.model_copy(deep=True, update={'confidence': min(first.confidence, second.confidence)})
        validate_decision(candidates[identity], selected)
        result.decisions.append(selected)
        changed |= first.verdict != second.verdict
    result.conflicts = list(dict.fromkeys(previous.conflicts + current.conflicts))
    result.followup_requests = []
    for request in previous.followup_requests + current.followup_requests:
        if request not in result.followup_requests:
            result.followup_requests.append(request.model_copy(deep=True))
    if changed:
        result.duplicate_groups, result.duplicate_reviews, result.disagreements = [], [], []
        result.conflicts.append('Counterexample review changed a verdict; unproven group and disagreement relations were discarded.')
    return result


def validate_relations(candidates, result, inspected_evidence):
    by_id = {decision.finding_id: decision for decision in result.decisions}
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
