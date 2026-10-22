"""Delivered, inspected source keeps its authority across candidate provenance."""
import asyncio
from devwatch.review.contracts import AgentId

from tests.test_audit_evidence import candidate, engine
from tests.test_repository_context import setup_repository
from tests.verification_fixtures import decision


def test_final_agent_can_cross_cite_inspected_same_source_from_two_candidates(tmp_path):
    _, _, _, repo, task = setup_repository(tmp_path)
    first = repo._read_source({'file_path': 'service.py'}, task).evidence_ref
    sibling = task.model_copy(update={'task_id':'another-review', 'agent_id':AgentId.BUG_RELIABILITY})
    second = repo._read_source({'file_path': 'service.py'}, sibling).evidence_ref
    assert first != second
    claims = {'f1': candidate(repo, first), 'f2': candidate(repo, second)}
    refs = [first, second]
    action = dict(kind='submit_verification', inspected_evidence=refs, payload=dict(decisions=[
        decision(claim, refs, identity=identity) for identity, claim in claims.items()]))
    runtime, _ = engine(repo, [action, action])
    runtime.require_verification_challenge = True
    state = asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id, files=task.files, candidates=claims))
    assert state['private_state'].stop_reason == 'evidence_complete'
    assert [item.verdict for item in state['verification'].decisions] == ['confirmed', 'confirmed']


def test_a_real_inspected_other_file_cannot_replace_source_covering_the_claim(tmp_path):
    _, _, _, repo, task = setup_repository(tmp_path)
    first = repo._read_source({'file_path': 'service.py'}, task).evidence_ref
    work = task.model_copy(update={'files':['other.py']})
    unrelated = repo._read_source({'file_path':'other.py'}, work).evidence_ref
    claims = {'f1': candidate(repo, first), 'f2': {**candidate(repo, unrelated),
        'location':dict(snapshot_id=repo.snapshot_id, file_path='other.py', start_line=1, end_line=1)}}
    records = [decision(claims['f1'], [unrelated]), decision(claims['f2'], [unrelated], identity='f2')]
    action = dict(kind='submit_verification', inspected_evidence=[first, unrelated], payload=dict(decisions=records))
    runtime, _ = engine(repo, [action, action])
    runtime.require_verification_challenge = True
    state = asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id, files=['service.py','other.py'], candidates=claims))
    assert state['verification'] is None
    assert state['private_state'].stop_reason == 'invalid_schema'
