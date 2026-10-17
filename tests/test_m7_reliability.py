"""Local recovery uses bounded feedback and retains independently valid work."""

import asyncio
import json
import sqlite3

import pytest

from devwatch.providers.base import LLMResponse, LLMUsage
from devwatch.review.budgets import BudgetManager
from devwatch.review.contracts import AgentId, AgentPrivateState, FindingCandidate, TokenUsage
from devwatch.review.jobs import DurableJobManager, JobConflict
from devwatch.review.stores import RepoCache
from devwatch.review.subgraphs import AgentSubgraphs, PermissionedTools, ToolObservation
from devwatch.review.workflow import CanonicalReviewExecutor, _ReviewSession, _serializable
from tests.test_canonical_workflow import ReviewProvider, stores
from tests.test_control_agents import MODELS, plan_payload
from tests.test_iterative_agents import ScriptedProvider, result, task


@pytest.mark.parametrize("error", [LookupError, ValueError, FileNotFoundError])
def test_recoverable_tool_failure_reaches_next_prompt_without_raw_details(error):
    async def scenario():
        tools = PermissionedTools()
        async def unavailable(arguments, work):
            raise error("private token and source text")
        tools.register("parse_ast", unavailable)
        provider = ScriptedProvider([
            {"kind": "call_tool", "tool": "parse_ast", "arguments": {"file_path": "service.py"}},
            {"kind": "submit_candidates", "payload": result()},
        ])
        saved = []
        engine = AgentSubgraphs(provider, tools, BudgetManager(), lambda state: {}, models=MODELS,
                                persist=lambda state, ledger: saved.append(_serializable(state)))
        output = await engine.run_specialist(task())
        assert output["output"].stop_reason == "evidence_complete"
        feedback = json.loads(provider.requests[1].prompt).get("last_tool_error")
        assert feedback == {"tool": "parse_ast", "code": "recoverable_tool_error"}
        assert saved[-1]["last_tool_error"] == feedback
        assert "private token" not in json.dumps(saved)
        assert output["private_state"].tool_call_count == 1
    asyncio.run(scenario())


def test_invalid_tool_arguments_can_be_corrected_without_executing_them():
    async def scenario():
        tools, calls = PermissionedTools(), []
        async def read(arguments, work):
            calls.append(arguments)
            return ToolObservation(evidence_ref="source-1")
        tools.register("read_source", read)
        provider = ScriptedProvider([
            {"kind": "call_tool", "tool": "read_source", "arguments": {"unexpected": "private token"}},
            {"kind": "call_tool", "tool": "read_source", "arguments": {"file_path": "service.py"}},
            {"kind": "submit_candidates", "payload": result()},
        ])
        output = await AgentSubgraphs(provider, tools, BudgetManager(), lambda state: {}, models=MODELS).run_specialist(task())
        assert output["output"].stop_reason == "evidence_complete"
        assert calls == [{"file_path": "service.py"}]
        assert json.loads(provider.requests[1].prompt).get("last_tool_error") == {
            "tool": "read_source", "code": "recoverable_tool_error"}
        assert json.loads(provider.requests[2].prompt).get("last_tool_error") is None
        assert output["private_state"].tool_call_count == 1
    asyncio.run(scenario())


def test_context_action_timeout_drains_retrieval_and_stops_without_replay():
    async def scenario():
        drained = asyncio.Event()
        async def context(state):
            if state.get("action") is not None:
                try:
                    await asyncio.Event().wait()
                finally:
                    drained.set()
            return {}
        budget = BudgetManager()
        # Accelerate the real timeout boundary without altering product limits.
        budget.timeout_for = lambda operation: .02
        provider = ScriptedProvider([{"kind": "request_context", "arguments": {"file_path": "service.py"}}])
        engine = AgentSubgraphs(provider, PermissionedTools(), budget, context, models=MODELS)
        output = await asyncio.wait_for(engine.run_specialist(task()), .5)
        assert output["output"].stop_reason == "tool_timeout"
        assert drained.is_set()
        assert len(provider.requests) == 1
        assert budget.ledger.task_tools == {"t1": 1}
        assert not budget.ledger.inflight
    asyncio.run(scenario())


