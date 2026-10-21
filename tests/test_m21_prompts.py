"""Request byte budgets and schema field integrity must hold together."""
import json
import pytest

from devwatch.review.contracts import AgentPrivateState, AgentWorkItem, ReviewTask
from tests.test_audit_evidence import engine
from tests.test_m20_verification import setup


def prompt(runtime, repo, claim, *, identity='__final', role='synthesizer_verifier', phase='verification'):
    work = ReviewTask if role == 'bug_reliability' else AgentWorkItem
    state = dict(task=work(task_id=identity, agent_id=role, files=['service.py'], focus='Verify supplied candidates'),
        private_state=AgentPrivateState(), phase=phase, snapshot_id=repo.snapshot_id, candidates={'f1':claim})
    return runtime._prepare_prompt(state, dict(snapshot_id=repo.snapshot_id, scope=['service.py'], evidence=[]), repair=False)[0]


def test_final_request_reduces_redundant_metadata_without_losing_claim_or_digest(tmp_path):
    repo, _, _, claim = setup(tmp_path)
    runtime, _ = engine(repo, [])
    raw = prompt(runtime, repo, claim)
    assert len(raw.encode()) < 11000  # Measured M20 equivalent request: 11,570 bytes.
    data = json.loads(raw)
    assert data['candidates']['f1'] == claim
    assert len(data['candidate_digests']['f1']) == 64
    review = data['result_schema']['$defs']['CausalReview']
    assert review['additionalProperties'] is False
    assert review['properties']['candidate_digest']['pattern'] == '^[0-9a-f]{64}$'


def test_compact_specialist_schema_preserves_title_property_and_validation_bounds(tmp_path):
    repo, _, _, claim = setup(tmp_path)
    runtime, _ = engine(repo, [])
    data = json.loads(prompt(runtime, repo, claim, identity='task-1', role='bug_reliability', phase='investigation'))
    candidate = data['result_schema']['$defs']['FindingCandidate']
    assert 'title' in candidate['required']
    assert candidate['properties']['title']['type'] == 'string'
    assert candidate['properties']['confidence']['minimum'] == 0
    assert candidate['properties']['confidence']['maximum'] == 1
    assert candidate['additionalProperties'] is False


@pytest.mark.parametrize('key,exposed', [('action_schema',True),('result_schema',True),
    ('followup_task_ids',True),('SECRET_DO_NOT_ECHO',False)])
def test_copied_request_metadata_is_rejected_with_safe_actionable_repair(tmp_path,key,exposed):
    import asyncio
    from tests.verification_fixtures import decision
    repo, task, ref, claim=setup(tmp_path)
    good=dict(kind='submit_verification',inspected_evidence=[ref],payload=dict(decisions=[decision(claim,[ref])]))
    runtime,provider=engine(repo,[{**good,key:{'private':'do-not-reflect-this-value'}},good])
    state=asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id,files=task.files,candidates={'f1':claim}))
    assert state['private_state'].stop_reason=='evidence_complete'
    assert len(provider.requests)==2
    assert runtime.budget.ledger.task_schema_repairs['__final']==1
    repair=json.loads(provider.requests[1].prompt)['repair']
    assert (key in repair) is exposed
    assert 'do-not-reflect-this-value' not in repair


def test_schema_compaction_does_not_edit_data_defaults_named_title():
    from pydantic import BaseModel
    from devwatch.review.prompts import response_schema
    class Response(BaseModel):
        metadata: dict = {'title': 'User data', 'nested': {'title': 'Keep'}}
    assert response_schema(Response)['properties']['metadata']['default'] == {
        'title': 'User data', 'nested': {'title': 'Keep'}}
