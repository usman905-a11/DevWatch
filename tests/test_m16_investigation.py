"""Real source/receipt/graph checks for specialist investigation completion."""
import asyncio
import json

import pytest

from devwatch.review.budgets import BudgetManager
from devwatch.review.contracts import AgentAction, AgentPrivateState, FindingCandidate, ModelTier
from devwatch.review.subgraphs import AgentSubgraphs
from devwatch.review.workflow import _serializable
from devwatch.review.repository import RepositoryContext
from tests.test_audit_evidence import candidate
from tests.test_iterative_agents import ScriptedProvider
from tests.test_repository_context import setup_repository


def complete(task, candidates=(), refs=()):
    return dict(kind='submit_candidates', inspected_evidence=list(refs), payload=dict(task_id=task.task_id,
        agent_id=task.agent_id.value, candidates=list(candidates), coverage={}, stop_reason='evidence_complete'))


def read():
    return dict(kind='call_tool',tool='read_source',arguments={'file_path':'service.py'})


def engine(repo, provider, **options):
    return AgentSubgraphs(provider,repo.tools(),options.pop('budget',BudgetManager()),repo.context,
                          models={tier:tier.value for tier in ModelTier},**options)


@pytest.mark.asyncio
async def test_no_evidence_cannot_be_reported_as_completed_investigation(tmp_path):
    _,_,_,repo,task=setup_repository(tmp_path)
    output=await engine(repo,ScriptedProvider([complete(task)])).run_specialist(task)
    assert output['output'].stop_reason=='evidence_incomplete'
    assert output['output'].coverage.failed[task.task_id]=='evidence_incomplete'
    assert output['output'].coverage.skipped=={'service.py':'not_inspected'}


@pytest.mark.asyncio
async def test_goal_and_required_source_survive_real_tool_and_acknowledgment(tmp_path):
    _,_,_,repo,task=setup_repository(tmp_path)
    task=task.model_copy(update={'focus':'Check empty input'})
    class Provider(ScriptedProvider):
        async def generate_completion(self,request):
            body=json.loads(request.prompt)
            refs=[page['evidence_ref'] for page in body['selected_context']['evidence']]
            self.responses=iter([complete(task,refs=refs) if refs else read()])
            return await super().generate_completion(request)
    provider=Provider([])
    output=await engine(repo,provider).run_specialist(task)
    assert output['output'].stop_reason=='evidence_complete'
    progress=getattr(output['private_state'],'investigation',None)
    assert progress is not None,'No durable investigation progress'
    assert progress.goal=='Check empty input' and progress.required_files==['service.py']
    assert progress.stage=='complete'
    assert json.loads(provider.requests[0].prompt)['investigation']['remaining_files']==['service.py']
    assert output['private_state'].tool_call_count==1 and output['private_state'].iteration_count==2


@pytest.mark.asyncio
async def test_repeating_an_acknowledged_immutable_read_stops_before_second_effect(tmp_path):
    _,_,_,repo,task=setup_repository(tmp_path)
    class Provider(ScriptedProvider):
        async def generate_completion(self,request):
            body=json.loads(request.prompt)
            action=read()
            action['inspected_evidence']=[page['evidence_ref'] for page in body['selected_context']['evidence']]
            self.responses=iter([action])
            return await super().generate_completion(request)
    provider=Provider([])
    output=await engine(repo,provider).run_specialist(task)
    assert output['output'].stop_reason=='no_progress'
    assert len(provider.requests)==2 and output['private_state'].tool_call_count==1
    assert output['output'].coverage.failed[task.task_id]=='no_progress'


@pytest.mark.asyncio
async def test_unacknowledged_source_candidate_gets_one_repair_then_explicit_incomplete_stop(tmp_path):
    _,_,_,repo,task=setup_repository(tmp_path)
    ref=repo._read_source({'file_path':'service.py'},task).evidence_ref
    action=complete(task,[candidate(repo,ref)])
    provider=ScriptedProvider([action,action])
    events=[]
    graph=engine(repo,provider,emit=lambda kind,**payload: events.append((kind,payload)))
    output=await graph.run_specialist(task,private_state=AgentPrivateState(evidence_refs=[ref]))
    assert output['output'].stop_reason=='evidence_incomplete'
    assert output['output'].candidates==[] and len(provider.requests)==2
    assert graph.budget.ledger.task_schema_repairs[task.task_id]==1
    rejected=[payload for kind,payload in events if kind=='candidate_rejected']
    assert len(rejected)==1 and rejected[0]['count']==1
    assert not [kind for kind,_ in events if kind=='candidate_submitted']


