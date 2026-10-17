"""Mandatory-agent failures produce honest, gated partial reports."""
import asyncio
import json

import pytest

from devwatch.providers.exceptions import ProviderAuthenticationError
from devwatch.review.jobs import DurableJobManager
from devwatch.review.stores import RepoCache
from devwatch.review.workflow import CanonicalReviewExecutor
from tests.test_canonical_workflow import ReviewProvider, stores
from tests.test_control_agents import MODELS


@pytest.mark.parametrize("role", ["planner", "synthesizer_verifier"])
def test_mandatory_agent_failure_preserves_coverage_and_unverified_candidates(tmp_path, role):
    class Provider(ReviewProvider):
        async def generate_completion(self, request):
            context = json.loads(request.prompt)
            if context["task"]["agent_id"] == role:
                self.requests.append(request)
                raise ProviderAuthenticationError("raw secret must not reach report")
            return await super().generate_completion(request)
    async def scenario():
        layout, artifacts, snapshot, jobs, events = stores(tmp_path)
        provider = Provider()
        executor = CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events,
                                          provider, models=MODELS)
        manager = DurableJobManager(jobs, events, executor)
        job = await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="partial")
        complete = await manager.wait(job.job_id, owner="alice")
        await manager.close()
        assert complete.status == "completed"
        report = json.loads(complete.result["json"])
        assert report["confirmed_defects"] == []
        identity = "__planner" if role == "planner" else "__final"
        assert report["coverage"]["failed"][identity] == "model_unavailable"
        assert "Partial" in report["summary"]
        assert "raw secret" not in json.dumps(complete.result)
        if role == "planner":
            assert len(provider.requests) == 1
            assert set(report["coverage"]["skipped"]) == set(snapshot.entries)
        else:
            assert len(report["uncertain_high_impact_candidates"]) == 1
            assert report["uncertain_high_impact_candidates"][0]["confidence"] <= .5
    asyncio.run(scenario())
