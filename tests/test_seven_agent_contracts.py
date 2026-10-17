"""Enforce the agreed identities, capabilities and planner boundary."""

import importlib

import pytest
from pydantic import ValidationError


def load_contracts():
    # Missing implementation is an explicit failing assertion during the RED step.
    assert importlib.util.find_spec("devwatch.review.contracts"), "Agent contracts are not implemented"
    return importlib.import_module("devwatch.review.contracts")


def test_capabilities_reject_cross_role_tools_and_agent_source_writes():
    contracts = load_contracts()
    bug = contracts.AGENT_CONTRACTS[contracts.AgentId.BUG_RELIABILITY]
    assert bug.authorize_tool("parse_ast") == "parse_ast"
    for denied in ("profile", "write_source", "write_artifact", "publish_report"):
        with pytest.raises(PermissionError):
            bug.authorize_tool(denied)


def test_artifact_permission_requires_performance_task_grant():
    contracts = load_contracts()
    for agent in contracts.AGENT_CONTRACTS.values():
        with pytest.raises(PermissionError):
            agent.authorize_tool("write_artifact")
    performance = contracts.AGENT_CONTRACTS[contracts.AgentId.PERFORMANCE_SCALABILITY]
    assert performance.authorize_tool("write_artifact", produces_measurement_artifact=True) == "write_artifact"
    verifier = contracts.AGENT_CONTRACTS[contracts.AgentId.SYNTHESIZER_VERIFIER]
    with pytest.raises(PermissionError):
        verifier.authorize_tool("write_artifact", produces_measurement_artifact=True)


@pytest.mark.parametrize("identity", ["supervisor", "orchestrator", "router", "verifier", "synthesizer", "budget_manager"])
def test_only_agreed_agent_identities_are_valid(identity):
    contracts = load_contracts()
    with pytest.raises(ValueError):
        contracts.AgentId(identity)


def test_private_state_roundtrip_preserves_usage_as_a_sibling():
    contracts = load_contracts()
    state = contracts.AgentPrivateState(
        current_task="task-1", tool_call_count=4,
        usage={"prompt_tokens": 100, "completion_tokens": 20}, stop_reason="evidence_complete",
    )
    saved = state.model_dump(mode="json")
    resumed = contracts.AgentPrivateState.model_validate(saved)
    assert saved["usage"] == {"prompt_tokens": 100, "completion_tokens": 20}
    assert resumed.tool_call_count == 4
    assert resumed.stop_reason == "evidence_complete"
    with pytest.raises(ValidationError):
        contracts.AgentPrivateState(tool_call_count=-1)


def test_planner_cannot_dispatch_itself_or_an_unselected_specialist():
    contracts = load_contracts()
    base = {
        "selected_agents": ["bug_reliability"], "priority_files": ["service.py"],
        "priority_symbols": [], "risk_areas": ["failure handling"],
        "review_strategy": "Inspect failure paths", "coverage_expectations": ["service.py"],
        "review_tasks": [{"task_id": "t1", "agent_id": "logic_correctness", "files": ["service.py"], "focus": "invariants"}],
    }
    with pytest.raises(ValidationError, match="selected"):
        contracts.ReviewPlan.model_validate(base)
    base["review_tasks"][0]["agent_id"] = "bug_reliability"
    assert contracts.ReviewPlan.model_validate(base).review_tasks[0].task_id == "t1"
    base["selected_agents"] = ["planner"]
    with pytest.raises(ValidationError, match="specialist"):
        contracts.ReviewPlan.model_validate(base)


def test_contract_validates_structured_actions_before_execution():
    contracts = load_contracts()
    planner = contracts.AGENT_CONTRACTS[contracts.AgentId.PLANNER]
    with pytest.raises(PermissionError):
        planner.validate_action(contracts.AgentAction(kind="submit_candidates", payload={}))
    with pytest.raises(ValidationError):
        contracts.AgentAction(kind="call_tool")
    assert planner.validate_action(contracts.AgentAction(kind="call_tool", tool="repo_map")) is None
    with pytest.raises(PermissionError):
        planner.validate_action(contracts.AgentAction(kind="call_tool", tool="run_command"))


def test_candidates_reject_unsafe_locations_and_missing_evidence():
    contracts = load_contracts()
    base = dict(category="bug", title="Crash", description="Empty list crashes", impact="Request fails",
                confidence=0.9, location=dict(snapshot_id="s1", file_path="service.py", start_line=2, end_line=3),
                evidence_refs=["e1"])
    assert contracts.FindingCandidate(**base).location.file_path == "service.py"
    base["evidence_refs"] = []
    with pytest.raises(ValidationError):
        contracts.FindingCandidate(**base)
    base["evidence_refs"] = ["e1"]
    for unsafe in ("../private.py", "C:/secrets.py", "/etc/passwd", "a/../../secret"):
        base["location"]["file_path"] = unsafe
        with pytest.raises(ValidationError):
            contracts.FindingCandidate(**base)