@pytest.mark.asyncio
async def test_valid_sibling_survives_evidence_repair_followed_by_invalid_model_response(tmp_path):
    _,_,_,repo,task=setup_repository(tmp_path)
    first=repo._read_source({'file_path':'service.py'},task).evidence_ref
    second=repo._read_source({'file_path':'service.py','start_line':2,'end_line':2},task).evidence_ref
    good,bad={**candidate(repo,first),'title':'Known valid'}, {**candidate(repo,second),'title':'Unacknowledged'}
    provider=ScriptedProvider([complete(task,[good,bad],[first]),'{'])
    output=await engine(repo,provider).run_specialist(task,private_state=AgentPrivateState(evidence_refs=[first,second]))
    assert [item.title for item in output['output'].candidates]==['Known valid']
    assert output['output'].stop_reason=='invalid_schema'


@pytest.mark.asyncio
async def test_acknowledged_ast_cannot_replace_source_retrieval_for_a_finding(tmp_path):
    _,_,_,repo,task=setup_repository(tmp_path)
    observation=await repo.tools().execute(task,AgentAction(kind='call_tool',tool='parse_ast',arguments={'file_path':'service.py'}))
    class Provider(ScriptedProvider):
        async def generate_completion(self,request):
            body=json.loads(request.prompt)
            refs=[page['evidence_ref'] for page in body['selected_context']['evidence']]
            if len(self.requests)==0:
                action=complete(task,[candidate(repo,observation.evidence_ref)],refs)
            elif len(self.requests)==1:
                action=read()
            else:
                source=body['private_state']['evidence_refs'][-1]
                action=complete(task,[candidate(repo,source)],refs)
            self.responses=iter([action])
            return await super().generate_completion(request)
    provider=Provider([])
    output=await engine(repo,provider).run_specialist(task,private_state=AgentPrivateState(evidence_refs=[observation.evidence_ref]))
    assert len(provider.requests)==3
    assert output['output'].stop_reason=='evidence_complete' and len(output['output'].candidates)==1
    assert repo.evidence(output['output'].candidates[0].evidence_refs[0])['tool']=='read_source'


@pytest.mark.asyncio
async def test_uninspected_assigned_sibling_is_explicit_incomplete_coverage(tmp_path):
    _,_,_,repo,task=setup_repository(tmp_path)
    task=task.model_copy(update={'files':['service.py','other.py']})
    ref=repo._read_source({'file_path':'service.py'},task).evidence_ref
    provider=ScriptedProvider([complete(task,refs=[ref])])
    output=await engine(repo,provider).run_specialist(task,private_state=AgentPrivateState(evidence_refs=[ref]))
    assert output['output'].stop_reason=='evidence_incomplete'
    assert output['output'].coverage.inspected_files==['service.py']
    assert output['output'].coverage.skipped=={'other.py':'not_inspected'}


@pytest.mark.asyncio
async def test_later_empty_completion_does_not_erase_a_valid_persisted_candidate(tmp_path):
    _,_,_,repo,task=setup_repository(tmp_path)
    ref=repo._read_source({'file_path':'service.py'},task).evidence_ref
    saved=FindingCandidate.model_validate(candidate(repo,ref))
    provider=ScriptedProvider([complete(task,refs=[ref])])
    output=await engine(repo,provider).run_specialist(task,private_state=AgentPrivateState(
        current_task=task.task_id,evidence_refs=[ref],local_findings=[saved]))
    assert output['output'].candidates==[saved]
    assert output['output'].stop_reason=='evidence_complete'


@pytest.mark.asyncio
async def test_two_unacknowledged_identical_successes_stop_before_a_third_read(tmp_path):
    _,_,_,repo,task=setup_repository(tmp_path)
    provider=ScriptedProvider([read() for _ in range(8)])
    output=await engine(repo,provider).run_specialist(task)
    assert output['output'].stop_reason=='no_progress'
    assert len(provider.requests)==3 and output['private_state'].tool_call_count==2


