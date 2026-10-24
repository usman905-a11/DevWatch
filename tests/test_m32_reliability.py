"""Close conservative-policy gaps without treating model votes as proof."""
import pytest

from devwatch.review.contracts import (AgentPrivateState, EvidenceProgress, FindingCandidate,
    ReviewTask, SpecialistResult, VerificationDecision, VerificationPhaseResult)
from devwatch.review.finalization import AcceptanceError, FinalAcceptanceGate, assemble_report
from devwatch.review.repository import SharedBlackboard, StructuralEvidenceGate
from devwatch.review.verification import require_independent_verification
from tests.test_audit_evidence import candidate, engine
from tests.test_repository_context import setup_repository
from tests.verification_fixtures import decision


def test_followup_cannot_overwrite_an_earlier_remediation(tmp_path):
    _, _, _, repo, task = setup_repository(tmp_path)
    ref = repo._read_source({'file_path': 'service.py'}, task).evidence_ref
    first = candidate(repo, ref) | {'remediation': 'Return None when the list is empty.'}
    second = first | {'remediation': 'Raise ValueError when the list is empty.'}
    board = SharedBlackboard(StructuralEvidenceGate(repo))
    for claim in (first, second, first):
        board.publish(task, SpecialistResult(task_id=task.task_id, agent_id=task.agent_id,
            candidates=[claim], coverage={}, stop_reason='evidence_complete'))
    assert len(board.candidates) == 2
    assert {claim.remediation for claim in board.candidates.values()} == {
        'Return None when the list is empty.', 'Raise ValueError when the list is empty.'}
    assert len(board.provenance()) == 2


@pytest.mark.asyncio
async def test_already_uncertain_model_result_cannot_publish_confidence_above_half(tmp_path):
    from tests.test_m20_verification import setup
    repo, task, ref, claim = setup(tmp_path)
    record = decision(claim, [ref], verdict='uncertain', confidence=.79, statuses={'impact': 'uncertain'})
    runtime, _ = engine(repo, [dict(kind='submit_verification', inspected_evidence=[ref],
        payload=dict(decisions=[record]))])
    runtime.require_verification_challenge = runtime.require_independent_support = True
    state = await runtime.run_final(snapshot_id=repo.snapshot_id, files=task.files, candidates={'f1': claim})
    assert state['output'] is not None
    finding = state['output'].report_draft.uncertain_high_impact_candidates[0]
    assert finding.confidence == .5
    assert finding.description == claim['description']


def test_strict_acceptance_rechecks_uncertain_confidence_for_restored_decisions(tmp_path):
    from tests.test_m20_verification import setup
    repo, _, ref, claim = setup(tmp_path)
    record = VerificationDecision.model_validate(decision(claim, [ref], verdict='uncertain',
        confidence=.79, statuses={'impact': 'uncertain'}))
    draft = assemble_report(repo.snapshot_id, {'f1': claim}, [record], summary='review')
    gate = FinalAcceptanceGate({'f1': FindingCandidate.model_validate(claim)}, evidence_refs={ref},
        inspected_evidence={ref}, require_independent_support=True)
    with pytest.raises(AcceptanceError, match='confidence'):
        gate.accept(draft, [record])


def test_exact_claims_are_deduplicated_after_votes_become_uncertain_without_erasing_audit(tmp_path):
    from tests.test_m20_verification import setup
    repo, _, ref, claim = setup(tmp_path)
    candidates = {'a': claim, 'b': claim | {'confidence': .85}}
    records = VerificationPhaseResult(decisions=[decision(value, [ref], identity=identity)
        for identity, value in candidates.items()])
    result = require_independent_verification(candidates, records)
    assert result.duplicate_groups == [['a', 'b']]
    assert len(result.decisions) == 2
    assert all(item.verdict == 'uncertain' for item in result.decisions)
    draft = assemble_report(repo.snapshot_id, candidates, result.decisions, summary='review',
        duplicate_groups=result.duplicate_groups)
    accepted = FinalAcceptanceGate({key: FindingCandidate.model_validate(value) for key, value in candidates.items()},
        evidence_refs={ref}, inspected_evidence={ref}, duplicate_groups=result.duplicate_groups,
        verification=result, require_independent_support=True).accept(draft, result.decisions).draft
    assert len(accepted.uncertain_high_impact_candidates) == 1
    assert len(accepted.verification_audit.decisions) == 2
    assert accepted.verification_audit.duplicate_groups == [['a', 'b']]
    assert require_independent_verification(candidates, result) == result


