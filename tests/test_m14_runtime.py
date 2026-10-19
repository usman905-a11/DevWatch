"""Real graph/checkpoint recovery and concurrent worker-state isolation."""

import asyncio
from collections import Counter
import json

import pytest

from devwatch.review.contracts import BalancedLimits, ModelTier
from devwatch.review.jobs import DurableJobManager
from devwatch.review.stores import RepoCache
from devwatch.review.workflow import CanonicalReviewExecutor, _ReviewSession
from tests.test_canonical_workflow import ReviewProvider, stores


class MultipleTasksProvider(ReviewProvider):
    def __init__(self, identities):
        super().__init__()
        self.identities = identities
        self.private_tasks = []

    async def generate_completion(self, request):
        body = json.loads(request.prompt)
        response = await super().generate_completion(request)
        action = json.loads(response.content)
        if body["task"]["agent_id"] == "planner":
            template = action["payload"]["review_tasks"][0]
            action["payload"]["review_tasks"] = [
                {**template, "task_id": identity, "focus": "Boundary " + identity}
                for identity in self.identities]
        elif body["task"]["agent_id"] == "logic_correctness":
            self.private_tasks.append((body["task"]["task_id"], body["private_state"]["current_task"]))
            if action["kind"] == "submit_candidates":
                action["payload"]["task_id"] = body["task"]["task_id"]
        return response.model_copy(update={"content": json.dumps(action)})


def executor_for(layout, artifacts, jobs, events, provider):
    return CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events,
                                   provider, models={tier: tier.value for tier in ModelTier})


@pytest.mark.asyncio
async def test_interruption_reuses_finished_worker_while_resuming_its_unfinished_sibling(tmp_path, monkeypatch):
    layout, artifacts, snapshot, jobs, events = stores(tmp_path)
    slow_entered, fast_saved = asyncio.Event(), asyncio.Event()
    loop = asyncio.get_running_loop()

    class PausedProvider(MultipleTasksProvider):
        async def generate_completion(self, request):
            body = json.loads(request.prompt)
            if body["task"]["task_id"] == "logic-slow":
                slow_entered.set()
                await asyncio.Event().wait()
            return await super().generate_completion(request)

    first = executor_for(layout, artifacts, jobs, events, PausedProvider(["logic-fast", "logic-slow"]))
    save = first.checkpoints.save
    def observed_save(thread_id, state, generation):
        save(thread_id, state, generation)
        if state["task"].task_id == "logic-fast" and state.get("output"):
            loop.call_soon_threadsafe(fast_saved.set)
    monkeypatch.setattr(first.checkpoints, "save", observed_save)
    manager = DurableJobManager(jobs, events, first)
    try:
        job = await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="workers")
        await asyncio.wait_for(asyncio.gather(slow_entered.wait(), fast_saved.wait()), timeout=20)
    finally:
        await manager.close()
    interrupted = jobs.get(job.job_id, owner="alice")
    assert interrupted.status == "interrupted" and not interrupted.ledger.inflight

    provider = MultipleTasksProvider(["logic-fast", "logic-slow"])
    resumed = DurableJobManager(jobs, events, executor_for(layout, artifacts, jobs, events, provider))
    try:
        await resumed.resume(job.job_id, owner="alice")
        done = await resumed.wait(job.job_id, owner="alice")
    finally:
        await resumed.close()
    assert done.status == "completed" and not done.ledger.inflight
    requested = [json.loads(request.prompt)["task"]["task_id"] for request in provider.requests]
    assert Counter(requested) == {"logic-slow": 2, "__final": 2}
    report = json.loads(done.result["json"])
    assert len(report["uncertain_high_impact_candidates"]) == 2
    assert not report["coverage"]["failed"]
    timeline = events.replay(job.job_id, limit=1000)
    assert sum(e.kind == "agent_reused" and e.payload.task_id == "logic-fast" for e in timeline) == 1


@pytest.mark.asyncio
async def test_two_jobs_share_three_model_slots_and_keep_five_same_role_workers_isolated(tmp_path):
    layout, artifacts, snapshot, jobs, events = stores(tmp_path)
    ready, release = asyncio.Event(), asyncio.Event()

    class BarrierProvider(MultipleTasksProvider):
        active = 0
        peak = 0
        async def generate_completion(self, request):
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                if json.loads(request.prompt)["task"]["agent_id"] == "logic_correctness":
                    if self.active == 3:
                        ready.set()
                    await release.wait()
                return await super().generate_completion(request)
            finally:
                self.active -= 1

    provider = BarrierProvider(["logic-e", "logic-d", "logic-c", "logic-b", "logic-a"])
    manager = DurableJobManager(jobs, events, executor_for(layout, artifacts, jobs, events, provider),
                                concurrent_jobs=2)
    try:
        submitted = [await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id},
                                         idempotency_key=key, limits=BalancedLimits(concurrent_model_calls=2))
                     for key in ["first", "second"]]
        await asyncio.wait_for(ready.wait(), timeout=20)
        assert provider.active == 3
        release.set()
        completed = await asyncio.gather(*(manager.wait(job.job_id, owner="alice") for job in submitted))
    finally:
        release.set()
        await manager.close()
    assert provider.peak == 3 and provider.active == 0
    assert all(assigned == private for assigned, private in provider.private_tasks)
    for job in completed:
        assert job.status == "completed" and not job.ledger.inflight
        report = json.loads(job.result["json"])
        assert len(report["uncertain_high_impact_candidates"]) == 5 and not report["coverage"]["failed"]
        timeline = events.replay(job.job_id, limit=1000)
        starts = [e.payload.task_id for e in timeline if e.kind == "agent_started" and e.payload.phase == "investigation"]
        assert starts == ["logic-a", "logic-b", "logic-c", "logic-d", "logic-e"]


@pytest.mark.asyncio
async def test_invalid_worker_result_preserves_sibling_finding_through_finalization(tmp_path, monkeypatch):
    layout, artifacts, snapshot, jobs, events = stores(tmp_path)
    original = _ReviewSession.run_task
    async def missing_one(self, task, **kwargs):
        return None if task.task_id == "logic-bad" else await original(self, task, **kwargs)
    monkeypatch.setattr(_ReviewSession, "run_task", missing_one)
    provider = MultipleTasksProvider(["logic-good", "logic-bad"])
    manager = DurableJobManager(jobs, events, executor_for(layout, artifacts, jobs, events, provider))
    try:
        job = await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id},
                                   idempotency_key="partial")
        done = await manager.wait(job.job_id, owner="alice")
    finally:
        await manager.close()
    assert done.status == "completed" and not done.ledger.inflight
    report = json.loads(done.result["json"])
    assert len(report["uncertain_high_impact_candidates"]) == 1
    assert report["coverage"]["failed"] == {"logic-bad": "specialist_failed"}
    assert provider.phase_counts["synthesizer_verifier:verification"] == 1
    assert provider.phase_counts["synthesizer_verifier:synthesis"] == 1
