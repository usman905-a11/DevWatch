"""Classified retries share the persisted budget, with no hidden SDK retries."""
import asyncio
import json

import pytest

from devwatch.providers.exceptions import (
    ProviderAuthenticationError, ProviderQuotaExhaustedError, ProviderRateLimitError,
    ProviderTemporaryError, ProviderTimeoutError,
)
from devwatch.review.budgets import BudgetManager
from devwatch.review.subgraphs import AgentSubgraphs, PermissionedTools
from tests.test_control_agents import MODELS
from tests.test_iterative_agents import ScriptedProvider, task, result


class FailingProvider(ScriptedProvider):
    async def generate_completion(self, request):
        response = next(self.responses)
        if isinstance(response, Exception):
            self.requests.append(request)
            raise response
        self.responses = iter([response, *self.responses])
        return await super().generate_completion(request)


@pytest.mark.parametrize("error", [ProviderRateLimitError, ProviderTemporaryError])
def test_two_safe_retries_are_persisted_before_next_attempt(error):
    async def scenario():
        provider = FailingProvider([error("secret upstream details"), error("secret"),
            {"kind": "submit_candidates", "payload": result()}])
        budget, saved, events = BudgetManager(), [], []
        async def persist(state, ledger):
            saved.append((len(provider.requests), ledger))
        engine = AgentSubgraphs(provider, PermissionedTools(), budget, lambda state: {},
            models=MODELS, persist=persist, emit=lambda kind, **metadata: events.append((kind, metadata)))
        output = await engine.run_specialist(task())
        assert output["output"].stop_reason == "evidence_incomplete"
        assert len(provider.requests) == 3
        assert budget.ledger.task_iterations == {"t1": 1}
        assert list(budget.ledger.operation_retries.values()) == [2]
        assert any(calls == 1 and list(ledger["operation_retries"].values()) == [1] for calls, ledger in saved)
        assert any(calls == 2 and list(ledger["operation_retries"].values()) == [2] for calls, ledger in saved)
        retries = [payload for kind, payload in events if kind == "retry_started"]
        assert len(retries) == 2
        assert [payload["attempt"] for payload in retries] == [2, 3]
        assert len([kind for kind, _ in events if kind == "model_call_started"]) == 3
        assert "secret" not in json.dumps(events)
        assert budget.ledger.total_tokens == output["private_state"].usage.total_tokens > 15
        assert not budget.ledger.inflight
    asyncio.run(scenario())


def test_safe_retry_exhaustion_stops_at_three_attempts():
    async def scenario():
        provider = FailingProvider([ProviderTemporaryError("secret")] * 4)
        budget = BudgetManager()
        engine = AgentSubgraphs(provider, PermissionedTools(), budget, lambda state: {}, models=MODELS)
        output = await engine.run_specialist(task())
        assert len(provider.requests) == 3
        assert output["output"].stop_reason == "model_unavailable"
        assert list(budget.ledger.operation_retries.values()) == [2]
    asyncio.run(scenario())


@pytest.mark.parametrize("error", [ProviderQuotaExhaustedError, ProviderAuthenticationError,
                                         ProviderTimeoutError, TimeoutError, RuntimeError])
def test_unclassified_or_unsafe_failures_are_not_retried(error):
    async def scenario():
        provider = FailingProvider([error("secret")] * 4)
        budget = BudgetManager()
        engine = AgentSubgraphs(provider, PermissionedTools(), budget, lambda state: {}, models=MODELS)
        output = await engine.run_specialist(task())
        assert len(provider.requests) == 1
        assert not budget.ledger.operation_retries
        assert output["output"].stop_reason == "model_unavailable"
        assert not budget.ledger.inflight
    asyncio.run(scenario())


def test_provider_adapter_disables_hidden_sdk_retries(monkeypatch):
    from devwatch.providers.openai_adapter import OpenAIProviderAdapter
    monkeypatch.setenv("GEMINI_API_KEY", "test-only")
    config = OpenAIProviderAdapter()._get_client_config()
    assert config["max_retries"] == 0
    asyncio.run(config["http_client"].aclose())


