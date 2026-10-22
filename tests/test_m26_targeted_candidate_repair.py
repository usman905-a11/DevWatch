"""Schema repairs identify the actual missing field without echoing private input."""
import json

import pytest

from devwatch.providers.base import LLMResponse, LLMUsage
from devwatch.review.contracts import AgentPrivateState
from tests.test_m19_candidate_repair import setup
from tests.test_m16_investigation import complete, engine


@pytest.mark.asyncio
async def test_model_can_repair_the_named_missing_field_within_the_existing_one_retry(tmp_path):
    repo, task, ref, good, bad = setup(tmp_path)
    prompts = []
    class Provider:
        async def generate_completion(self, request):
            body = json.loads(request.prompt)
            prompts.append(body)
            repaired = len(prompts) > 1 and 'candidates.0.impact' in body['repair']
            return LLMResponse(content=json.dumps(complete(task, [good if repaired else bad], [ref])),
                provider='fixture', model=request.model, finish_reason='stop', latency_ms=1,
                usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15))
    runtime = engine(repo, Provider())
    state = await runtime.run_specialist(task, private_state=AgentPrivateState(evidence_refs=[ref]))
    assert state['output'].stop_reason == 'evidence_complete'
    assert len(state['output'].candidates) == 1
    assert state['output'].candidates[0].impact == good['impact']
    assert len(prompts) == 2
    assert runtime.budget.ledger.task_schema_repairs[task.task_id] == 1


@pytest.mark.asyncio
async def test_targeted_repair_does_not_reflect_arbitrary_keys_or_values(tmp_path):
    from tests.test_iterative_agents import ScriptedProvider
    repo, task, ref, good, bad = setup(tmp_path)
    bad['PRIVATE_UNKNOWN_FIELD'] = 'PRIVATE_VALUE_NEVER_ECHO'
    bad['title'] = 'PRIVATE_CANDIDATE_TITLE'
    provider = ScriptedProvider([complete(task, [bad], [ref]), complete(task, [good], [ref])])
    state = await engine(repo, provider).run_specialist(task, private_state=AgentPrivateState(evidence_refs=[ref]))
    repair = json.loads(provider.requests[1].prompt)['repair']
    assert 'candidates.0.impact' in repair
    assert not any(value in repair for value in ['PRIVATE_UNKNOWN_FIELD', 'PRIVATE_VALUE_NEVER_ECHO', 'PRIVATE_CANDIDATE_TITLE'])
    assert state['output'].stop_reason == 'evidence_complete'