@pytest.mark.parametrize('field,value', [
    ('description', 'A second distinct failure on the same source line.'),
    ('remediation', 'Raise a different exception.'),
    ('impact', 'A different caller contract is violated.'),
])
def test_model_duplicate_vote_cannot_discard_different_uncertain_claims(tmp_path, field, value):
    from tests.test_m20_verification import setup
    repo, _, ref, claim = setup(tmp_path)
    candidates = {'a': claim, 'b': claim | {field: value}}
    records = VerificationPhaseResult(decisions=[decision(item, [ref], identity=identity,
        verdict='uncertain', confidence=.5, statuses={'impact': 'uncertain'})
        for identity, item in candidates.items()], duplicate_groups=[['a', 'b']],
        duplicate_reviews=[dict(finding_ids=['a', 'b'], rationale='Model claims these are equivalent.', evidence_refs=[ref])])
    result = require_independent_verification(candidates, records)
    assert result.duplicate_groups == result.duplicate_reviews == []
    draft = assemble_report(repo.snapshot_id, candidates, result.decisions, summary='review',
        duplicate_groups=result.duplicate_groups)
    assert len(draft.uncertain_high_impact_candidates) == 2
    # Persisted legacy relations must also fail closed at the last gate.
    legacy_draft = assemble_report(repo.snapshot_id, candidates, records.decisions, summary='review',
        duplicate_groups=records.duplicate_groups)
    with pytest.raises(AcceptanceError, match='duplicate'):
        FinalAcceptanceGate({key: FindingCandidate.model_validate(item) for key, item in candidates.items()},
            evidence_refs={ref}, inspected_evidence={ref}, duplicate_groups=records.duplicate_groups,
            verification=records, require_independent_support=True).accept(legacy_draft, records.decisions)


def test_identical_wording_with_different_evidence_gaps_cannot_merge(tmp_path):
    from tests.test_m20_verification import setup
    _, _, ref, claim = setup(tmp_path)
    result = require_independent_verification({'a': claim, 'b': claim}, VerificationPhaseResult(decisions=[
        decision(claim, [ref], identity='a', verdict='uncertain', confidence=.5, statuses={'impact': 'uncertain'}),
        decision(claim, [ref], identity='b', verdict='uncertain', confidence=.5, statuses={'remediation': 'uncertain'})]))
    assert result.duplicate_groups == []
    assert len(result.decisions) == 2


def test_partial_recovery_caps_confidence_and_rebuilds_exact_groups(tmp_path):
    from devwatch.review.workflow import _ReviewSession
    from tests.test_m20_recovery import setup
    session, identity, ref = setup(tmp_path)
    claim = session.board.candidates[identity]
    # Two contributors remain distinct in the blackboard and provenance audit.
    task = ReviewTask(task_id='logic-2', agent_id='logic_correctness', files=['service.py'], focus='Review independently')
    session.board.publish(task, SpecialistResult(task_id=task.task_id, agent_id=task.agent_id,
        candidates=[claim], coverage={}, stop_reason='evidence_complete'))
    other, = set(session.board.candidates) - {identity}
    record = session.repository.evidence_page(ref, task)
    total = record['total_chars']
    private = AgentPrivateState(stop_reason='review_time_exhausted', evidence_refs=[ref],
        evidence_progress={ref: EvidenceProgress(total_chars=total, source_file='service.py',
            delivered=[(0, total)], inspected=[(0, total)])})
    previous = VerificationPhaseResult(decisions=[decision(claim, [ref], identity=key, verdict='uncertain',
        confidence=.79, statuses={'impact': 'uncertain'}) for key in (identity, other)])
    recovered = _ReviewSession.partial_result(session, private, verification=previous)
    assert len(recovered.decisions) == 2
    assert all(record.confidence == .5 for record in recovered.decisions)
    assert len(recovered.report_draft.uncertain_high_impact_candidates) == 1
    accepted = FinalAcceptanceGate(session.board.candidates, evidence_refs={ref}, inspected_evidence={ref},
        duplicate_groups=recovered.duplicate_groups, verification=recovered, provenance=session.board.provenance(),
        require_independent_support=True).accept(recovered.report_draft, recovered.decisions).draft
    assert set(accepted.verification_audit.provenance) == {identity, other}
    assert accepted.coverage.failed['__final'] == 'review_time_exhausted'


def test_old_policy_verification_checkpoint_requires_current_adjudication(tmp_path):
    from devwatch.review.verification import checkpoint_verification
    from tests.test_m20_verification import setup
    _, _, ref, claim = setup(tmp_path)
    previous = VerificationPhaseResult(decisions=[decision(claim, [ref], verdict='uncertain',
        confidence=.79, statuses={'impact': 'uncertain'})])
    assert checkpoint_verification(dict(verification=previous.model_dump(),
        verification_policy='independent-claims-v3')) is None
