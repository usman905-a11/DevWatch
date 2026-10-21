"""Real prompts and tools prove presentation changes without granting authority."""
import asyncio
import json

import pytest

from devwatch.review.budgets import BudgetManager
from devwatch.review.contracts import AgentPrivateState, SPECIALISTS
from devwatch.review.workflow import _serializable
from tests.test_iterative_agents import ScriptedProvider
from tests.test_m16_investigation import complete, engine, read
from tests.test_repository_context import setup_repository


@pytest.mark.asyncio
@pytest.mark.parametrize('role',sorted(SPECIALISTS,key=lambda role:role.value))
async def test_specialists_first_see_source_tools_bound_into_action_schema(tmp_path,role):
    _,_,_,repo,task=setup_repository(tmp_path)
    task=task.model_copy(update={'agent_id':role})
    provider=ScriptedProvider([complete(task)])
    result=await engine(repo,provider).run_specialist(task)
    prompt=json.loads(provider.requests[0].prompt)
    assert [tool['name'] for tool in prompt['tool_catalogue']]==['read_source']
    assert prompt['action_schema']['properties']['tool']['enum']==[None,'read_source']
    assert result['output'].stop_reason=='evidence_incomplete'
    selection=result['tool_selections'][0]
    assert selection['stage']=='source'
    assert selection['selected_tool_count']==1 and selection['role_tool_count']>1
    assert selection['selected_catalogue_bytes']<selection['role_catalogue_bytes']


@pytest.mark.asyncio
async def test_delivered_source_unlocks_analysis_without_hiding_page_retrieval(tmp_path):
    _,_,_,repo,task=setup_repository(tmp_path)
    class Provider(ScriptedProvider):
        async def generate_completion(self,request):
            body=json.loads(request.prompt)
            refs=[page['evidence_ref'] for page in body['selected_context']['evidence']]
            step=len(self.requests)
            action=(read() if step==0 else dict(kind='call_tool',tool='parse_ast',
                arguments={'file_path':'service.py'},inspected_evidence=refs) if step==1 else complete(task,refs=refs))
            self.responses=iter([action])
            return await super().generate_completion(request)
    provider=Provider([])
    result=await engine(repo,provider).run_specialist(task)
    prompts=[json.loads(request.prompt) for request in provider.requests]
    assert len(prompts)==3 and result['private_state'].tool_call_count==2
    assert result['output'].stop_reason=='evidence_complete'
    assert result['output'].coverage.inspected_files==['service.py']
    assert [tool['name'] for tool in prompts[0]['tool_catalogue']]==['read_source']
    assert {'parse_ast','read_source','read_evidence'}.issubset({tool['name'] for tool in prompts[1]['tool_catalogue']})
    for body in prompts:
        assert set(body['action_schema']['properties']['tool']['enum'])=={None,*[tool['name'] for tool in body['tool_catalogue']]}
    assert [item['stage'] for item in result['tool_selections']]==['source','analysis','analysis']


@pytest.mark.asyncio
async def test_synthesis_exposes_no_tools_but_verification_keeps_source_access(tmp_path):
    _,_,_,repo,_=setup_repository(tmp_path)
    provider=ScriptedProvider([dict(kind='submit_verification',payload={'decisions':[]}),
                              dict(kind='submit_synthesis',payload={'summary':'No candidates','limitations':[]})])
    runtime=engine(repo,provider)
    result=await runtime.run_final(snapshot_id=repo.snapshot_id,files=['service.py'],candidates={})
    verify,=[json.loads(request.prompt) for request in provider.requests]
    # Legacy synthesis preparation remains tool-free; normal execution now
    # assembles the verified report without dispatching this request.
    raw,_=runtime._prepare_prompt(result,repo.context(result),repair=False)
    synthesis=json.loads(raw)
    assert 'read_source' in {tool['name'] for tool in verify['tool_catalogue']}
    assert synthesis['tool_catalogue']==[]
    assert synthesis['action_schema']['properties']['tool']['enum']==[None]
    assert not {'call_tool','request_context'}.intersection(synthesis['action_schema']['properties']['kind']['enum'])
    assert result['private_state'].tool_call_count==0


@pytest.mark.asyncio
async def test_unadvertised_role_allowed_action_keeps_authority_and_is_measured(tmp_path):
    _,_,_,repo,task=setup_repository(tmp_path)
    provider=ScriptedProvider([dict(kind='call_tool',tool='parse_ast',arguments={'file_path':'service.py'}),complete(task)])
    result=await engine(repo,provider).run_specialist(task)
    assert result['private_state'].tool_call_count==1
    assert result['output'].stop_reason=='evidence_incomplete'
    assert result['tool_selections'][0]['proposed_tool']=='parse_ast'
    assert result['tool_selections'][0]['advertised'] is False
    assert all('tool_selections' not in json.loads(request.prompt) for request in provider.requests)


@pytest.mark.asyncio
async def test_invented_tool_remains_denied_and_its_name_is_not_copied_into_selection_metrics(tmp_path):
    _,_,_,repo,task=setup_repository(tmp_path)
    provider=ScriptedProvider([dict(kind='call_tool',tool='private-tool-content',arguments={})])
    result=await engine(repo,provider).run_specialist(task)
    assert result['output'].stop_reason=='permission_denied'
    assert result['private_state'].tool_call_count==0
    assert result['tool_selections'][0]['proposed_tool']=='unrecognized_tool'
    assert result['tool_selections'][0]['advertised'] is False
    assert 'private-tool-content' not in json.dumps(result['tool_selections'])


@pytest.mark.asyncio
async def test_restart_recomputes_visible_tools_and_preserves_prior_selection_measurement(tmp_path):
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
    with pytest.raises(asyncio.CancelledError): await operation
    state=saved[-1]
    private=AgentPrivateState.model_validate(state['private_state'])
    provider=ScriptedProvider([complete(task,refs=private.evidence_refs)])
    result=await engine(repo,provider,budget=budget).run_specialist(task,private_state=private,restored_state=state)
    assert result['output'].stop_reason=='evidence_complete'
    assert [item['stage'] for item in result['tool_selections']]==['source','analysis']
    assert 'parse_ast' in {tool['name'] for tool in json.loads(provider.requests[0].prompt)['tool_catalogue']}
    assert result['private_state'].tool_call_count==1 and budget.ledger.task_iterations[task.task_id]==2