@pytest.mark.parametrize("role", ["specialist", "planner"])
def test_successful_resume_removes_only_the_resolved_cancellation_marker(role):
    async def scenario():
        entered, saved = asyncio.Event(), []
        class PausedProvider:
            async def generate_completion(self, request):
                entered.set()
                await asyncio.Event().wait()
        async def context(state):
            if role == "planner":
                # Cancel before dispatch: an unknown planner completion can use
                # most of its token ceiling and correctly prevent another call.
                entered.set()
                await asyncio.Event().wait()
            return {}
        budget = BudgetManager()
        engine = AgentSubgraphs(PausedProvider(), PermissionedTools(), budget, context, models=MODELS,
                                persist=lambda state, ledger: saved.append(_serializable(state)))
        async def run(runtime, **kwargs):
            if role == "specialist":
                return await runtime.run_specialist(task(), **kwargs)
            return await runtime.run_planner(snapshot_id="snapshot", files=["service.py"], **kwargs)
        operation = asyncio.create_task(run(engine))
        await asyncio.wait_for(entered.wait(), 1)
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation
        checkpoint = saved[-1]
        private = AgentPrivateState.model_validate(checkpoint["private_state"])
        identity = "t1" if role == "specialist" else "__planner"
        assert private.coverage.failed[identity] == "cancelled"
        private.coverage.failed["other-task"] = "invalid_evidence"
        action = {"kind": "submit_candidates", "payload": result()} if role == "specialist" else {
            "kind": "submit_plan", "payload": plan_payload()}
        resumed = AgentSubgraphs(ScriptedProvider([action]), PermissionedTools(), budget, lambda state: {}, models=MODELS)
        output = await run(resumed, private_state=private, restored_state=checkpoint)
        assert output["private_state"].stop_reason == "evidence_complete"
        assert output["private_state"].coverage.failed == {"other-task": "invalid_evidence"}
        assert budget.ledger.task_iterations[identity] == 2
        assert not budget.ledger.inflight
    asyncio.run(scenario())


@pytest.mark.parametrize("saved_candidate", [False, True])
def test_one_specialist_crash_keeps_sibling_candidate_and_persisted_progress(tmp_path, monkeypatch, saved_candidate):
    original = _ReviewSession.run_task
    async def crash_one(self, work, **kwargs):
        if work.task_id == "bug-1":
            if saved_candidate:
                source = self.repository._read_source({"file_path": "service.py"}, work)
                candidate = FindingCandidate(category="reliability", title="Persisted candidate before crash",
                    description="First item indexing raises on empty input", impact="Request failure", confidence=.7,
                    evidence_refs=[source.evidence_ref], location={"snapshot_id": self.repository.snapshot_id,
                        "file_path": "service.py", "start_line": 2, "end_line": 2})
                private = AgentPrivateState(current_task=work.task_id, local_findings=[candidate])
                await self.persist_agent({"task": work, "private_state": private, "output": None}, {})
            # Represent an unexpected task-local failure outside provider handling.
            await asyncio.sleep(.02)
            raise RuntimeError("private failure details")
        return await original(self, work, **kwargs)
    monkeypatch.setattr(_ReviewSession, "run_task", crash_one)
    class TwoSpecialists(ReviewProvider):
        async def generate_completion(self, request):
            data = json.loads(request.prompt)
            if data["task"]["agent_id"] != "planner":
                return await super().generate_completion(request)
            self.requests.append(request)
            plan = plan_payload()
            plan["selected_agents"].append("bug_reliability")
            plan["review_tasks"].append({"task_id": "bug-1", "agent_id": "bug_reliability",
                "files": ["service.py"], "focus": "Inspect failure handling"})
            return LLMResponse(finish_reason="stop", content=json.dumps({"kind": "submit_plan", "payload": plan}),
                provider="scripted", model=request.model, latency_ms=0,
                usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15))
    async def scenario():
        layout, artifacts, snapshot, jobs, events = stores(tmp_path)
        provider = TwoSpecialists()
        executor = CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events, provider, models=MODELS)
        manager = DurableJobManager(jobs, events, executor)
        try:
            job = await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="m7-partial")
            completed = await manager.wait(job.job_id, owner="alice")
            assert completed.status == "completed"
            report = json.loads(completed.result["json"])
            assert len(report["uncertain_high_impact_candidates"]) == (2 if saved_candidate else 1)
            assert report["coverage"]["failed"]["bug-1"] == "specialist_failed"
            assert "logic-1" not in report["coverage"]["failed"]
            assert "private failure" not in json.dumps(completed.result)
            from hashlib import sha256
            thread = sha256(("alice\0" + job.job_id).encode()).hexdigest()
            assert executor.checkpoints.load(thread, "bug-1")["state"]["output"]["stop_reason"] == "specialist_failed"
        finally:
            await manager.close()
    asyncio.run(scenario())


