"""Cumulative execution across interruption, including an admitted follow-up."""

import asyncio
import json

from devwatch.review.contracts import ModelTier
from devwatch.review.jobs import DurableJobManager
from devwatch.review.stores import RepoCache
from devwatch.review.workflow import CanonicalReviewExecutor
from tests.test_canonical_workflow import ReviewProvider, stores
from tests.assembly_fixtures import held_assembly


def test_resume_after_verification_continues_synthesis_without_reverifying(tmp_path):
    async def scenario():
        layout, artifacts, snapshot, jobs, events = stores(tmp_path)
        synthesis_entered = asyncio.Event()
        class PausedProvider(ReviewProvider):
            async def generate_completion(self, request):
                if json.loads(request.prompt)["phase"] == "synthesis":
                    synthesis_entered.set()
                    await asyncio.Event().wait()
                return await super().generate_completion(request)
        first = PausedProvider()
        executor = CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events,
                                          first, models={tier: tier.value for tier in ModelTier})
        manager = DurableJobManager(jobs, events, executor)
        with held_assembly(first, synthesis_entered):
            job = await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="resume")
            await asyncio.wait_for(synthesis_entered.wait(), timeout=10)
            await manager.close()
        interrupted = jobs.get(job.job_id, owner="alice")
        assert interrupted.status == "interrupted"
        tokens_before = interrupted.ledger.total_tokens
        second = ReviewProvider()
        resumed_executor = CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events,
                                                  second, models={tier: tier.value for tier in ModelTier})
        resumed = DurableJobManager(jobs, events, resumed_executor)
        await resumed.resume(job.job_id, owner="alice")
        completed = await resumed.wait(job.job_id, owner="alice")
        assert completed.status == "completed"
        assert second.requests == []
        assert completed.ledger.total_tokens == tokens_before
        assert completed.ledger.task_iterations["__final"] == 1
        await resumed.close()
    asyncio.run(scenario())


def test_resume_preserves_an_admitted_followup_and_does_not_repeat_it(tmp_path):
    async def scenario():
        layout, artifacts, snapshot, jobs, events = stores(tmp_path)
        admitted = asyncio.Event()
        class PausedFollowupProvider(ReviewProvider):
            async def generate_completion(self, request):
                data = json.loads(request.prompt)
                if data["task"]["agent_id"] == "logic_correctness" and "Follow-up question" in data["task"]["focus"]:
                    admitted.set()
                    await asyncio.Event().wait()
                return await super().generate_completion(request)
        executor = CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events,
            PausedFollowupProvider(followup=True), models={tier: tier.value for tier in ModelTier})
        manager = DurableJobManager(jobs, events, executor)
        job = await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="followup")
        await asyncio.wait_for(admitted.wait(), timeout=10)
        await manager.close()
        assert jobs.get(job.job_id, owner="alice").ledger.review_round == 2
        second = ReviewProvider(followup=True)
        resumed_executor = CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events,
                                                  second, models={tier: tier.value for tier in ModelTier})
        resumed = DurableJobManager(jobs, events, resumed_executor)
        await resumed.resume(job.job_id, owner="alice")
        completed = await resumed.wait(job.job_id, owner="alice")
        assert completed.status == "completed"
        followup_calls = [request for request in second.requests if "Follow-up question" in json.loads(request.prompt)["task"]["focus"]]
        assert len(followup_calls) == 1
        assert completed.ledger.review_round == 2
        await resumed.close()
    asyncio.run(scenario())
