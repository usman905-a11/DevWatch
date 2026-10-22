"""Known local admission failure must not become unknown remote consumption."""
import asyncio

import pytest

from devwatch.review.budgets import BudgetManager
from devwatch.review.contracts import ModelTier
from devwatch.review.subgraphs import AgentSubgraphs, PermissionedTools
from scripts.evaluate_agents import MeasuredProvider
from tests.test_iterative_agents import ScriptedProvider, task


def engine(provider):
    return AgentSubgraphs(provider, PermissionedTools(), BudgetManager(), lambda state: {},
                          models={tier:'m' for tier in ModelTier})


def test_meter_refusal_before_dispatch_has_zero_runtime_usage_and_known_stop():
    provider = ScriptedProvider([])
    meter = MeasuredProvider(provider, rates={'m':dict(input_per_million=1,output_per_million=1)},
                             max_cost_usd=.0000001)
    runtime = engine(meter)
    state = asyncio.run(runtime.run_specialist(task()))
    assert runtime.budget.ledger.total_tokens == 0
    assert state['private_state'].usage.total_tokens == 0
    assert state['private_state'].stop_reason == 'budget_exhausted'
    assert not runtime.budget.ledger.inflight
    assert not provider.requests
    assert meter.charged_usd == meter.unknown_calls == 0
    assert meter.budget_refusals == 1
    observation, = state['provider_observations']
    assert observation['status'] == 'not_dispatched'
    assert observation['charged_tokens'] == 0
    assert not any('unknown' in text.lower() for text in state['private_state'].coverage.limitations)


@pytest.mark.parametrize('failure', [TimeoutError('network'),
    RuntimeError('evaluation cost cap reached before dispatch')])
def test_untyped_failure_keeps_unknown_reservation_even_when_message_claims_no_dispatch(failure):
    class FailingProvider:
        async def generate_completion(self, request):
            raise failure
    runtime = engine(FailingProvider())
    state = asyncio.run(runtime.run_specialist(task()))
    observation, = state['provider_observations']
    assert observation['status'] == 'unknown'
    assert runtime.budget.ledger.total_tokens == observation['reserved_tokens'] > 0
    assert state['private_state'].usage.total_tokens == observation['reserved_tokens']
    assert not runtime.budget.ledger.inflight


def test_nested_meter_releases_only_a_proven_undispatched_inner_refusal():
    from devwatch.providers.base import LLMRequest
    provider = ScriptedProvider([])
    rates = {'m':dict(input_per_million=1,output_per_million=1)}
    inner = MeasuredProvider(provider,rates=rates,max_cost_usd=.0000001)
    outer = MeasuredProvider(inner,rates=rates,max_cost_usd=1)
    with pytest.raises(RuntimeError):
        asyncio.run(outer.generate_completion(LLMRequest(model='m',prompt='probe',max_tokens=32)))
    assert outer.unknown_calls == 0
    assert outer.charged_usd == 0
    assert outer.budget_refusals == 1
    assert not provider.requests


@pytest.mark.asyncio
async def test_local_refusal_is_not_evaluable_model_reasoning(tmp_path):
    from scripts.evaluate_agents import load_corpus, run_case
    provider=ScriptedProvider([])
    meter=MeasuredProvider(provider,rates={'m':dict(input_per_million=1,output_per_million=1)},max_cost_usd=.0000001)
    row=await run_case(load_corpus()[0],tmp_path,mode='specialist',evidence_mode='provided',provider=meter,
                       models={tier:'m' for tier in ModelTier})
    assert row['failure_categories']==['evaluation_budget']
    assert row['evaluation_eligible'] is False
    assert row['metrics']['ledger_total_tokens']==0
    assert row['metrics']['unknown_provider_calls']==0