@pytest.mark.asyncio
async def test_successful_read_guard_survives_checkpoint_restart(tmp_path):
    _,_,_,repo,task=setup_repository(tmp_path)
    saved,ready,budget=[],asyncio.Event(),BudgetManager()
    async def persist(state,ledger):
        saved.append(_serializable(state))
        if state['private_state'].tool_call_count==1 and state.get('action') is None:
            ready.set()
            await asyncio.Event().wait()
    operation=asyncio.create_task(engine(repo,ScriptedProvider([read()]),budget=budget,persist=persist).run_specialist(task))
    await asyncio.wait_for(ready.wait(),10)
    operation.cancel()
    with pytest.raises(asyncio.CancelledError): await operation
    state=saved[-1]
    private=AgentPrivateState.model_validate(state['private_state'])
    ref=private.evidence_refs[0]
    again={**read(),'inspected_evidence':[ref]}
    provider=ScriptedProvider([again,complete(task,refs=[ref])])
    output=await engine(repo,provider,budget=budget).run_specialist(task,private_state=private,restored_state=state)
    assert output['output'].stop_reason=='no_progress'
    assert len(provider.requests)==1 and output['private_state'].tool_call_count==1


@pytest.mark.asyncio
async def test_followup_reuses_inspection_and_findings_without_repeating_a_read(tmp_path):
    _,_,_,repo,task=setup_repository(tmp_path)
    ref=repo._read_source({'file_path':'service.py'},task).evidence_ref
    provider=ScriptedProvider([read(),complete(task,[candidate(repo,ref)],[ref])])
    budget=BudgetManager()
    first=await engine(repo,provider,budget=budget).run_specialist(task)
    changed=task.model_copy(update={'focus':'Recheck this source'})
    provider=ScriptedProvider([read(),complete(changed,[candidate(repo,ref)],[ref])])
    output=await engine(repo,provider,budget=budget).run_specialist(changed,private_state=first['private_state'])
    assert output['output'].stop_reason=='no_progress'
    assert output['output'].candidates==first['output'].candidates
    assert output['private_state'].tool_call_count==1 and len(provider.requests)==1
    assert output['private_state'].investigation.goal=='Recheck this source'


@pytest.mark.asyncio
async def test_completing_missing_inspection_clears_only_its_resolved_task_marker(tmp_path):
    _,_,_,repo,task=setup_repository(tmp_path)
    budget=BudgetManager()
    first=await engine(repo,ScriptedProvider([complete(task)]),budget=budget).run_specialist(task)
    ref=repo._read_source({'file_path':'service.py'},task).evidence_ref
    private=first['private_state']
    private.coverage.failed[task.task_id+':read_source']='recoverable_tool_error'
    provider=ScriptedProvider([read(),complete(task,refs=[ref])])
    output=await engine(repo,provider,budget=budget).run_specialist(task,private_state=private)
    assert output['output'].stop_reason=='evidence_complete'
    assert output['output'].coverage.failed=={task.task_id+':read_source':'recoverable_tool_error'}
    assert output['output'].coverage.skipped=={}


@pytest.mark.asyncio
async def test_advancing_page_offsets_reaches_complete_inspection_without_stall(tmp_path):
    _,artifacts,_,original,task=setup_repository(tmp_path)
    snapshot=artifacts.capture(owner='alice',files={'service.py':'# '+'x'*4000+'\n'})
    repo=RepositoryContext(artifacts,original.cache,snapshot.snapshot_id,owner='alice')
    ref=repo._read_source({'file_path':'service.py'},task).evidence_ref
    class Provider(ScriptedProvider):
        async def generate_completion(self,request):
            body=json.loads(request.prompt)
            page=body['selected_context']['evidence'][0]
            action=(dict(kind='call_tool',tool='read_evidence',arguments={'evidence_ref':ref,'offset':page['next_offset']},
                         inspected_evidence=[ref]) if page['next_offset'] is not None else complete(task,refs=[ref]))
            self.responses=iter([action])
            return await super().generate_completion(request)
    provider=Provider([])
    output=await engine(repo,provider).run_specialist(task,private_state=AgentPrivateState(evidence_refs=[ref]))
    assert output['output'].stop_reason=='evidence_complete'
    assert output['private_state'].evidence_progress[ref].fully_inspected()
    offsets=[json.loads(request.prompt)['selected_context']['evidence'][0]['offset'] for request in provider.requests]
    assert len(offsets)>1 and offsets==sorted(set(offsets))