def test_followup_specialist_crash_preserves_initial_findings(tmp_path, monkeypatch):
    original = _ReviewSession.run_task
    async def crash_followup(self, work, **kwargs):
        if kwargs.get("followup") is not None:
            raise RuntimeError("private followup details")
        return await original(self, work, **kwargs)
    monkeypatch.setattr(_ReviewSession, "run_task", crash_followup)
    async def scenario():
        layout, artifacts, snapshot, jobs, events = stores(tmp_path)
        executor = CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events,
                                          ReviewProvider(followup=True), models=MODELS)
        manager = DurableJobManager(jobs, events, executor)
        try:
            job = await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="m7-followup")
            completed = await manager.wait(job.job_id, owner="alice")
            assert completed.status == "completed"
            report = json.loads(completed.result["json"])
            assert len(report["uncertain_high_impact_candidates"]) == 1
            assert report["coverage"]["failed"]["logic-1"] == "specialist_failed"
            assert completed.followup_completed
            assert completed.ledger.review_round == 2
            assert "private followup" not in json.dumps(completed.result)
        finally:
            await manager.close()
    asyncio.run(scenario())


def test_prompt_context_timeout_stops_before_model_dispatch():
    async def scenario():
        drained = asyncio.Event()
        async def context(state):
            try:
                await asyncio.Event().wait()
            finally:
                drained.set()
        budget = BudgetManager()
        budget.timeout_for = lambda operation: .02
        provider = ScriptedProvider([])
        engine = AgentSubgraphs(provider, PermissionedTools(), budget, context, models=MODELS)
        output = await asyncio.wait_for(engine.run_specialist(task()), .5)
        assert output["output"].stop_reason == "context_timeout"
        assert drained.is_set()
        assert provider.requests == []
        assert budget.ledger.total_tokens == 0
        assert not budget.ledger.inflight
    asyncio.run(scenario())


@pytest.mark.parametrize("limit", ["iterations", "tokens", "tools"])
def test_exhausted_budget_retains_saved_findings_and_cumulative_usage(limit):
    async def scenario():
        candidate = FindingCandidate(category="reliability", title="Saved finding", description="Empty input raises",
            impact="Request failure", confidence=.7, evidence_refs=["source-1"],
            location={"snapshot_id": "snapshot", "file_path": "service.py", "start_line": 2, "end_line": 2})
        private = AgentPrivateState(current_task="t1", local_findings=[candidate])
        budget = BudgetManager()
        if limit == "iterations":
            budget.ledger.task_iterations["t1"] = 8
        elif limit == "tokens":
            budget.ledger.agent_usage[AgentId.BUG_RELIABILITY] = TokenUsage(prompt_tokens=50_000)
        else:
            budget.ledger.task_tools["t1"] = 12
        provider = ScriptedProvider([{"kind": "call_tool", "tool": "parse_ast", "arguments": {"file_path": "service.py"}}])
        tools = PermissionedTools()
        async def forbidden(*args):
            pytest.fail("Exhausted budget admitted tool execution")
        tools.register("parse_ast", forbidden)
        output = await AgentSubgraphs(provider, tools, budget, lambda state: {}, models=MODELS).run_specialist(task(), private_state=private)
        assert output["output"].stop_reason == "budget_exhausted"
        assert output["output"].candidates == [candidate]
        assert output["output"].coverage.failed["t1"] == "budget_exhausted"
        assert len(provider.requests) == (1 if limit == "tools" else 0)
        assert budget.ledger.total_tokens == (50_000 if limit == "tokens" else 15 if limit == "tools" else 0)
        assert not budget.ledger.inflight
        if limit == "tools":
            assert budget.ledger.task_tools == {"t1": 12}
        elif limit == "iterations":
            assert budget.ledger.task_iterations == {"t1": 8}
    asyncio.run(scenario())


