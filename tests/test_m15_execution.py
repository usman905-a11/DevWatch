"""Exercise safe correction and ambiguous effects against real execution backends."""

import json
import sys

import pytest

from devwatch.review.budgets import BudgetManager
from devwatch.review.contracts import ModelTier
from devwatch.review.subgraphs import AgentSubgraphs, ToolObservation
from devwatch.review.tool_runtime import TrustedCommand, TrustedToolRuntime
from devwatch.review.workflow import _serializable
from tests.test_iterative_agents import ScriptedProvider
from tests.test_m15_database import configured
from tests.test_m15_recovery import complete
from tests.test_trusted_runtime import setup


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["value", "result_schema"])
async def test_command_failure_after_effect_is_terminal_and_diagnostics_redact_values(tmp_path, monkeypatch, failure):
    artifacts, snapshot, repo, jobs, job, task = setup(tmp_path,
        "from pathlib import Path\nPath('effect').write_text('executed')\n")
    command = TrustedCommand(command_id="probe", tool="run_tests", argv=(sys.executable, "probe.py"), files=("probe.py",))
    runtime = TrustedToolRuntime(repo, jobs, job, commands=(command,))
    def record_failure(*args, **kwargs):
        if failure == "result_schema":
            ToolObservation.model_validate({"evidence_ref": {"private": "private-fixture-exception"}})
        raise ValueError("private-fixture-exception")
    monkeypatch.setattr(repo, "_record", record_failure)
    action = {"kind": "call_tool", "tool": "run_tests", "arguments": {"command_id": "probe"}}
    provider, saved = ScriptedProvider([action, action, complete(task)]), []
    graph = AgentSubgraphs(provider, repo.tools(command_runtime=runtime), BudgetManager(),
        lambda state: {"snapshot_id": snapshot.snapshot_id}, models={tier: tier.value for tier in ModelTier},
        persist=lambda state, ledger: saved.append(_serializable(state)))
    result = await graph.run_specialist(task)
    assert result["output"].stop_reason == "tools_unavailable"
    assert len(provider.requests) == 1 and result["private_state"].tool_call_count == 1
    diagnostic = result["private_state"].tool_diagnostics[-1]
    assert diagnostic.code == "tool_execution_failed" and not diagnostic.recoverable
    assert diagnostic.arguments == {"command_id": "[redacted]"}
    assert "private-fixture-exception" not in json.dumps(saved)
    assert len(list(artifacts.root.glob("scratch/*/effect"))) == 1
    assert runtime.active_processes == 0


@pytest.mark.asyncio
async def test_query_correction_keeps_sql_and_bindings_out_of_feedback_and_checkpoints(tmp_path):
    repo, runtime, task = configured(tmp_path)
    actions = [{"kind": "call_tool", "tool": "query_analyze", "arguments": {
        "database_id": "fixture", "query": "SELECT ? FROM private_missing_table", "parameters": ["private-binding"]}},
        {"kind": "call_tool", "tool": "query_analyze", "arguments": {
            "database_id": "fixture", "query": "SELECT id FROM items"}}, complete(task)]
    provider, saved = ScriptedProvider(actions), []
    graph = AgentSubgraphs(provider, repo.tools(database_runtime=runtime), BudgetManager(), repo.context,
        models={tier: tier.value for tier in ModelTier}, persist=lambda state, ledger: saved.append(_serializable(state)))
    result = await graph.run_specialist(task)
    feedback = json.loads(provider.requests[1].prompt)["tool_diagnostic"]
    assert feedback["code"] == "invalid_query" and feedback["recoverable"]
    assert feedback["arguments"] == {"database_id": "[redacted]", "query": "[redacted]", "parameters": "[redacted]"}
    assert result["output"].stop_reason == "evidence_complete"
    assert result["private_state"].tool_call_count == 2
    assert len(result["private_state"].evidence_refs) == 1
    assert "private_missing_table" not in json.dumps(saved) and "private-binding" not in json.dumps(saved)
    assert "private_missing_table" not in provider.requests[1].prompt and "private-binding" not in provider.requests[1].prompt
