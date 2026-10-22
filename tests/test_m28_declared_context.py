"""Caller-declared behavior reaches every role without widening task permissions."""
import json

import pytest
from fastapi.testclient import TestClient

from devwatch.review.budgets import BudgetManager
from devwatch.review.contracts import AgentId, AgentPrivateState, AgentWorkItem, ReviewTask, ModelTier
from devwatch.review.repository import RepositoryContext
from devwatch.review.stores import RepoCache
from devwatch.review.workflow import CanonicalReviewExecutor, _ReviewSession
from tests.test_canonical_workflow import ReviewProvider, stores
from tests.test_control_agents import MODELS
from tests.test_review_service import ALICE, app


def test_job_accepts_and_persists_explicit_snapshot_context(tmp_path):
    with TestClient(app(tmp_path)) as client:
        snapshot=client.post('/api/snapshots',headers=ALICE,json={'files':{
            'service.py':'def first(items):\n    return items[0]\n',
            'constraints.txt':'Only nonempty lists are supported.\n'}}).json()['snapshot_id']
        response=client.post('/api/jobs',headers={**ALICE,'Idempotency-Key':'declared-context'},
            json=dict(snapshot_id=snapshot,context_files=['constraints.txt']))
        assert response.status_code==202,response.text
        import hashlib
        owner='key-'+hashlib.sha256(ALICE['X-API-Key'].encode()).hexdigest()
        job=client.app.state.jobs.get(response.json()['job_id'],owner=owner)
        assert job.request['context_files']==['constraints.txt']
        repeated=client.post('/api/jobs',headers={**ALICE,'Idempotency-Key':'declared-context'},
            json=dict(snapshot_id=snapshot,context_files=['constraints.txt']))
        assert repeated.status_code==202 and repeated.json()['job_id']==job.job_id
        different=client.post('/api/jobs',headers={**ALICE,'Idempotency-Key':'declared-context'},
            json=dict(snapshot_id=snapshot,context_files=[]))
        assert different.status_code==409


@pytest.mark.parametrize('paths,size,status', [(['missing.txt'],10,422),
    (['constraints.txt'],6001,422), (['constraints.txt']*5,10,422)])
def test_context_is_bounded_and_owned_before_job_creation(tmp_path,paths,size,status):
    with TestClient(app(tmp_path)) as client:
        snapshot=client.post('/api/snapshots',headers=ALICE,json={'files':{
            'service.py':'pass\n','constraints.txt':'x'*size}}).json()['snapshot_id']
        response=client.post('/api/jobs',headers={**ALICE,'Idempotency-Key':'invalid-context'},
            json=dict(snapshot_id=snapshot,context_files=paths))
        assert response.status_code==status,response.text


def test_declared_context_is_delivered_to_every_role_without_scope_or_receipt_inflation(tmp_path):
    layout,artifacts,_,jobs,events=stores(tmp_path)
    snapshot=artifacts.capture(owner='alice',files={
        'service.py':'def first(items):\n    return items[0]\n',
        'constraints.txt':'Only nonempty lists are supported.\n'})
    job=jobs.submit(owner='alice',request=dict(snapshot_id=snapshot.snapshot_id,context_files=['constraints.txt']),
                    idempotency_key='context-everywhere')
    repository=RepositoryContext(artifacts,RepoCache(layout.repo_cache),snapshot.snapshot_id,owner='alice')
    executor=CanonicalReviewExecutor(layout,artifacts,RepoCache(layout.repo_cache),jobs,events,ReviewProvider(),models=MODELS)
    session=_ReviewSession(executor,job,repository,BudgetManager(job.limits),['service.py'])
    for role in AgentId:
        schema=AgentWorkItem if role in {AgentId.PLANNER,AgentId.SYNTHESIZER_VERIFIER} else ReviewTask
        task=schema(task_id='scope-'+role.value,agent_id=role,files=['service.py'],focus='Review code')
        private=AgentPrivateState()
        selected=session.context(dict(task=task,private_state=private))
        assert selected['declared_context']['files'][0]['content']=='Only nonempty lists are supported.\n'
        assert selected['declared_context']['files'][0]['file_path']=='constraints.txt'
        assert task.files==['service.py']
        assert not private.evidence_progress and not private.coverage.inspected_files


def test_prompt_pressure_never_silently_discards_declared_context(tmp_path):
    from tests.test_m16_investigation import engine
    from tests.test_repository_context import setup_repository
    from tests.test_iterative_agents import ScriptedProvider
    from devwatch.review.subgraphs import PromptContextLimit
    _,_,_,repo,task=setup_repository(tmp_path)
    runtime=engine(repo,ScriptedProvider([]))
    state=dict(task=task,private_state=AgentPrivateState(),model_tier=ModelTier.MEDIUM)
    with pytest.raises(PromptContextLimit):
        runtime._prepare_prompt(state,{'declared_context':{'files':[{'content':'x'*200000}]}},repair=False)


def test_cli_submit_shares_declared_context_through_the_real_client(tmp_path,monkeypatch):
    from tests.test_durable_cli import connect, runner, cli
    with TestClient(app(tmp_path)) as http:
        client,transport=connect(monkeypatch,http)
        snapshot=http.post('/api/snapshots',headers=ALICE,json={'files':{
            'service.py':'def first(items):\n    return items[0]\n',
            'constraints.txt':'Only nonempty lists are supported.\n'}}).json()['snapshot_id']
        result=runner.invoke(cli,['submit',snapshot,'--idempotency-key','cli-context',
            '--changed-file','service.py','--context-file','constraints.txt'])
        assert result.exit_code==0,result.output
        requests=[request for request in transport.requests if request.full_url.endswith('/api/jobs')]
        assert json.loads(requests[0].data)['context_files']==['constraints.txt']