def test_actual_provider_timeout_drains_and_conservatively_charges_unknown_usage():
    async def scenario():
        drained, calls = asyncio.Event(), []
        class HeldProvider:
            async def generate_completion(self, request):
                calls.append(request)
                try:
                    await asyncio.Event().wait()
                finally:
                    drained.set()
        budget = BudgetManager()
        budget.timeout_for = lambda operation: .02
        output = await AgentSubgraphs(HeldProvider(), PermissionedTools(), budget, lambda state: {}, models=MODELS).run_specialist(task())
        assert output["output"].stop_reason == "model_unavailable"
        assert drained.is_set()
        assert len(calls) == 1
        assert budget.ledger.total_tokens > 1000
        assert output["private_state"].usage.total_tokens == budget.ledger.total_tokens
        assert not budget.ledger.inflight
        assert not budget.ledger.operation_retries
    asyncio.run(scenario())


def test_recoverable_tool_feedback_survives_explicit_resume():
    async def scenario():
        tools, saved, entered = PermissionedTools(), [], asyncio.Event()
        async def unavailable(*args):
            raise LookupError("private details")
        tools.register("parse_ast", unavailable)
        async def context(state):
            if state.get("last_tool_error"):
                entered.set()
                await asyncio.Event().wait()
            return {}
        budget = BudgetManager()
        first = ScriptedProvider([{"kind": "call_tool", "tool": "parse_ast", "arguments": {"file_path": "service.py"}}])
        engine = AgentSubgraphs(first, tools, budget, context, models=MODELS,
            persist=lambda state, ledger: saved.append(_serializable(state)))
        operation = asyncio.create_task(engine.run_specialist(task()))
        await asyncio.wait_for(entered.wait(), 1)
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation
        second = ScriptedProvider([{"kind": "submit_candidates", "payload": result()}])
        resumed = AgentSubgraphs(second, tools, budget, lambda state: {}, models=MODELS)
        output = await resumed.run_specialist(task(), private_state=AgentPrivateState.model_validate(saved[-1]["private_state"]),
                                              restored_state=saved[-1])
        assert output["output"].stop_reason == "evidence_complete"
        assert json.loads(second.requests[0].prompt)["last_tool_error"] == {"tool": "parse_ast", "code": "recoverable_tool_error"}
        assert budget.ledger.task_tools == {"t1": 1}
        assert budget.ledger.task_iterations == {"t1": 3}
    asyncio.run(scenario())


@pytest.mark.parametrize("error", [OSError, sqlite3.OperationalError, JobConflict])
def test_storage_and_ownership_failures_are_not_specialist_partial_success(tmp_path, monkeypatch, error):
    async def scenario():
        layout, artifacts, snapshot, jobs, events = stores(tmp_path)
        executor = CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events,
                                          ReviewProvider(), models=MODELS)
        from devwatch.review.repository import RepositoryContext
        job = jobs.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="storage")
        repository = RepositoryContext(artifacts, RepoCache(layout.repo_cache), snapshot.snapshot_id, owner="alice")
        session = _ReviewSession(executor, job, repository, BudgetManager(), ["service.py"])
        async def fail(*args, **kwargs):
            raise error("storage or ownership unavailable")
        monkeypatch.setattr(session, "run_task", fail)
        with pytest.raises(error):
            await session.run_task_safely(task())
        assert executor.checkpoints.load(session.thread_id, "t1") is None
        assert not session.board.results
    asyncio.run(scenario())
