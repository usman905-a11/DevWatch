"""A hard job deadline drains execution and renders only deterministic partial data."""
import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from devwatch.review.jobs import DurableJobManager
from devwatch.review.stores import RepoCache
from devwatch.review.workflow import CanonicalReviewExecutor
from tests.test_canonical_workflow import ReviewProvider, stores
from tests.test_control_agents import MODELS


def test_canonical_timeout_recovery_preserves_inspection_without_new_model_calls(tmp_path):
    class PausedFinal(ReviewProvider):
        def __init__(self):
            super().__init__()
            self.entered, self.cancelled = asyncio.Event(), False
        async def generate_completion(self, request):
            if json.loads(request.prompt)["task"]["agent_id"] == "synthesizer_verifier":
                self.requests.append(request)
                self.entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    self.cancelled = True
            return await super().generate_completion(request)
    async def scenario():
        layout, artifacts, snapshot, jobs, events = stores(tmp_path)
        provider = PausedFinal()
        executor = CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events, provider, models=MODELS)
        job = jobs.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="deadline")
        jobs.transition(job.job_id, owner="alice", expected_status="queued", status="running")
        operation = asyncio.create_task(executor(jobs.get(job.job_id, owner="alice")))
        await asyncio.wait_for(provider.entered.wait(), 5)
        operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)
        assert provider.cancelled
        ledger = jobs.get(job.job_id, owner="alice").ledger
        ledger.elapsed_seconds = 600
        jobs.update_ledger(job.job_id, owner="alice", ledger=ledger)
        output = await executor.recover_timeout(jobs.get(job.job_id, owner="alice"))
        assert len(provider.requests) == 4
        report = json.loads(output["json"])
        assert report["confirmed_defects"] == []
        assert report["coverage"]["inspected_files"] == ["service.py"]
        assert report["coverage"]["failed"]["__job"] == "review_time_exhausted"
        assert "logic-1" not in report["coverage"]["failed"]
        assert len(report["uncertain_high_impact_candidates"]) == 1
        assert report["uncertain_high_impact_candidates"][0]["confidence"] <= .5
        assert jobs.get(job.job_id, owner="alice").ledger.elapsed_seconds >= 600
    asyncio.run(scenario())


@pytest.mark.parametrize("lagging_clock", [False, True])
def test_manager_deadline_calls_recovery_only_after_executor_is_drained(tmp_path, monkeypatch, lagging_clock):
    if lagging_clock:
        # Windows loop timers may expire slightly ahead of the accounting clock.
        monkeypatch.setattr("devwatch.review.jobs.time", SimpleNamespace(monotonic=lambda: 10., time=time.time))
    async def scenario():
        _, _, snapshot, jobs, events = stores(tmp_path)
        drained, recoveries = asyncio.Event(), []
        async def execute(job):
            try:
                await asyncio.Event().wait()
            finally:
                drained.set()
        async def recover(job):
            assert drained.is_set()
            assert job.ledger.elapsed_seconds >= job.limits.review_seconds
            recoveries.append(job.job_id)
            return {"json": "partial", "markdown": "partial"}
        job = jobs.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="timeout")
        ledger = job.ledger.model_copy(deep=True)
        ledger.elapsed_seconds = 599.95
        jobs.update_ledger(job.job_id, owner="alice", ledger=ledger)
        manager = DurableJobManager(jobs, events, execute, recover_timeout=recover)
        await manager.start()
        result = await manager.wait(job.job_id, owner="alice")
        await manager.close()
        assert result.status == "completed"
        assert recoveries == [job.job_id]
        assert any(event.payload.error_code == "review_time_exhausted" for event in events.replay(job.job_id))
    asyncio.run(scenario())


def test_executor_timeout_error_is_not_a_job_deadline(tmp_path):
    async def scenario():
        _, _, snapshot, jobs, events = stores(tmp_path)
        async def execute(job):
            raise TimeoutError("private tool timeout")
        async def recover(job):
            raise AssertionError("ordinary failure misclassified as job deadline")
        manager = DurableJobManager(jobs, events, execute, recover_timeout=recover)
        job = await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="inner-timeout")
        assert (await manager.wait(job.job_id, owner="alice")).status == "failed"
        assert any(event.payload.error_code == "execution_failed" for event in events.replay(job.job_id))
        await manager.close()
    asyncio.run(scenario())


def test_explicit_cancel_never_invokes_deadline_recovery(tmp_path):
    async def scenario():
        _, _, snapshot, jobs, events = stores(tmp_path)
        started = asyncio.Event()
        async def execute(job):
            started.set()
            await asyncio.Event().wait()
        async def recover(job):
            raise AssertionError("explicit cancellation published a report")
        manager = DurableJobManager(jobs, events, execute, recover_timeout=recover)
        job = await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="cancel")
        await started.wait()
        assert (await manager.cancel(job.job_id, owner="alice")).status == "cancelled"
        assert jobs.get(job.job_id, owner="alice").result is None
        await manager.close()
    asyncio.run(scenario())


def test_deadline_after_empty_followup_retains_initial_candidate_and_completed_coverage(tmp_path, monkeypatch):
    from devwatch.providers.base import LLMResponse, LLMUsage
    class PausedAfterFollowup(ReviewProvider):
        def __init__(self):
            super().__init__(followup=True)
            self.final_calls, self.entered = 0, asyncio.Event()
        async def generate_completion(self, request):
            context = json.loads(request.prompt)
            task = context["task"]
            if task["agent_id"] == "synthesizer_verifier":
                self.final_calls += 1
                if self.final_calls == 3:
                    self.requests.append(request)
                    self.entered.set()
                    await asyncio.Event().wait()
            if task["agent_id"] == "logic_correctness" and "Follow-up question:" in task["focus"]:
                self.requests.append(request)
                return LLMResponse(finish_reason="stop", content=json.dumps({"kind": "submit_candidates", "payload": {
                    "task_id": task["task_id"], "agent_id": task["agent_id"], "candidates": [],
                    "coverage": {}, "stop_reason": "evidence_complete"}}), provider="scripted", model=request.model,
                    latency_ms=1, usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15))
            return await super().generate_completion(request)
    async def scenario():
        layout, artifacts, snapshot, jobs, events = stores(tmp_path)
        provider = PausedAfterFollowup()
        from devwatch.review.subgraphs import AgentSubgraphs
        original = AgentSubgraphs._run_control
        async def after_completed_followup(runtime, agent, **kwargs):
            if agent.value == 'synthesizer_verifier' and runtime.budget.ledger.review_round == 2:
                provider.entered.set()
                await asyncio.Event().wait()
            return await original(runtime, agent, **kwargs)
        monkeypatch.setattr(AgentSubgraphs, '_run_control', after_completed_followup)
        executor = CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events, provider, models=MODELS)
        job = jobs.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="followup-deadline")
        jobs.transition(job.job_id, owner="alice", expected_status="queued", status="running")
        operation = asyncio.create_task(executor(jobs.get(job.job_id, owner="alice")))
        # Allow local checkpoint I/O before the simulated deadline below.
        await asyncio.wait_for(provider.entered.wait(), 30)
        operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)
        ledger = jobs.get(job.job_id, owner="alice").ledger
        ledger.elapsed_seconds = 600
        jobs.update_ledger(job.job_id, owner="alice", ledger=ledger)
        report = json.loads((await executor.recover_timeout(jobs.get(job.job_id, owner="alice")))["json"])
        assert len(report["uncertain_high_impact_candidates"]) == 1
        assert "logic-1" not in report["coverage"]["failed"]
        assert report["coverage"]["inspected_files"] == ["service.py"]
    asyncio.run(scenario())
