"""Planner failures are bounded and valid plans must actually dispatch work."""

import json

import pytest

from devwatch.review.budgets import BudgetManager
from devwatch.review.contracts import AgentId, BalancedLimits, ModelTier
from devwatch.review.subgraphs import AgentSubgraphs, PermissionedTools, ToolObservation
from tests.test_control_agents import plan_payload
from tests.test_iterative_agents import ScriptedProvider


MODELS = {tier: tier.value for tier in ModelTier}


@pytest.mark.asyncio
async def test_planner_output_allowance_is_configurable_without_raising_total_budget():
    provider = ScriptedProvider([{"kind": "submit_plan", "payload": plan_payload()}])
    limits = BalancedLimits(planner_output_tokens=2048)
    engine = AgentSubgraphs(provider, PermissionedTools(), BudgetManager(limits), lambda state: {}, models=MODELS)
    state = await engine.run_planner(snapshot_id="snapshot", files=["service.py"])
    assert state["output"] is not None
    assert provider.requests[0].max_tokens == 2048
    assert engine.budget.limits.planner_tokens == 25000


@pytest.mark.asyncio
async def test_bare_plan_repairs_to_explicit_action_with_useful_safe_feedback():
    provider = ScriptedProvider([plan_payload(), {"kind": "submit_plan", "payload": plan_payload()}])
    budget = BudgetManager()
    engine = AgentSubgraphs(provider, PermissionedTools(), budget, lambda state: {}, models=MODELS)
    state = await engine.run_planner(snapshot_id="snapshot", files=["service.py"])
    assert state["output"] is not None
    first, repair = provider.requests
    assert first.json_mode is True and first.reasoning_effort == "low"
    assert "submit_plan" in first.system_prompt and "payload" in first.system_prompt
    assert "kind" in json.loads(repair.prompt)["repair"]
    assert budget.ledger.task_schema_repairs == {"__planner": 1}


@pytest.mark.asyncio
async def test_successful_tool_action_clears_prior_schema_repair_guidance():
    provider = ScriptedProvider([plan_payload(), {"kind": "call_tool", "tool": "repo_map"},
                                 {"kind": "submit_plan", "payload": plan_payload()}])
    tools = PermissionedTools()
    async def repo_map(arguments, task):
        return ToolObservation(evidence_ref="map-fixture")
    tools.register("repo_map", repo_map)
    engine = AgentSubgraphs(provider, tools, BudgetManager(), lambda state: {}, models=MODELS)
    state = await engine.run_planner(snapshot_id="snapshot", files=["service.py"])
    assert state["output"] is not None
    assert json.loads(provider.requests[1].prompt)["repair"]
    assert json.loads(provider.requests[2].prompt)["repair"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", ["length", "unknown"])
async def test_planner_incomplete_response_has_one_accounted_recovery(finish):
    class Provider(ScriptedProvider):
        async def generate_completion(self, request):
            response = await super().generate_completion(request)
            return response.model_copy(update={"finish_reason": finish}) if len(self.requests) == 1 else response
    provider = Provider(["incomplete", {"kind": "submit_plan", "payload": plan_payload()}])
    budget, saved = BudgetManager(), []
    engine = AgentSubgraphs(provider, PermissionedTools(), budget, lambda state: {}, models=MODELS,
        persist=lambda state, ledger: saved.append(json.loads(json.dumps(ledger))))
    state = await engine.run_planner(snapshot_id="snapshot", files=["service.py"])
    assert state["output"] is not None
    assert state["private_state"].stop_reason == "evidence_complete"
    assert len(provider.requests) == 2
    assert budget.ledger.task_schema_repairs == {"__planner": 1}
    assert any(row["task_schema_repairs"] == {"__planner": 1} for row in saved)
    assert budget.ledger.total_tokens == 30 and not budget.ledger.inflight
    observations = state["provider_observations"]
    assert [row["finish_reason"] for row in observations] == [finish, "stop"]
    assert observations[0]["content_chars"] == 10
    assert observations[1]["json_shape"] == "object"


@pytest.mark.asyncio
async def test_recovery_cannot_reset_planner_token_ceiling():
    provider = ScriptedProvider([{"kind": "submit_plan", "payload": plan_payload()}])
    budget = BudgetManager()
    ticket = budget.reserve_model(AgentId.PLANNER, 12000)
    budget.record_model(ticket, prompt_tokens=12000, completion_tokens=0)
    # Real registered schemas reproduce the cumulative prompt admission problem.
    from tests.test_repository_context import setup_repository
    from tempfile import TemporaryDirectory
    from pathlib import Path
    with TemporaryDirectory(prefix="devwatch-m13-planner-") as root:
        _, _, _, repo, _ = setup_repository(Path(root))
        engine = AgentSubgraphs(provider, repo.tools(), budget, repo.context, models=MODELS)
        state = await engine.run_planner(snapshot_id=repo.snapshot_id, files=["service.py"])
    assert state["output"] is not None
    request = provider.requests[0]
    bound = len(request.prompt.encode()) + len(request.system_prompt.encode()) + 512
    assert 0 < request.max_tokens < 8192
    assert 12000 + bound + request.max_tokens <= 25000
    assert budget.ledger.total_tokens == 12015


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["empty", "unused_agent", "invented_evidence"])
async def test_invalid_plan_never_silently_completes(mutation):
    payload = plan_payload()
    if mutation == "empty":
        payload.update(selected_agents=[], review_tasks=[])
    elif mutation == "unused_agent":
        payload["selected_agents"].append("bug_reliability")
    else:
        payload["review_tasks"][0]["evidence_refs"] = ["evidence-forged"]
    provider = ScriptedProvider([{"kind": "submit_plan", "payload": payload}] * 2)
    engine = AgentSubgraphs(provider, PermissionedTools(), BudgetManager(), lambda state: {}, models=MODELS)
    state = await engine.run_planner(snapshot_id="snapshot", files=["service.py"])
    assert state["output"] is None
    assert state["private_state"].stop_reason == "invalid_schema"
    assert len(provider.requests) == 2


@pytest.mark.asyncio
async def test_provider_diagnostics_are_persisted_without_response_text():
    secret = "private-source-never-export"
    provider = ScriptedProvider([secret, secret])
    saved, events = [], []
    engine = AgentSubgraphs(provider, PermissionedTools(), BudgetManager(), lambda state: {}, models=MODELS,
        persist=lambda state, ledger: saved.append(json.loads(json.dumps(state.get("provider_observation", {})))),
        emit=lambda kind, **data: events.append((kind, data)))
    state = await engine.run_planner(snapshot_id="snapshot", files=["service.py"])
    assert state["private_state"].stop_reason == "invalid_schema"
    observation = state["provider_observation"]
    assert observation["finish_reason"] == "stop"
    assert observation["content_chars"] == len(secret)
    assert observation["json_shape"] == "invalid_json"
    assert observation["reported_total_tokens"] == 15
    assert any(row.get("content_chars") == len(secret) for row in saved)
    assert secret not in json.dumps(saved) + json.dumps(events)
