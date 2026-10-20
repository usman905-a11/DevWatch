"""Consume real graph requests to verify role/phase policy selection and provenance."""
import asyncio
import json

import pytest

from devwatch.review.budgets import BudgetManager
from devwatch.review.contracts import AgentId, AgentPrivateState, SPECIALISTS
from devwatch.review.workflow import _serializable
from tests.test_control_agents import plan_payload
from tests.test_iterative_agents import ScriptedProvider
from tests.test_m16_investigation import complete, engine, read
from tests.test_repository_context import setup_repository


@pytest.mark.asyncio
@pytest.mark.parametrize('role',list(AgentId))
async def test_real_role_requests_are_compact_versioned_and_checkpointed(tmp_path,role):
    _,_,_,repo,task=setup_repository(tmp_path)
    task=task.model_copy(update={'agent_id':role,'focus':'TASK_DATA_ONLY_MARKER'})
    responses=([complete(task)] if role in SPECIALISTS else
        [dict(kind='submit_plan',payload=plan_payload())] if role==AgentId.PLANNER else
        [dict(kind='submit_verification',payload={'decisions':[]}),
         dict(kind='submit_synthesis',payload={'summary':'No candidates','limitations':[]})])
    provider=ScriptedProvider(responses)
    graph=engine(repo,provider)
    if role in SPECIALISTS:
        state=await graph.run_specialist(task)
    elif role==AgentId.PLANNER:
        state=await graph.run_planner(snapshot_id=repo.snapshot_id,files=task.files)
    else:
        state=await graph.run_final(snapshot_id=repo.snapshot_id,files=task.files,candidates={})
    bodies=[json.loads(request.prompt) for request in provider.requests]
    for request,body,observation in zip(provider.requests,bodies,state['provider_observations']):
        assert 'prompt_revision' in body
        revision=body['prompt_revision']
        assert revision['version'] and len(revision['policy_sha256'])==64
        assert observation['prompt_revision']==revision
        assert observation['finish_reason']=='stop' and observation['reported_total_tokens']==15
        assert len(request.system_prompt.encode())<=2000
        assert 'TASK_DATA_ONLY_MARKER' not in request.system_prompt
        assert body['task']['agent_id']==role.value
        expected=(['specialist_completion'] if role in SPECIALISTS else [] if role==AgentId.PLANNER else
            ['verification'] if body['phase']=='verification' else ['synthesis'])
        assert list(body['policy_skills'])==expected
        assert revision['skills']==expected
    if role==AgentId.SYNTHESIZER_VERIFIER:
        assert provider.requests[0].system_prompt==provider.requests[1].system_prompt
        assert bodies[0]['prompt_revision']['policy_sha256']!=bodies[1]['prompt_revision']['policy_sha256']


@pytest.mark.asyncio
async def test_paging_guidance_loads_only_for_partial_evidence_and_keeps_completion(tmp_path):
    _,artifacts,_,original,task=setup_repository(tmp_path)
    from devwatch.review.repository import RepositoryContext
    snapshot=artifacts.capture(owner='alice',files={'service.py':'# '+ 'x'*4000+'\n'})
    repo=RepositoryContext(artifacts,original.cache,snapshot.snapshot_id,owner='alice')
    class Provider(ScriptedProvider):
        async def generate_completion(self,request):
            body=json.loads(request.prompt)
            pages=body['selected_context']['evidence']
            refs=[page['evidence_ref'] for page in pages]
            if not pages:
                action=read()
            elif pages[0]['next_offset'] is not None:
                action=dict(kind='call_tool',tool='read_evidence',arguments={
                    'evidence_ref':refs[0],'offset':pages[0]['next_offset']},inspected_evidence=refs)
            else:
                action=complete(task,refs=refs)
            self.responses=iter([action])
            return await super().generate_completion(request)
    provider=Provider([])
    result=await engine(repo,provider).run_specialist(task)
    bodies=[json.loads(request.prompt) for request in provider.requests]
    assert 'policy_skills' in bodies[0]
    assert 'evidence_paging' not in bodies[0]['policy_skills']
    assert 'evidence_paging' in bodies[1]['policy_skills']
    assert 'evidence_paging' not in bodies[-1]['policy_skills']
    assert result['output'].stop_reason=='evidence_complete'
    assert result['output'].coverage.inspected_files==['service.py']
    assert result['private_state'].tool_call_count==len(bodies)-1


@pytest.mark.asyncio
async def test_restart_keeps_prior_prompt_revision_and_records_new_policy(tmp_path,monkeypatch):
    from devwatch.review import prompts
    _,_,_,repo,task=setup_repository(tmp_path)
    saved,ready,budget=[],asyncio.Event(),BudgetManager()
    async def persist(state,ledger):
        saved.append(_serializable(state))
        if state['private_state'].tool_call_count==1 and state.get('action') is None and not ready.is_set():
            ready.set()
            await asyncio.Event().wait()
    operation=asyncio.create_task(engine(repo,ScriptedProvider([read()]),budget=budget,persist=persist).run_specialist(task))
    await asyncio.wait_for(ready.wait(),10)
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await operation
    restored=saved[-1]
    old=restored['provider_observations'][0]['prompt_revision']
    private=AgentPrivateState.model_validate(restored['private_state'])
    monkeypatch.setattr(prompts,'VERSION',old['version']+'-next')
    provider=ScriptedProvider([complete(task,refs=private.evidence_refs)])
    state=await engine(repo,provider,budget=budget).run_specialist(task,private_state=private,restored_state=restored)
    assert state['provider_observations'][0]['prompt_revision']==old
    new=state['provider_observations'][1]['prompt_revision']
    assert new['version']!=old['version'] and new['policy_sha256']!=old['policy_sha256']
    assert new==json.loads(provider.requests[0].prompt)['prompt_revision']
    assert state['output'].stop_reason=='evidence_complete'
    assert state['private_state'].tool_call_count==1 and budget.ledger.task_iterations[task.task_id]==2