def test_adapter_transport_error_with_unknown_completion_is_not_replayed():
    from devwatch.providers.openai_adapter import OpenAIProviderAdapter
    translated = OpenAIProviderAdapter()._translate_sdk_error(ConnectionResetError("connection reset after submission"))
    async def scenario():
        provider = FailingProvider([translated] * 4)
        budget = BudgetManager()
        engine = AgentSubgraphs(provider, PermissionedTools(), budget, lambda state: {}, models=MODELS)
        output = await engine.run_specialist(task())
        assert len(provider.requests) == 1
        assert not budget.ledger.operation_retries
        assert output["output"].stop_reason == "model_unavailable"
    asyncio.run(scenario())


def test_resume_during_retry_backoff_preserves_operation_and_iteration():
    from devwatch.review.workflow import _serializable
    async def scenario():
        budget, saved = BudgetManager(), []
        first = FailingProvider([ProviderTemporaryError("transient")])
        entered = asyncio.Event()
        async def persist(state, ledger):
            saved.append(_serializable(state))
        async def interrupt(kind, **metadata):
            if kind == "retry_started":
                entered.set()
                await asyncio.Event().wait()
        engine = AgentSubgraphs(first, PermissionedTools(), budget, lambda state: {}, models=MODELS,
                                persist=persist, emit=interrupt)
        operation = asyncio.create_task(engine.run_specialist(task()))
        await asyncio.wait_for(entered.wait(), 2)
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation
        restored = saved[-1]
        from devwatch.review.contracts import AgentPrivateState
        second = FailingProvider([ProviderTemporaryError("transient")] * 4)
        resumed = AgentSubgraphs(second, PermissionedTools(), budget, lambda state: {}, models=MODELS)
        output = await resumed.run_specialist(task(), private_state=AgentPrivateState.model_validate(restored["private_state"]),
                                              restored_state=restored)
        assert len(first.requests) + len(second.requests) == 3
        assert budget.ledger.task_iterations == {"t1": 1}
        assert list(budget.ledger.operation_retries.values()) == [2]
        assert output["output"].stop_reason == "model_unavailable"
    asyncio.run(scenario())


@pytest.mark.parametrize("status", [429, 503])
def test_adapter_confirmed_rejections_remain_retryable(status):
    from devwatch.providers.openai_adapter import OpenAIProviderAdapter
    raw = RuntimeError("confirmed rejection")
    raw.status_code = status
    translated = OpenAIProviderAdapter()._translate_sdk_error(raw)
    async def scenario():
        provider = FailingProvider([translated, {"kind": "submit_candidates", "payload": result()}])
        budget = BudgetManager()
        engine = AgentSubgraphs(provider, PermissionedTools(), budget, lambda state: {}, models=MODELS)
        output = await engine.run_specialist(task())
        assert len(provider.requests) == 2
        assert output["output"].stop_reason == "evidence_incomplete"
    asyncio.run(scenario())


def test_retry_resume_preserves_schema_repair_phase():
    from devwatch.review.contracts import AgentPrivateState
    from devwatch.review.workflow import _serializable
    async def scenario():
        budget, saved = BudgetManager(), []
        first = FailingProvider(["invalid JSON", ProviderTemporaryError("transient")])
        entered = asyncio.Event()
        async def persist(state, ledger):
            saved.append(_serializable(state))
        async def interrupt(kind, **metadata):
            if kind == "retry_started":
                entered.set()
                await asyncio.Event().wait()
        engine = AgentSubgraphs(first, PermissionedTools(), budget, lambda state: {}, models=MODELS, persist=persist, emit=interrupt)
        operation = asyncio.create_task(engine.run_specialist(task()))
        await asyncio.wait_for(entered.wait(), 2)
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation
        second = FailingProvider([{"kind": "submit_candidates", "payload": result()}])
        resumed = AgentSubgraphs(second, PermissionedTools(), budget, lambda state: {}, models=MODELS)
        output = await resumed.run_specialist(task(), private_state=AgentPrivateState.model_validate(saved[-1]["private_state"]),
                                             restored_state=saved[-1])
        assert json.loads(second.requests[0].prompt)["repair"] is not None
        assert budget.ledger.task_schema_repairs == {"t1": 1}
        assert budget.ledger.task_iterations == {"t1": 1}
        assert output["output"].stop_reason == "evidence_incomplete"
    asyncio.run(scenario())
