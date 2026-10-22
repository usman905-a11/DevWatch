"""Computed evidence and disagreements travel through the actual final-agent graph."""
import asyncio

import pytest

from devwatch.review.arithmetic import ArithmeticClaim
from devwatch.review.contracts import VerificationPhaseResult
from devwatch.review import verification
from tests.test_audit_evidence import engine
from tests.test_m20_verification import setup
from tests.verification_fixtures import decision


def asserted(candidate, expression, start=1, stop=31, step=2):
    assertion = ArithmeticClaim(field='description', expression=expression,
        variables={'n': dict(start=start, stop=stop, step=step)})
    return {**candidate, 'description': assertion.statement(),
            'arithmetic_claims': [assertion.model_dump()]}


def run_pair(repo, task, ref, candidate, first, second):
    def action(record):
        return dict(kind='submit_verification', payload=dict(decisions=[record]), inspected_evidence=[ref])
    runtime, provider = engine(repo, [action(first), action(second), dict(kind='finish')])
    runtime.require_verification_challenge = True
    state = asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id, files=task.files,
        candidates={'f1': candidate}))
    return state, provider


def test_two_positive_model_votes_cannot_publish_a_false_arithmetic_clause(tmp_path):
    repo, task, ref, candidate = setup(tmp_path)
    candidate = asserted(candidate, '((n ^ (n - 1)) & 1) == 0')
    positive = decision(candidate, [ref])
    state, _ = run_pair(repo, task, ref, candidate, positive, positive)
    result = state['verification']
    assert result is not None
    assert result.decisions[0].verdict == 'rejected'
    assert [item.decision.verdict for item in result.review_observations] == ['confirmed', 'confirmed']
    assert positive['verdict'] == 'confirmed'


@pytest.mark.parametrize('reverse', [False, True])
def test_unproved_rejection_is_a_dispute_not_a_veto_in_either_order(tmp_path, reverse):
    repo, task, ref, candidate = setup(tmp_path)
    candidate = asserted(candidate, '(n ^ (n - 1)) == 1')
    positive = decision(candidate, [ref])
    negative = decision(candidate, [ref], verdict='rejected', statuses={'description': 'unsupported'})
    negative['rationale'] = '3 XOR 2 is 1, not 3.'
    first, second = (negative, positive) if reverse else (positive, negative)
    state, provider = run_pair(repo, task, ref, candidate, first, second)
    result = state['verification']
    assert result.decisions[0].verdict == 'uncertain'
    assert result.decisions[0].confidence < .8
    assert [item.decision.verdict for item in result.review_observations] == [first['verdict'], second['verdict']]
    assert len(provider.requests) == 2  # synthesis is deterministic; no extra model vote
    assert result.conflicts


def test_model_counterexample_is_checked_against_exact_predicate_and_domain(tmp_path):
    repo, task, ref, candidate = setup(tmp_path)
    candidate = asserted(candidate, '(n ^ (n - 1)) == 1')
    negative = decision(candidate, [ref], verdict='rejected', statuses={'description': 'unsupported'})
    negative['arithmetic_counterexamples'] = [{'claim_index': 0, 'point': {'n': 3}}]
    state, _ = run_pair(repo, task, ref, candidate, negative, negative)
    assert state['verification'].decisions[0].verdict == 'uncertain'


def test_unbounded_universal_claim_cannot_be_published_on_a_sample(tmp_path):
    repo, task, ref, candidate = setup(tmp_path)
    candidate = asserted(candidate, '(n ^ (n - 1)) == 1', stop=2147483647)
    positive = decision(candidate, [ref])
    state, _ = run_pair(repo, task, ref, candidate, positive, positive)
    assert state['verification'].decisions[0].verdict == 'uncertain'


def test_passing_calculation_does_not_approve_unrelated_prose(tmp_path):
    _, _, ref, candidate = setup(tmp_path)
    candidate = asserted(candidate, '(n ^ (n - 1)) == 1')
    candidate['description'] += ' This proves all programs terminate.'
    rejected = VerificationPhaseResult(decisions=[decision(candidate, [ref], verdict='rejected',
        statuses={'description': 'unsupported'})])
    result = verification.reconcile_challenge({'f1': candidate}, rejected, rejected)
    assert result.decisions[0].verdict == 'rejected'


def test_acceptance_rechecks_math_instead_of_trusting_stored_model_votes(tmp_path):
    from devwatch.review.finalization import FinalAcceptanceGate, assemble_report, AcceptanceError
    from devwatch.review.contracts import FindingCandidate, VerificationDecision
    _, _, ref, candidate = setup(tmp_path)
    candidate = asserted(candidate, 'n == 0', start=1, stop=1)
    record = VerificationDecision.model_validate(decision(candidate, [ref]))
    draft = assemble_report(candidate['location']['snapshot_id'], {'f1': candidate}, [record], summary='review')
    gate = FinalAcceptanceGate({'f1': FindingCandidate.model_validate(candidate)}, evidence_refs={ref}, inspected_evidence={ref})
    with pytest.raises(AcceptanceError, match='arithmetic'):
        gate.accept(draft, [record])


def test_old_rejection_checkpoint_cannot_bypass_disagreement_review(tmp_path):
    _, _, ref, candidate = setup(tmp_path)
    old = dict(verification_policy='counterexample-v1', verification=VerificationPhaseResult(
        decisions=[decision(candidate, [ref], verdict='rejected', statuses={'description':'unsupported'})]).model_dump())
    assert verification.checkpoint_verification(old) is None


def test_report_carries_computed_scope_and_retains_disputed_observations(tmp_path):
    from devwatch.review.finalization import FinalAcceptanceGate, assemble_report, render_accepted_report, AcceptanceError
    from devwatch.review.contracts import FindingCandidate
    repo, task, ref, candidate = setup(tmp_path)
    candidate = asserted(candidate, '(n ^ (n - 1)) == 1')
    positive = decision(candidate, [ref])
    negative = decision(candidate, [ref], verdict='rejected', statuses={'description':'unsupported'})
    state, _ = run_pair(repo, task, ref, candidate, positive, negative)
    verified = state['verification']
    draft = assemble_report(repo.snapshot_id, {'f1': candidate}, verified.decisions, summary='review')
    gate = FinalAcceptanceGate({'f1': FindingCandidate.model_validate(candidate)},
        evidence_refs={ref}, inspected_evidence={ref}, verification=verified)
    accepted = gate.accept(draft, verified.decisions)
    audit = accepted.draft.verification_audit
    receipt = audit.arithmetic_checks['f1'][0]
    assert receipt.result.status == 'supported'
    assert receipt.result.checked_assignments == 16
    assert receipt.candidate_digest == verification.candidate_digest(candidate)
    assert len(audit.review_observations) == 2
    assert any('prose' in note for note in accepted.draft.limitations)
    assert '16' in render_accepted_report(accepted)['markdown']
    damaged = accepted.draft
    damaged.verification_audit.arithmetic_checks.clear()
    with pytest.raises(AcceptanceError):
        gate.accept(damaged, verified.decisions)


def test_model_cannot_forge_original_judgment_history(tmp_path):
    repo, task, ref, candidate = setup(tmp_path)
    record = decision(candidate, [ref])
    action = dict(kind='submit_verification', inspected_evidence=[ref], payload=dict(
        decisions=[record], review_observations=[dict(pass_number=1, decision=record)]))
    runtime, _ = engine(repo, [action, action])
    state = asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id, files=task.files, candidates={'f1':candidate}))
    assert state['verification'] is None
    assert state['private_state'].stop_reason == 'invalid_schema'
