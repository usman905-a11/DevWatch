"""Correctable and terminal failures through actual tool/graph boundaries."""

import asyncio
import json

import pytest

from devwatch.review.budgets import BudgetManager
from devwatch.review.contracts import AGENT_CONTRACTS, AgentPrivateState, BalancedLimits, ModelTier
from devwatch.review.repository import RepositoryContext
from devwatch.review.subgraphs import AgentSubgraphs
from devwatch.review.workflow import _serializable
from tests.test_iterative_agents import ScriptedProvider
from tests.test_repository_context import setup_repository


def read(start=99):
    return {"kind": "call_tool", "tool": "read_source", "arguments": {"file_path": "service.py", "start_line": start}}


def complete(task):
    return {"kind": "submit_candidates", "payload": {"task_id": task.task_id,
        "agent_id": task.agent_id.value, "candidates": [], "coverage": {}, "stop_reason": "evidence_complete"}}


def engine(repo, provider, *, budget=None, persist=None, emit=None):
    return AgentSubgraphs(provider, repo.tools(), budget or BudgetManager(), repo.context,
                          models={tier: tier.value for tier in ModelTier}, persist=persist, emit=emit)


@pytest.mark.asyncio
async def test_range_feedback_guides_correction_and_clears_only_active_error(tmp_path):
    _, _, _, repo, task = setup_repository(tmp_path)
    ref = repo._read_source({'file_path': 'service.py'}, task).evidence_ref
    provider = ScriptedProvider([read(), read(1), {**complete(task), 'inspected_evidence': [ref]}])
    output = await engine(repo, provider).run_specialist(task)
    feedback = json.loads(provider.requests[1].prompt).get("tool_diagnostic")
    assert feedback is not None, "range error has no actionable structured feedback"
    assert feedback["code"] == "invalid_source_range"
    assert feedback["arguments"] == {"file_path": "service.py", "start_line": 99}
    assert feedback["details"] == {"line_count": 2, "max_lines": 200}
    assert output["output"].stop_reason == "evidence_complete"
    assert json.loads(provider.requests[2].prompt)["tool_diagnostic"] is None
    assert len(output["private_state"].tool_diagnostics) == 1
    assert output["private_state"].tool_call_count == 2


@pytest.mark.asyncio
async def test_identical_failure_with_equivalent_defaults_never_reexecutes(tmp_path):
    _, _, _, repo, task = setup_repository(tmp_path)
    second = read()
    second["arguments"]["end_line"] = None
    provider = ScriptedProvider([read(), second, complete(task)])
    output = await engine(repo, provider).run_specialist(task)
    assert output["output"].stop_reason == "tools_unavailable"
    assert len(provider.requests) == 2
    assert output["private_state"].tool_call_count == 1
    assert output["private_state"].tool_diagnostics[-1].code == "repeated_tool_failure"


@pytest.mark.asyncio
async def test_repeated_invalid_arguments_stop_without_consuming_tool_effects(tmp_path):
    _, _, _, repo, task = setup_repository(tmp_path)
    bad = {"kind": "call_tool", "tool": "read_source", "arguments": {"file_path": "service.py", "start_line": True}}
    provider = ScriptedProvider([bad, bad, complete(task)])
    output = await engine(repo, provider).run_specialist(task)
    assert output["output"].stop_reason == "tools_unavailable"
    assert len(provider.requests) == 2 and output["private_state"].tool_call_count == 0


@pytest.mark.asyncio
async def test_failure_guard_survives_checkpoint_restart(tmp_path):
    _, _, _, repo, task = setup_repository(tmp_path)
    saved, budget, failed = [], BudgetManager(), asyncio.Event()
    async def checkpoint(state, ledger):
        saved.append(_serializable(state))
        if state.get("last_tool_error"):
            failed.set()
            await asyncio.Event().wait()  # Pause between known failure and next model request.
    operation = asyncio.create_task(engine(repo, ScriptedProvider([read()]), budget=budget,
                                         persist=checkpoint).run_specialist(task))
    await asyncio.wait_for(failed.wait(), 10)
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await operation
    state = saved[-1]
    second = ScriptedProvider([read(), complete(task)])
    output = await engine(repo, second, budget=budget).run_specialist(task,
        private_state=AgentPrivateState.model_validate(state["private_state"]), restored_state=state)
    assert output["output"].stop_reason == "tools_unavailable"
    assert output["private_state"].tool_call_count == 1
    assert len(second.requests) == 1


