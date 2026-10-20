"""All-invalid batches get bounded schema repair without erasing good siblings."""
import json

import pytest

from devwatch.review.budgets import BudgetManager
from devwatch.review.contracts import AgentPrivateState, BalancedLimits
from tests.test_audit_evidence import candidate
from tests.test_iterative_agents import ScriptedProvider
from tests.test_m16_investigation import complete, engine
from tests.test_repository_context import setup_repository


def setup(tmp_path):
    _,_,_,repo,task=setup_repository(tmp_path)
    ref=repo._read_source({'file_path':'service.py'},task).evidence_ref
    good=candidate(repo,ref)
    bad=dict(good)
    bad.pop('impact')
    return repo,task,ref,good,bad


@pytest.mark.asyncio
async def test_recognized_claim_with_missing_impact_gets_one_repair_and_source_backed_admission(tmp_path):
    repo,task,ref,good,bad=setup(tmp_path)
    provider=ScriptedProvider([complete(task,[bad],[ref]),complete(task,[good],[ref])])
    graph=engine(repo,provider)
    result=await graph.run_specialist(task,private_state=AgentPrivateState(evidence_refs=[ref]))
    assert len(provider.requests)==2 and result['output'].stop_reason=='evidence_complete'
    assert len(result['output'].candidates)==1 and not result['output'].quarantined
    assert not result['output'].coverage.failed
    assert graph.budget.ledger.task_schema_repairs[task.task_id]==1
    assert 'impact' in json.loads(provider.requests[1].prompt)['repair']


@pytest.mark.asyncio
@pytest.mark.parametrize('repairs,calls',[(0,1),(1,2)])
async def test_repeated_invalid_candidates_stop_at_existing_repair_ceiling_and_remain_quarantined(tmp_path,repairs,calls):
    repo,task,ref,_,bad=setup(tmp_path)
    provider=ScriptedProvider([complete(task,[bad],[ref])]*3)
    graph=engine(repo,provider,budget=BudgetManager(BalancedLimits(schema_repairs_per_task=repairs)))
    result=await graph.run_specialist(task,private_state=AgentPrivateState(evidence_refs=[ref]))
    assert len(provider.requests)==calls and result['output'].stop_reason=='invalid_schema'
    assert result['output'].candidates==[] and len(result['output'].quarantined)==1
    assert result['output'].coverage.failed[task.task_id]=='invalid_schema'


@pytest.mark.asyncio
async def test_mixed_valid_and_invalid_batch_keeps_existing_sibling_quarantine_behavior(tmp_path):
    repo,task,ref,good,bad=setup(tmp_path)
    provider=ScriptedProvider([complete(task,[good,bad],[ref])])
    result=await engine(repo,provider).run_specialist(task,private_state=AgentPrivateState(evidence_refs=[ref]))
    assert len(provider.requests)==1
    assert len(result['output'].candidates)==1 and len(result['output'].quarantined)==1


@pytest.mark.asyncio
async def test_evaluator_reports_candidate_validation_failure_separately_from_reasoning(tmp_path):
    from scripts.evaluate_agents import load_corpus, review_input, run_case
    from tests.test_m19_evaluation import RecordingProvider
    class Malformed(RecordingProvider):
        async def generate_completion(self,request):
            response=await super().generate_completion(request)
            action=json.loads(response.content)
            for item in action.get('payload',{}).get('candidates',[]): item.pop('impact',None)
            return response.model_copy(update={'content':json.dumps(action)})
    case=load_corpus()[0]
    row=await run_case(case,tmp_path,mode='specialist',evidence_mode='provided',
        provider=Malformed(review_input(case)),live=False)
    assert row['score']['false_negative']==1 and row['metrics']['inspected_source_fraction']==1
    assert row['failure_categories']==['candidate_validation']
    assert len(row['quarantined_candidates'])==1
