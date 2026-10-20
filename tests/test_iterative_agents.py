"""Real LangGraph iteration and runtime permissions with a scripted provider."""

import asyncio
import importlib
import json

import pytest

from devwatch.providers.base import LLMResponse, LLMUsage
from devwatch.review.budgets import BudgetManager
from devwatch.review.contracts import AgentId, AgentPrivateState, ReviewTask, ModelTier


def runtime():
    assert importlib.util.find_spec("devwatch.review.subgraphs"), "Iterative agent subgraphs are missing"
    return importlib.import_module("devwatch.review.subgraphs")


class ScriptedProvider:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def generate_completion(self, request):
        self.requests.append(request)
        response = next(self.responses)
        return LLMResponse(finish_reason="stop", content=response if isinstance(response, str) else json.dumps(response),
                           provider="scripted", model=request.model, latency_ms=1,
                           usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15))


def task():
    return ReviewTask(task_id="t1", agent_id=AgentId.BUG_RELIABILITY, files=["service.py"], focus="exceptions")


def result():
    return dict(task_id="t1", agent_id="bug_reliability", candidates=[],
                coverage={"inspected_files": ["service.py"]}, stop_reason="evidence_complete")


def test_specialist_investigates_with_tool_then_another_model_iteration():
    api = runtime()
    async def scenario():
        provider = ScriptedProvider([
            {"kind": "call_tool", "tool": "parse_ast", "arguments": {"file_path": "service.py"}},
            {"kind": "submit_candidates", "payload": result(), "inspected_evidence": ["ev-ast"]},
        ])
        tools = api.PermissionedTools()
        async def ast(arguments, review_task):
            return api.ToolObservation(evidence_ref="ev-ast", inspected=["service.py"])
        tools.register("parse_ast", ast)
        budget = BudgetManager()
        async def context(state):
            return {"observations": list(state["private_state"].evidence_refs), "evidence": [
                {"evidence_ref":"ev-ast", "offset":0, "end_offset":2, "total_chars":2, "excerpt":"{}", "source_scope":["service.py"]}
                for ref in state["private_state"].evidence_refs]}
        engine = api.AgentSubgraphs(provider, tools, budget, context,
                                    models={tier: tier.value + "-test" for tier in ModelTier})
        state = await engine.run_specialist(task())
        # Parsed facts support iteration, but cannot stand in for source inspection.
        assert state["output"].coverage.inspected_files == []
        assert state["output"].stop_reason == "evidence_incomplete"
        assert state["private_state"].evidence_refs == ["ev-ast"]
        assert state["private_state"].iteration_count == 2
        assert state["private_state"].tool_call_count == 1
        assert state["private_state"].usage.total_tokens == 30
        assert "ev-ast" in provider.requests[1].prompt
        assert budget.ledger.task_iterations == {"t1": 2}
    asyncio.run(scenario())


def test_denied_tool_never_executes_and_reports_failed_coverage():
    api = runtime()
    async def scenario():
        provider = ScriptedProvider([{"kind": "call_tool", "tool": "profile", "arguments": {}}])
        tools = api.PermissionedTools()
        async def forbidden(*args):
            raise AssertionError("role permission was bypassed")
        tools.register("profile", forbidden)
        engine = api.AgentSubgraphs(provider, tools, BudgetManager(), lambda state: {},
                                    models={tier: tier.value for tier in ModelTier})
        state = await engine.run_specialist(task())
        assert state["output"].stop_reason == "permission_denied"
        assert state["output"].coverage.failed == {"t1": "permission_denied"}
        assert state["private_state"].tool_call_count == 0
    asyncio.run(scenario())


def test_invalid_model_schema_gets_exactly_one_repair():
    api = runtime()
    async def scenario():
        provider = ScriptedProvider(["invalid json", "still invalid json", {"kind": "submit_candidates", "payload": result()}])
        budget = BudgetManager()
        engine = api.AgentSubgraphs(provider, api.PermissionedTools(), budget, lambda state: {},
                                    models={tier: tier.value for tier in ModelTier})
        state = await engine.run_specialist(task())
        assert state["output"].stop_reason == "invalid_schema"
        assert state["output"].coverage.failed == {"t1": "invalid_schema"}
        assert len(provider.requests) == 2
        assert budget.ledger.task_schema_repairs == {"t1": 1}
        assert budget.ledger.total_tokens == 30
    asyncio.run(scenario())


def test_unknown_command_completion_is_explicit_and_never_retried():
    from devwatch.review.jobs import UnknownToolCompletion
    api = runtime()
    async def scenario():
        provider = ScriptedProvider([{"kind": "call_tool", "tool": "run_tests", "arguments": {"command_id": "tests"}}])
        tools = api.PermissionedTools()
        async def unknown(*args):
            raise UnknownToolCompletion("unknown")
        tools.register("run_tests", unknown)
        budget = BudgetManager()
        engine = api.AgentSubgraphs(provider, tools, budget, lambda state: {},
                                    models={tier: tier.value for tier in ModelTier})
        state = await engine.run_specialist(task())
        assert state["output"].stop_reason == "unknown_tool_completion"
        assert state["output"].coverage.failed == {"t1": "unknown_tool_completion"}
        assert len(provider.requests) == 1
        assert not budget.ledger.operation_retries
    asyncio.run(scenario())


