import asyncio

from devwatch.review.contracts import AgentAction, Coverage, FindingCandidate, SpecialistResult
from devwatch.review.repository import SharedBlackboard, StructuralEvidenceGate
from tests.test_repository_context import setup_repository
from tests.test_audit_evidence import candidate


def test_invalid_candidate_does_not_remove_valid_siblings_and_is_quarantined(tmp_path):
    _, _, _, repo, task = setup_repository(tmp_path)
    ref = repo._read_source({'file_path':'service.py'}, task).evidence_ref
    good = candidate(repo,ref)
    second = {**good, 'title':'Another valid claim'}
    invalid = {**good, 'evidence_refs':['forged']}
    board = SharedBlackboard(StructuralEvidenceGate(repo))
    result = SpecialistResult(task_id=task.task_id, agent_id=task.agent_id, candidates=[good,invalid,second],
        coverage=Coverage(failed={'other.py':'tool failed'}),stop_reason='evidence_complete')
    board.publish(task,result)
    assert {item.title for item in board.candidates.values()} == {'Empty list crashes','Another valid claim'}
    assert len(board.quarantined[task.task_id]) == 1
    assert 'invalid evidence reference' in board.quarantined[task.task_id][0].reason
    assert board.coverage().failed['other.py'] == 'tool failed'
    assert board.coverage().failed[task.task_id] == 'invalid_evidence'


def test_schema_invalid_candidate_is_isolated_before_blackboard(tmp_path):
    _, _, _, repo, task = setup_repository(tmp_path)
    ref = repo._read_source({'file_path':'service.py'},task).evidence_ref
    good = candidate(repo,ref)
    result = SpecialistResult.model_validate(dict(task_id=task.task_id,agent_id=task.agent_id,
        candidates=[good, {'title':'Missing fields'}, {**good,'confidence':2}],coverage={},stop_reason='evidence_complete'))
    board = SharedBlackboard(StructuralEvidenceGate(repo))
    board.publish(task,result)
    assert len(board.candidates) == 1
    assert len(board.quarantined[task.task_id]) == 2


def test_candidate_capacity_preserves_admitted_findings_and_records_excess(tmp_path,monkeypatch):
    from devwatch.config import Config
    monkeypatch.setattr(Config,'MAX_CANDIDATE_FINDINGS',2)
    _, _, _, repo, task = setup_repository(tmp_path)
    ref = repo._read_source({'file_path':'service.py'},task).evidence_ref
    board = SharedBlackboard(StructuralEvidenceGate(repo))
    result = SpecialistResult(task_id=task.task_id,agent_id=task.agent_id,candidates=[
        {**candidate(repo,ref),'title':f'Candidate {i}'} for i in range(4)],coverage={},stop_reason='evidence_complete')
    board.publish(task,result)
    assert len(board.candidates)==2
    assert len(board.quarantined[task.task_id])==2
    assert all('capacity' in item.reason for item in board.quarantined[task.task_id])


def test_followup_evidence_merge_is_bounded_and_preserves_previous_failures(tmp_path):
    _,_,_,repo,task=setup_repository(tmp_path)
    ref=repo._read_source({'file_path':'service.py'},task).evidence_ref
    record=repo.evidence(ref)
    refs=[repo._record({**record,'serial':i}).evidence_ref for i in range(16)]
    board=SharedBlackboard(StructuralEvidenceGate(repo))
    for group in [refs[:8],refs[8:]]:
        result=SpecialistResult(task_id=task.task_id,agent_id=task.agent_id,candidates=[candidate(repo,group[0]) | {'evidence_refs':group}],
            coverage=Coverage(failed={'earlier':'tool_failed'} if group==refs[:8] else {}),stop_reason='evidence_complete')
        board.publish(task,result)
    assert len(board.candidates)==1
    assert len(next(iter(board.candidates.values())).evidence_refs)<=8
    assert board.coverage().failed['earlier']=='tool_failed'