@pytest.mark.asyncio
async def test_diagnostics_redact_unknown_values_and_never_enter_public_events(tmp_path):
    _, _, _, repo, task = setup_repository(tmp_path)
    bad = read(1)
    bad["arguments"]["api_key"] = "private-fixture-token"
    provider, saved, events = ScriptedProvider([bad, complete(task)]), [], []
    output = await engine(repo, provider, persist=lambda state, ledger: saved.append(_serializable(state)),
                          emit=lambda kind, **metadata: events.append({"kind": kind, **metadata})).run_specialist(task)
    feedback = json.loads(provider.requests[1].prompt).get("tool_diagnostic")
    assert feedback is not None and feedback["code"] == "invalid_arguments"
    assert feedback["redacted_fields"] == 1
    assert "private-fixture-token" not in json.dumps(saved)
    assert "private-fixture-token" not in provider.requests[1].prompt
    assert all("arguments" not in event and "tool_diagnostic" not in event for event in events)
    assert output["private_state"].tool_call_count == 0


@pytest.mark.asyncio
async def test_integrity_failure_stops_before_another_model_call(tmp_path):
    _, _, _, repo, task = setup_repository(tmp_path)
    ref = repo._read_source({"file_path": "service.py"}, task).evidence_ref
    path = repo.evidence_root / (ref + ".json")
    value = json.loads(path.read_text(encoding="utf-8"))
    value["data"] = "tampered"
    path.write_text(json.dumps(value), encoding="utf-8")
    provider = ScriptedProvider([{"kind": "call_tool", "tool": "read_evidence", "arguments": {"evidence_ref": ref}}, complete(task)])
    output = await engine(repo, provider).run_specialist(task)
    assert output["output"].stop_reason == "tools_unavailable"
    assert len(provider.requests) == 1
    assert output["private_state"].tool_diagnostics[-1].code == "evidence_integrity_failure"
    assert not output["private_state"].evidence_refs


@pytest.mark.asyncio
async def test_context_integrity_failure_is_attributed_to_tools_before_model_dispatch(tmp_path):
    _, _, _, repo, task = setup_repository(tmp_path)
    ref = repo._read_source({"file_path": "service.py"}, task).evidence_ref
    path = repo.evidence_root / (ref + ".json")
    value = json.loads(path.read_text(encoding="utf-8"))
    value["data"] = "tampered"
    path.write_text(json.dumps(value), encoding="utf-8")
    provider = ScriptedProvider([complete(task)])
    output = await engine(repo, provider).run_specialist(task,
        private_state=AgentPrivateState(current_task=task.task_id, evidence_refs=[ref]))
    assert output["output"].stop_reason == "tools_unavailable"
    assert not provider.requests
    assert output["private_state"].tool_diagnostics[-1].code == "evidence_integrity_failure"
    assert output["private_state"].tool_diagnostics[-1].arguments == {"evidence_ref": ref}


@pytest.mark.asyncio
async def test_page_that_cannot_fit_is_never_marked_delivered_or_inspected(tmp_path):
    _, artifacts, _, original, task = setup_repository(tmp_path)
    snapshot = artifacts.capture(owner="alice", files={"service.py": "# " + "x" * 4000 + "\n"})
    repo = RepositoryContext(artifacts, original.cache, snapshot.snapshot_id, owner="alice")
    ref = repo._read_source({"file_path": "service.py"}, task).evidence_ref
    private = AgentPrivateState(current_task=task.task_id, iteration_count=1, evidence_refs=[ref])
    provider = ScriptedProvider([complete(task)])
    graph = engine(repo, provider)
    # Fit mandatory schemas and a small response, but not the actual 1,500-char
    # page. Compute the budget from this role's real schema instead of a magic
    # model-context number that could fail at Planner admission first.
    # Source pages make the analysis catalogue relevant. Size that real request
    # with its page removed, so the bound still isolates page delivery itself.
    state = {"task": task, "private_state": private}
    prompt, _ = graph._prepare_prompt(state, repo.context(state), repair=False)
    body = json.loads(prompt)
    body["selected_context"] = {"snapshot_id": snapshot.snapshot_id, "scope": task.files, "evidence": []}
    prompt = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    mandatory = len(prompt.encode()) + len(AGENT_CONTRACTS[task.agent_id].system_prompt.encode()) + 512
    graph.budget = BudgetManager(limits=BalancedLimits(model_context_tokens=mandatory + 700))
    private.iteration_count = 0
    result = await graph.run_specialist(task, private_state=private)
    assert result["output"].stop_reason == "evidence_incomplete"
    request = provider.requests[0]
    body = json.loads(request.prompt)
    assert "evidence_page; retrieve via read_evidence" in body["context_omissions"]
    assert not body["selected_context"]["evidence"]
    assert len(request.prompt.encode()) + len(request.system_prompt.encode()) + 512 + request.max_tokens <= mandatory + 700
    assert request.max_tokens >= 512
    assert not result["private_state"].evidence_progress
    assert not result["output"].coverage.inspected_files
    assert result["output"].coverage.skipped["service.py"] == "not_inspected"
