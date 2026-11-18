"""Orchestration boundaries use real stores, workers and graph execution."""

import json

import pytest

from backend.review.budgets import BudgetManager
from backend.review.contracts import AgentId, AgentPrivateState, ModelTier, ReviewTask, SpecialistResult
from backend.review.repository import RepositoryContext
from backend.review.workflow import CanonicalReviewExecutor, ReviewExecutionError, _ReviewSession
from tests.test_canonical_workflow import ReviewProvider, stores
from tests.test_control_agents import plan_payload


def session_for(tmp_path):
    layout, artifacts, snapshot, jobs = stores(tmp_path)
    provider = ReviewProvider()
    executor = CanonicalReviewExecutor(layout, artifacts, jobs,
        provider, models={tier: tier.value for tier in ModelTier})
    job = jobs.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="m14")
    job = jobs.claim(job.job_id, owner="alice", execution_id="m14-test")
    repository = RepositoryContext(artifacts, snapshot.snapshot_id, owner="alice")
    session = _ReviewSession(executor, job, repository, BudgetManager(job.limits), ["service.py"])
    return session, provider


def assigned_task():
    return ReviewTask.model_validate(plan_payload()["review_tasks"][0])


@pytest.mark.asyncio
async def test_duplicate_dispatch_is_rejected_before_any_model_call(tmp_path):
    session, provider = session_for(tmp_path)
    task = assigned_task().model_dump(mode="json")
    with pytest.raises(ReviewExecutionError, match="duplicate"):
        session._route_specialists({"tasks": [task, task]})
    assert provider.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["scope", "agent", "generation", "output_owner"])
async def test_cached_worker_output_must_match_assignment_and_initial_generation(tmp_path, mismatch):
    session, provider = session_for(tmp_path)
    task = assigned_task()
    saved_task, generation = task, 1
    result = SpecialistResult(task_id=task.task_id, agent_id=task.agent_id,
                              coverage={}, stop_reason="evidence_complete")
    if mismatch == "scope":
        saved_task = task.model_copy(update={"files": ["skipped.ts"]})
    elif mismatch == "agent":
        saved_task = task.model_copy(update={"agent_id": AgentId.BUG_RELIABILITY})
    elif mismatch == "generation":
        generation = 2
    else:
        result = result.model_copy(update={"task_id": "other-task"})
    session.executor.checkpoints.save(session.thread_id, {
        "task": saved_task, "private_state": AgentPrivateState(current_task=task.task_id,
            stop_reason="evidence_complete"), "output": result}, generation)
    with pytest.raises(ReviewExecutionError, match="checkpoint"):
        await session.run_task_safely(task)
    assert provider.requests == []
    assert not session.budget.ledger.inflight


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["missing", "wrong_owner", "wrong_role"])
async def test_invalid_worker_result_becomes_task_failure_instead_of_aborting_aggregation(tmp_path, monkeypatch, fault):
    session, _ = session_for(tmp_path)
    async def missing(task, *, followup=None):
        if fault == "missing":
            return None
        return SpecialistResult(task_id="other-task" if fault == "wrong_owner" else task.task_id,
            agent_id=AgentId.BUG_RELIABILITY if fault == "wrong_role" else task.agent_id,
            coverage={}, stop_reason="evidence_complete")
    # Inject an internal worker fault; result validation and durable failure are real.
    monkeypatch.setattr(session, "run_task", missing)
    task = assigned_task()
    output = await session.run_specialist_node({"task": task.model_dump(mode="json")})
    result = SpecialistResult.model_validate(output["results"][0])
    assert result.task_id == "logic-1" and result.stop_reason == "specialist_failed"
    assert result.coverage.failed == {"logic-1": "specialist_failed"}
    saved = session.executor.checkpoints.load(session.thread_id, "logic-1")
    assert saved["state"]["output"]["stop_reason"] == "specialist_failed"


@pytest.mark.parametrize("fault", ["missing", "duplicate", "unknown", "wrong_role", "duplicate_task"])
def test_aggregation_validates_complete_result_set_before_any_publication(tmp_path, fault):
    session, _ = session_for(tmp_path)
    task = assigned_task()
    other = task.model_copy(update={"task_id": "logic-2"})
    tasks = [task.model_dump(mode="json"), other.model_dump(mode="json")]
    result = SpecialistResult(task_id="logic-1", agent_id=task.agent_id,
                              coverage={}, stop_reason="evidence_complete").model_dump(mode="json")
    second = {**result, "task_id": "logic-2"}
    results = [result, second]
    if fault == "missing":
        results.pop()
    elif fault == "duplicate":
        results.append(result)
    elif fault == "unknown":
        results[1] = {**second, "task_id": "not-assigned"}
    elif fault == "wrong_role":
        results[1] = {**second, "agent_id": "bug_reliability"}
    else:
        tasks.append(tasks[0])
    with pytest.raises(ReviewExecutionError, match="aggregation"):
        session.join({"tasks": tasks, "results": results})
    assert session.board.results == {} and session.board.candidates == {}


