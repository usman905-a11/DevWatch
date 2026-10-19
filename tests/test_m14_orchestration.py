"""Orchestration boundaries use real stores, workers and graph execution."""

import json

import pytest

from devwatch.review.budgets import BudgetManager
from devwatch.review.contracts import AgentId, AgentPrivateState, ModelTier, ReviewTask, SpecialistResult
from devwatch.review.repository import RepositoryContext
from devwatch.review.stores import RepoCache
from devwatch.review.workflow import CanonicalReviewExecutor, ReviewExecutionError, _ReviewSession
from tests.test_canonical_workflow import ReviewProvider, stores
from tests.test_control_agents import plan_payload


def session_for(tmp_path):
    layout, artifacts, snapshot, jobs, events = stores(tmp_path)
    provider = ReviewProvider()
    executor = CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events,
        provider, models={tier: tier.value for tier in ModelTier})
    job = jobs.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="m14")
    job = jobs.claim(job.job_id, owner="alice", execution_id="m14-test")
    repository = RepositoryContext(artifacts, executor.cache, snapshot.snapshot_id, owner="alice")
    session = _ReviewSession(executor, job, repository, BudgetManager(job.limits), ["service.py"])
    return session, provider


def assigned_task():
    return ReviewTask.model_validate(plan_payload()["review_tasks"][0])


@pytest.mark.asyncio
async def test_duplicate_dispatch_is_rejected_before_any_model_call(tmp_path):
    session, provider = session_for(tmp_path)
    task = assigned_task().model_dump(mode="json")
    with pytest.raises(ReviewExecutionError, match="duplicate"):
        await session.specialists({"tasks": [task, task]})
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
    output = await session.specialists({"tasks": [task.model_dump(mode="json")]})
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
        session.blackboard({"tasks": tasks, "results": results})
    assert session.board.results == {} and session.board.candidates == {}
