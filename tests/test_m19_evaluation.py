"""Real specialist evaluation paths separate delivered source from retrieval."""
import json

import pytest

from scripts.evaluate_agents import load_corpus, review_input, run_case
from tests.evaluation_provider import EvaluationProvider


class RecordingProvider(EvaluationProvider):
    def __init__(self, public, *, acknowledge=True, silent=False):
        super().__init__(public, silent=silent)
        self.requests = []
        self.acknowledge = acknowledge

    async def generate_completion(self, request):
        self.requests.append(request)
        response = await super().generate_completion(request)
        body = json.loads(request.prompt)
        action = json.loads(response.content)
        # External response fixture: claim the actual delivered refs, as a real model can.
        if action['kind'] == 'submit_candidates':
            for candidate in action['payload']['candidates']:
                candidate['evidence_refs'] = [page['evidence_ref'] for page in body['selected_context']['evidence']]
        if not self.acknowledge:
            action.pop('inspected_evidence', None)
        return response.model_copy(update={'content':json.dumps(action)})


@pytest.mark.asyncio
@pytest.mark.parametrize('evidence_mode,tool_calls,prefetched', [('provided',0,1), ('autonomous',1,0)])
async def test_same_defect_is_source_backed_in_both_evaluation_modes(tmp_path,evidence_mode,tool_calls,prefetched):
    case = load_corpus()[0]
    provider = RecordingProvider(review_input(case))
    row = await run_case(case,tmp_path,mode='specialist',evidence_mode=evidence_mode,provider=provider,live=False)
    assert row['status'] == 'completed' and not row['coverage']['failed']
    assert row['score']['true_positive'] == 1 and row['score']['false_positive'] == 0
    assert row['evidence_mode'] == evidence_mode
    assert row['metrics']['prefetched_source_artifacts'] == prefetched
    assert row['metrics']['tool_calls'] == tool_calls
    assert row['metrics']['inspected_source_fraction'] == 1
    assert all(ref in row['evidence'] for finding in row['findings'] for ref in finding['evidence_refs'])
    initial = json.loads(provider.requests[0].prompt)
    assert bool(initial['selected_context']['evidence']) == (evidence_mode=='provided')
    assert 'defect_id' not in provider.requests[0].prompt
    assert case['gold'][0]['explanation'] not in provider.requests[0].prompt


@pytest.mark.asyncio
async def test_provided_source_is_not_automatically_acknowledged(tmp_path):
    case = load_corpus()[0]
    provider = RecordingProvider(review_input(case),acknowledge=False)
    row = await run_case(case,tmp_path,mode='specialist',evidence_mode='provided',provider=provider,live=False)
    assert row['metrics']['prefetched_source_artifacts'] == 1
    assert row['metrics']['inspected_source_fraction'] == 0
    assert row['coverage']['failed'] and row['score']['true_positive'] == 0


@pytest.mark.asyncio
async def test_provided_source_does_not_hide_a_silent_reasoning_miss(tmp_path):
    case = load_corpus()[0]
    row = await run_case(case,tmp_path,mode='specialist',evidence_mode='provided',
        provider=RecordingProvider(review_input(case),silent=True),live=False)
    assert row['metrics']['tool_calls'] == 0 and row['metrics']['inspected_source_fraction'] == 1
    assert row['score']['false_negative'] == 1
    assert row['failure_categories'] == ['model_reasoning']


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,evidence_mode', [('full','provided'),('specialist','unknown')])
async def test_invalid_evidence_mode_is_rejected_before_runtime_effects(tmp_path,mode,evidence_mode):
    with pytest.raises(ValueError,match='evidence'):
        await run_case(load_corpus()[0],tmp_path,mode=mode,evidence_mode=evidence_mode,
            provider=None,live=False)
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize('expected_kind,correct', [('defect',1), ('advisory',0)])
async def test_kind_measurement_is_separate_from_primary_detection(tmp_path,expected_kind,correct):
    case=load_corpus()[0]
    case['gold'][0]['kind']=expected_kind
    row=await run_case(case,tmp_path,mode='specialist',evidence_mode='provided',
        provider=RecordingProvider(review_input(case)),live=False)
    assert row['score']['true_positive']==1 and row['score']['false_positive']==0
    assert row['metrics']['finding_kind_evaluated']==1
    assert row['metrics']['finding_kind_correct']==correct


@pytest.mark.asyncio
async def test_local_budget_refusal_is_distinct_from_provider_consumption_or_reasoning(tmp_path):
    from scripts.evaluate_agents import MeasuredProvider
    case=load_corpus()[0]
    provider=RecordingProvider(review_input(case))
    meter=MeasuredProvider(provider,rates={tier+'-scripted':{'input_per_million':1,'output_per_million':1}
        for tier in ('small','medium','strong')},
        max_cost_usd=.000001)
    row=await run_case(case,tmp_path,mode='specialist',evidence_mode='provided',provider=meter,live=False)
    assert row['failure_categories']==['evaluation_budget']
    assert row['metrics']['local_budget_refusals']==1
    assert row['metrics']['unknown_provider_calls']==0 and not provider.requests


def test_cli_provided_mode_scores_real_source_provenance(tmp_path):
    from scripts.run_agent_evaluation import main
    path=tmp_path/'result.json'
    assert main(['--fixture','--mode','specialist','--evidence-mode','provided',
        '--case','empty-defect','--output',str(path)])==0
    row=json.loads(path.read_text())['results'][0]
    assert row['score']['true_positive']==1 and not row['coverage']['failed']
    assert row['metrics']['tool_calls']==0 and row['metrics']['prefetched_source_artifacts']==1


@pytest.mark.parametrize('mode',['full','both'])
def test_cli_rejects_provided_full_evaluation_without_creating_output(tmp_path,mode):
    from scripts.run_agent_evaluation import main
    with pytest.raises(SystemExit) as error:
        main(['--fixture','--mode',mode,'--evidence-mode','provided','--output',str(tmp_path/'unused.json')])
    assert error.value.code==2 and not list(tmp_path.iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize('role,expected',[
    ('performance_scalability',['specialist_completion','performance_cost']),
    ('bug_reliability',['specialist_completion']),
])
async def test_cost_guidance_loads_after_real_source_delivery_only_for_performance(tmp_path,role,expected):
    from devwatch.review.contracts import AgentId
    from tests.test_iterative_agents import ScriptedProvider
    from tests.test_m16_investigation import complete,engine,read
    from tests.test_repository_context import setup_repository
    _,_,_,repo,task=setup_repository(tmp_path)
    task=task.model_copy(update={'agent_id':AgentId(role)})
    class Provider(ScriptedProvider):
        async def generate_completion(self,request):
            body=json.loads(request.prompt)
            refs=[page['evidence_ref'] for page in body['selected_context']['evidence']]
            self.responses=iter([complete(task,refs=refs) if refs else read()])
            return await super().generate_completion(request)
    provider=Provider([])
    result=await engine(repo,provider).run_specialist(task)
    assert result['output'].stop_reason=='evidence_complete'
    first,second=[json.loads(request.prompt) for request in provider.requests]
    assert list(first['policy_skills'])==['specialist_completion']
    assert list(second['policy_skills'])==expected
    assert second['prompt_revision']['skills']==expected
