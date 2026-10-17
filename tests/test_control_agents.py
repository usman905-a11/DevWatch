"""Planner and combined final-agent behavior through the real bounded runtime."""

import asyncio
import json

import pytest

from devwatch.review.budgets import BudgetManager
from devwatch.review.contracts import AgentId, ModelTier
from devwatch.review.subgraphs import AgentSubgraphs, PermissionedTools, ToolObservation
from tests.test_iterative_agents import ScriptedProvider


MODELS = {tier: tier.value + "-test" for tier in ModelTier}


def plan_payload(files=None):
    return dict(selected_agents=["logic_correctness"], priority_files=files or ["service.py"],
                priority_symbols=[], risk_areas=["boundary"], review_tasks=[
                    dict(task_id="logic-1", agent_id="logic_correctness", files=files or ["service.py"], focus="boundary")],
                review_strategy="Trace boundary inputs", coverage_expectations=["service.py"])


def verification():
    return dict(decisions=[], duplicate_groups=[], conflicts=[], followup_requests=[])


def synthesis(snapshot="snap-1"):
    return dict(**verification(), report_draft=dict(snapshot_id=snapshot, summary="No defects established", coverage={}),
                coverage_summary={})


def runtime(responses, context=lambda state: {}):
    provider = ScriptedProvider(responses)
    return AgentSubgraphs(provider, PermissionedTools(), BudgetManager(), context, models=MODELS), provider


def test_planner_can_investigate_before_submitting_a_scoped_plan():
    async def scenario():
        engine, provider = runtime([
            dict(kind="call_tool", tool="repo_map"), dict(kind="submit_plan", payload=plan_payload())])
        async def repo_map(arguments, work):
            return ToolObservation(evidence_ref="map-1", inspected=["service.py"])
        engine.tools.register("repo_map", repo_map)
        state = await engine.run_planner(snapshot_id="snap-1", files=["service.py"])
        assert state["output"].review_tasks[0].task_id == "logic-1"
        assert state["private_state"].evidence_refs == ["map-1"]
        assert state["private_state"].iteration_count == 2
        assert provider.requests[0].model == "small-test"
    asyncio.run(scenario())


def test_planner_cannot_dispatch_files_outside_the_snapshot():
    async def scenario():
        engine, provider = runtime([dict(kind="submit_plan", payload=plan_payload(["missing.py"]))] * 2)
        state = await engine.run_planner(snapshot_id="snap-1", files=["service.py"])
        assert state["output"] is None
        assert state["private_state"].stop_reason == "invalid_schema"
        assert len(provider.requests) == 2
    asyncio.run(scenario())


def test_final_agent_verifies_then_synthesizes_with_one_identity():
    async def scenario():
        engine, provider = runtime([dict(kind="submit_verification", payload=verification()),
                                    dict(kind="submit_synthesis", payload=synthesis())])
        state = await engine.run_final(snapshot_id="snap-1", files=["service.py"], candidates={})
        assert state["output"].report_draft.snapshot_id == "snap-1"
        assert [json.loads(request.prompt)["phase"] for request in provider.requests] == ["verification", "synthesis"]
        assert all("synthesizer_verifier" in request.system_prompt for request in provider.requests)
        assert state["private_state"].usage.total_tokens == 30
    asyncio.run(scenario())


def test_synthesis_cannot_run_before_verification():
    async def scenario():
        engine, provider = runtime([dict(kind="submit_synthesis", payload=synthesis())] * 2)
        state = await engine.run_final(snapshot_id="snap-1", files=["service.py"], candidates={})
        assert state["output"] is None
        assert state["private_state"].stop_reason == "invalid_schema"
        assert len(provider.requests) == 2
    asyncio.run(scenario())


def test_synthesis_cannot_change_recorded_verification_decisions():
    async def scenario():
        changed = synthesis()
        changed["decisions"] = [dict(finding_id="invented", verdict="confirmed", confidence=1, rationale="invented", evidence_refs=[])]
        engine, _ = runtime([dict(kind="submit_verification", payload=verification()),
                             dict(kind="submit_synthesis", payload=changed), dict(kind="submit_synthesis", payload=changed)])
        state = await engine.run_final(snapshot_id="snap-1", files=["service.py"], candidates={})
        assert state["output"] is None
        assert state["private_state"].stop_reason == "invalid_schema"
    asyncio.run(scenario())


def test_control_agents_cannot_write_artifacts():
    async def scenario():
        engine, _ = runtime([dict(kind="call_tool", tool="write_artifact")])
        state = await engine.run_planner(snapshot_id="snap-1", files=["service.py"])
        assert state["private_state"].stop_reason == "permission_denied"
        assert state["private_state"].tool_call_count == 0
    asyncio.run(scenario())


def test_complexity_escalates_planner_deterministically_without_an_extra_agent():
    async def scenario():
        engine, provider = runtime([dict(kind="submit_plan", payload=plan_payload())])
        state = await engine.run_planner(snapshot_id="snap-1", files=["service.py"], complexity=0.9)
        assert state["output"].selected_agents == [AgentId.LOGIC_CORRECTNESS]
        assert provider.requests[0].model == "medium-test"
        assert state["escalation_count"] == 1
    asyncio.run(scenario())


def test_accounting_persistence_failure_prevents_provider_effect():
    async def scenario():
        engine, provider = runtime([dict(kind="submit_plan", payload=plan_payload())])
        async def failing_persistence(state, ledger):
            raise OSError("checkpoint unavailable")
        engine.persist = failing_persistence
        with pytest.raises(OSError):
            await engine.run_planner(snapshot_id="snap-1", files=["service.py"])
        assert provider.requests == []
    asyncio.run(scenario())
