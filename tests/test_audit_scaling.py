import asyncio
import json

import pytest

from devwatch.review.budgets import BudgetManager
from devwatch.review.contracts import AgentPrivateState, BalancedLimits, ModelTier
from devwatch.review.subgraphs import AgentSubgraphs
from tests.test_repository_context import setup_repository
from tests.test_iterative_agents import ScriptedProvider
from tests.test_audit_evidence import candidate


@pytest.mark.parametrize('count',[0,5,24])
def test_small_medium_and_large_reviews_verify_in_bounded_batches_without_loss(tmp_path,count):
    _,_,_,repo,task=setup_repository(tmp_path)
    ref=repo._read_source({'file_path':'service.py'},task).evidence_ref
    candidates={f'f{i}':{**candidate(repo,ref),'title':f'Claim {i}'} for i in range(count)}
    class Provider(ScriptedProvider):
        async def generate_completion(self,request):
            data=json.loads(request.prompt)
            if data['phase']=='verification':
                action=dict(kind='submit_verification',payload={'decisions':[
                    dict(finding_id=identity,verdict='uncertain',confidence=.6,rationale='Caller contract unknown',evidence_refs=[ref])
                    for identity in data['candidates']]})
            else:
                action=dict(kind='submit_synthesis',payload={'summary':'Review assembled','limitations':[]})
            self.responses=iter([action])
            return await super().generate_completion(request)
    provider=Provider([])
    runtime=AgentSubgraphs(provider,repo.tools(),BudgetManager(),repo.context,models={t:t.value for t in ModelTier})
    state=asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id,files=task.files,candidates=candidates))
    assert state['output'] is not None
    assert {f.finding_id for f in state['output'].report_draft.uncertain_high_impact_candidates}==set(candidates)
    batches=[json.loads(r.prompt)['candidates'] for r in provider.requests if json.loads(r.prompt)['phase']=='verification']
    assert max(map(len,batches),default=0)<=8
    assert len(batches)==max(1,(count+7)//8)
    for request in provider.requests:
        assert len(request.prompt.encode())+len(request.system_prompt.encode())+512+request.max_tokens<=32768
        assert request.max_tokens>=min(8192,1024+1024*len(json.loads(request.prompt)['candidates']))


def test_whole_prompt_including_large_private_and_repository_context_is_bounded(tmp_path):
    _,_,_,repo,task=setup_repository(tmp_path)
    provider=ScriptedProvider([dict(kind='finish')])
    private=AgentPrivateState(hypotheses=[{'claim':'x'*3000} for i in range(50)])
    runtime=AgentSubgraphs(provider,repo.tools(),BudgetManager(),lambda state:{'metadata':'界'*40000},models={t:t.value for t in ModelTier})
    state=asyncio.run(runtime.run_specialist(task,private_state=private))
    assert len(provider.requests)==1
    request=provider.requests[0]
    assert len(request.prompt.encode())+len(request.system_prompt.encode())+512+request.max_tokens<=32768
    assert json.loads(request.prompt)['context_omissions']
    assert len(state['private_state'].hypotheses)==50, 'prompt compaction must not erase durable private state'


@pytest.mark.parametrize('finish_reason',['length','content_filter','unknown','missing'])
def test_incomplete_provider_output_is_not_accepted_or_retried_with_same_limits(tmp_path,finish_reason):
    _,_,_,repo,task=setup_repository(tmp_path)
    class Provider(ScriptedProvider):
        async def generate_completion(self,request):
            response=await super().generate_completion(request)
            if finish_reason=='missing':
                return response.model_dump(exclude={'finish_reason'})
            return response.model_copy(update={'finish_reason':finish_reason})
    provider=Provider([dict(kind='finish')]*2)
    runtime=AgentSubgraphs(provider,repo.tools(),BudgetManager(),repo.context,models={t:t.value for t in ModelTier})
    state=asyncio.run(runtime.run_specialist(task))
    assert state['output'].stop_reason==('provider_truncated' if finish_reason=='length' else 'provider_incomplete')
    assert len(provider.requests)==1
    assert runtime.budget.ledger.total_tokens==15
    assert not runtime.budget.ledger.inflight


def test_irreducible_prompt_is_rejected_before_provider_dispatch(tmp_path):
    _,_,_,repo,task=setup_repository(tmp_path)
    task.focus='x'*100000
    provider=ScriptedProvider([dict(kind='finish')])
    runtime=AgentSubgraphs(provider,repo.tools(),BudgetManager(),repo.context,models={t:t.value for t in ModelTier})
    state=asyncio.run(runtime.run_specialist(task))
    assert state['output'].stop_reason=='prompt_context_limit'
    assert not provider.requests


def test_recoverable_tool_error_can_be_followed_by_a_successful_scoped_read(tmp_path):
    _,_,_,repo,task=setup_repository(tmp_path)
    provider=ScriptedProvider([dict(kind='call_tool',tool='parse_ast',arguments={'file_path':'service.py'}),
        dict(kind='call_tool',tool='read_source',arguments={'file_path':'service.py'}),dict(kind='finish')])
    tools=repo.tools()
    async def unavailable(arguments,work):
        raise LookupError('parser unavailable')
    tools._handlers['parse_ast']=unavailable
    runtime=AgentSubgraphs(provider,tools,BudgetManager(),repo.context,models={t:t.value for t in ModelTier})
    state=asyncio.run(runtime.run_specialist(task))
    assert len(state['private_state'].evidence_refs)==1
    assert state['private_state'].tool_call_count==2
    assert state['output'].coverage.failed