@pytest.mark.asyncio
async def test_root_graph_removes_plumbing_nodes_and_runs_five_specialists_in_parallel_isolated(tmp_path, monkeypatch):
    import asyncio
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from backend.providers.base import LLMResponse, LLMUsage
    from backend.review.contracts import SPECIALISTS
    from backend.review.jobs import DurableJobManager
    from backend.review.workflow import _ReviewSession

    session, _ = session_for(tmp_path)
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "graph.sqlite")) as saver:
        compiled = session.compile(saver)
        graph_nodes = set(compiled.get_graph().nodes)
    expected_nodes = {"__start__", "__end__", "planner", "join", "synthesizer_verifier"} | {
        agent.value for agent in SPECIALISTS
    }
    assert graph_nodes == expected_nodes

    # Run all 5 specialists in parallel: 3 hit a shared asyncio.Barrier simultaneously,
    # while performance_scalability times out without aborting the other four.
    layout, artifacts, snapshot, jobs = stores(tmp_path / "parallel")
    barrier = asyncio.Barrier(3)
    seen_prompts: dict[str, str] = {}

    class FiveSpecialistProvider:
        async def generate_completion(self, request):
            data = json.loads(request.prompt)
            role = data["task"]["agent_id"]
            if role == "planner":
                roles = [agent.value for agent in SPECIALISTS]
                action = {
                    "kind": "submit_plan",
                    "payload": {
                        "selected_agents": roles,
                        "priority_files": ["service.py"],
                        "priority_symbols": [],
                        "risk_areas": ["indexing"],
                        "review_tasks": [
                            {"task_id": f"task-{r}", "agent_id": r, "files": ["service.py"], "focus": f"Check {r}"}
                            for r in roles
                        ],
                        "review_strategy": "Inspect in parallel",
                        "coverage_expectations": ["service.py"],
                    },
                }
            elif role in {agent.value for agent in SPECIALISTS}:
                seen_prompts[role] = request.prompt
                evidence = data["selected_context"]["evidence"]
                if not evidence:
                    if role in {"bug_reliability", "logic_correctness", "quality_testability"}:
                        await asyncio.wait_for(barrier.wait(), timeout=5)
                    action = {"kind": "call_tool", "tool": "read_file", "arguments": {"file_path": "service.py"}}
                else:
                    action = {
                        "kind": "submit_candidates",
                        "inspected_evidence": [p["evidence_ref"] for p in evidence],
                        "payload": {
                            "task_id": data["task"]["task_id"],
                            "agent_id": role,
                            "candidates": [
                                {
                                    "category": role,
                                    "title": f"Finding from {role}",
                                    "description": "Empty list indexes zero element",
                                    "impact": "Raises IndexError",
                                    "confidence": 0.9,
                                    "location": {
                                        "snapshot_id": snapshot.snapshot_id,
                                        "file_path": "service.py",
                                        "start_line": 2,
                                        "end_line": 2,
                                    },
                                    "evidence_refs": [evidence[0]["evidence_ref"]],
                                }
                            ],
                            "coverage": {},
                            "stop_reason": "evidence_complete",
                        },
                    }
            elif data["phase"] == "verification":
                candidates = data["candidates"]
                evidence = data["selected_context"]["evidence"]
                if not evidence:
                    action = {"kind": "call_tool", "tool": "read_file", "arguments": {"file_path": "service.py"}}
                else:
                    ref = evidence[0]["evidence_ref"]
                    action = {
                        "kind": "submit_verification",
                        "inspected_evidence": [ref],
                        "payload": {
                            "decisions": [
                                {
                                    "finding_id": fid,
                                    "verdict": "uncertain",
                                    "confidence": 0.5,
                                    "rationale": "Candidate remains unverified under independent check.",
                                    "evidence_refs": [ref],
                                }
                                for fid in candidates
                            ]
                        },
                    }
            else:
                action = {"kind": "submit_synthesis", "payload": {"summary": "Partial scan complete", "limitations": []}}
            return LLMResponse(
                finish_reason="stop",
                content=json.dumps(action),
                provider="scripted",
                model=request.model,
                latency_ms=0,
                usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )

    original_run_task = _ReviewSession.run_task

    async def timeout_performance(self, task, *, followup=None):
        if task.agent_id == AgentId.PERFORMANCE_SCALABILITY:
            raise TimeoutError("specialist timed out")
        return await original_run_task(self, task, followup=followup)

    monkeypatch.setattr(_ReviewSession, "run_task", timeout_performance)
    executor = CanonicalReviewExecutor(
        layout, artifacts, jobs, FiveSpecialistProvider(), models={tier: tier.value for tier in ModelTier}
    )
    manager = DurableJobManager(jobs, executor)
    try:
        job = await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="p4")
        completed = await manager.wait(job.job_id, owner="alice")
    finally:
        await manager.close()

    assert completed.status == "completed"
    report = json.loads(completed.result["json"])
    assert report["coverage"]["failed"]["task-performance_scalability"] == "specialist_failed"
    reported_categories = {item["category"] for item in report["uncertain_high_impact_candidates"]}
    assert reported_categories == {"bug_reliability", "logic_correctness", "quality_testability", "architecture_security"}
    for role, prompt_text in seen_prompts.items():
        for sibling in SPECIALISTS:
            if sibling.value != role:
                assert f"Finding from {sibling.value}" not in prompt_text
