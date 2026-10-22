"""Recovery cannot turn absent or failed semantic review into confirmation."""
from types import SimpleNamespace

from devwatch.review.contracts import AgentPrivateState, SpecialistResult, VerificationPhaseResult
from devwatch.review.repository import SharedBlackboard, StructuralEvidenceGate
from devwatch.review.workflow import _ReviewSession
from tests.test_audit_evidence import candidate
from tests.test_repository_context import setup_repository
from tests.verification_fixtures import decision


def setup(tmp_path):
    _, _, _, repo, task = setup_repository(tmp_path)
    ref = repo._read_source({'file_path': 'service.py'}, task).evidence_ref
    board = SharedBlackboard(StructuralEvidenceGate(repo))
    board.publish(task, SpecialistResult(task_id=task.task_id, agent_id=task.agent_id,
        candidates=[candidate(repo, ref)], coverage={}, stop_reason='evidence_complete'))
    identity = next(iter(board.candidates))
    return SimpleNamespace(repository=repo, board=board), identity, ref


def test_uninspected_model_unsupported_impact_remains_unreviewed_not_a_proven_rejection(tmp_path):
    session, identity, ref = setup(tmp_path)
    claim = session.board.candidates[identity]
    raw = decision(claim, [ref], identity=identity, statuses={'impact': 'unsupported'})
    result = _ReviewSession.partial_result(session, AgentPrivateState(stop_reason='invalid_schema'),
        verification=VerificationPhaseResult(decisions=[raw]))
    assert result.decisions[0].verdict == 'uncertain'
    assert result.decisions[0].causal_review is None
    assert len(result.report_draft.uncertain_high_impact_candidates) == 1
    assert not result.report_draft.confirmed_defects


def test_legacy_unreviewed_candidate_remains_explicitly_unverified_with_failed_final_coverage(tmp_path):
    session, _, _ = setup(tmp_path)
    result = _ReviewSession.partial_result(session, AgentPrivateState(stop_reason='model_unavailable'))
    assert result.decisions[0].verdict == 'uncertain' and result.decisions[0].confidence <= .5
    assert result.report_draft.coverage.failed['__final'] == 'model_unavailable'
    assert 'unverified' in ' '.join(result.report_draft.limitations).lower()


def test_blackboard_retains_runtime_owned_specialist_provenance_for_every_candidate(tmp_path):
    session, identity, _ = setup(tmp_path)
    provenance = getattr(session.board, 'provenance', None)
    assert callable(provenance)
    assert provenance()[identity] == dict(task_id='logic-1', agent_id='logic_correctness')


def test_partial_report_keeps_provenance_and_does_not_reuse_stale_duplicate_relations(tmp_path):
    session, identity, ref = setup(tmp_path)
    record = decision(session.board.candidates[identity], [ref], identity=identity)
    verification = VerificationPhaseResult(decisions=[record], duplicate_groups=[[identity, 'missing']])
    result = _ReviewSession.partial_result(session, AgentPrivateState(stop_reason='invalid_schema'), verification=verification)
    assert not result.duplicate_groups
    assert result.report_draft.coverage.failed['__final'] == 'invalid_schema'


def test_planner_failure_is_not_misattributed_to_a_verifier_that_never_ran(tmp_path):
    session, _, _ = setup(tmp_path)
    result = _ReviewSession.partial_result(session, AgentPrivateState(stop_reason='invalid_schema'), phase='planner')
    assert result.report_draft.coverage.failed == {'__planner': 'invalid_schema'}


def test_restored_synthesis_requires_every_cited_artifact_to_be_fully_inspected(tmp_path):
    import asyncio
    from devwatch.review.contracts import EvidenceProgress
    from tests.test_audit_evidence import engine
    _, _, _, repo, task = setup_repository(tmp_path)
    first = repo._read_source({'file_path':'service.py'}, task).evidence_ref
    second = repo._read_source({'file_path':'service.py', 'start_line':2, 'end_line':2}, task).evidence_ref
    claim = candidate(repo, first)
    progress = {}
    for ref, complete in ((first, True), (second, False)):
        page = repo.evidence_page(ref, task)
        total = page['total_chars']
        progress[ref] = EvidenceProgress(total_chars=total, source_file='service.py',
            delivered=[(0, total)], inspected=[(0, total if complete else 10)])
    private = AgentPrivateState(current_task='__final', evidence_refs=[first, second], evidence_progress=progress)
    verification = VerificationPhaseResult(decisions=[decision(claim, [first, second])])
    restored = dict(snapshot_id=repo.snapshot_id, candidates={'f1':claim},
        task={'agent_id':'synthesizer_verifier'}, phase='synthesis', verification=verification.model_dump(mode='json'))
    runtime, _ = engine(repo, [dict(kind='submit_synthesis', payload=dict(summary='Complete', limitations=[]))] * 2)
    result = asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id, files=task.files, candidates={'f1':claim},
        private_state=private, restored_state=restored))
    assert result['output'] is None
    assert result['private_state'].stop_reason == 'invalid_schema'