def test_followup_of_exhausted_task_does_not_make_another_model_call():
    api = runtime()
    async def scenario():
        budget = BudgetManager()
        for _ in range(8):
            budget.consume_iteration("t1")
        provider = ScriptedProvider([])
        engine = api.AgentSubgraphs(provider, api.PermissionedTools(), budget, lambda state: {},
                                    models={tier: tier.value for tier in ModelTier})
        private = AgentPrivateState(current_task="t1", iteration_count=8)
        state = await engine.run_specialist(task(), private_state=private)
        assert state["output"].stop_reason == "budget_exhausted"
        assert len(provider.requests) == 0
    asyncio.run(scenario())


def test_model_result_cannot_claim_another_agents_task():
    api = runtime()
    async def scenario():
        wrong = result()
        wrong["agent_id"] = "logic_correctness"
        provider = ScriptedProvider([{"kind": "submit_candidates", "payload": wrong}] * 2)
        engine = api.AgentSubgraphs(provider, api.PermissionedTools(), BudgetManager(), lambda state: {},
                                    models={tier: tier.value for tier in ModelTier})
        state = await engine.run_specialist(task())
        assert state["output"].agent_id == AgentId.BUG_RELIABILITY
        assert state["output"].coverage.failed == {"t1": "invalid_schema"}
    asyncio.run(scenario())


def test_ambient_langsmith_tracing_cannot_export_review_data(monkeypatch):
    api = runtime()
    from langchain_core.tracers.langchain import LangChainTracer
    from langsmith import tracing_context
    from langsmith.run_helpers import get_tracing_context
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    # The external tracing dependency may not even be constructed for this path.
    # Prevent network effects while reproducing the ambient-config defect.
    def reject_external_trace(*args, **kwargs):
        raise AssertionError("automatic external tracing was enabled")
    monkeypatch.setattr(LangChainTracer, "__init__", reject_external_trace)
    async def scenario():
        provider = ScriptedProvider([{"kind": "submit_candidates", "payload": result()}])
        engine = api.AgentSubgraphs(provider, api.PermissionedTools(), BudgetManager(),
                                    lambda state: {"tracing_disabled": get_tracing_context()["enabled"] is False},
                                    models={tier: tier.value for tier in ModelTier})
        with tracing_context(enabled=True, parent=False):
            state = await engine.run_specialist(task())
        assert state["output"].stop_reason == "evidence_incomplete"
        assert json.loads(provider.requests[0].prompt)["selected_context"]["tracing_disabled"] is True
    asyncio.run(scenario())


@pytest.mark.parametrize("usage", [None, LLMUsage(total_tokens=150), LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=40)])
def test_missing_total_only_and_inconsistent_usage_cannot_free_token_reservation(usage):
    api = runtime()
    async def scenario():
        class UsageProvider(ScriptedProvider):
            async def generate_completion(self, request):
                response = await super().generate_completion(request)
                if usage is None:
                    return LLMResponse(finish_reason="stop", content=response.content, provider="scripted", model=request.model, latency_ms=0)
                return response.model_copy(update={"usage": usage})
        provider = UsageProvider([{"kind": "submit_candidates", "payload": result()}])
        budget = BudgetManager()
        engine = api.AgentSubgraphs(provider, api.PermissionedTools(), budget, lambda state: {},
                                    models={tier: tier.value for tier in ModelTier})
        state = await engine.run_specialist(task())
        expected = 150 if usage is not None and usage.total_tokens == 150 else 40
        if usage is None:
            assert budget.ledger.total_tokens > 1000
        else:
            assert budget.ledger.total_tokens == expected
        assert state["private_state"].usage.total_tokens == budget.ledger.total_tokens
        assert state["output"].coverage.limitations
        assert not budget.ledger.inflight
    asyncio.run(scenario())


def test_unknown_provider_completion_is_charged_in_private_and_job_usage():
    api = runtime()
    async def scenario():
        class TimeoutProvider(ScriptedProvider):
            async def generate_completion(self, request):
                raise TimeoutError("provider completion unknown")
        budget = BudgetManager()
        engine = api.AgentSubgraphs(TimeoutProvider([]), api.PermissionedTools(), budget, lambda state: {},
                                    models={tier: tier.value for tier in ModelTier})
        state = await engine.run_specialist(task())
        assert state["output"].stop_reason == "model_unavailable"
        assert budget.ledger.total_tokens > 1000
        assert state["private_state"].usage.total_tokens == budget.ledger.total_tokens
        assert state["output"].coverage.limitations
        assert not budget.ledger.inflight
    asyncio.run(scenario())
