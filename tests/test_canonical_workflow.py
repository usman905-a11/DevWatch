"""Whole canonical graph against real stores, with only the provider scripted."""

import asyncio
import importlib
import json

import pytest

from devwatch.providers.base import LLMResponse, LLMUsage
from devwatch.review.contracts import AgentId, ModelTier
from devwatch.review.jobs import DurableJobManager, EventStore, JobStore
from devwatch.review.stores import ArtifactStore, RepoCache, StoreLayout
from tests.test_control_agents import plan_payload


def workflow_api():
    assert importlib.util.find_spec("devwatch.review.workflow"), "Canonical root graph is missing"
    return importlib.import_module("devwatch.review.workflow")


class ReviewProvider:
    def __init__(self, *, followup=False, invalid=False):
        self.requests = []
        self.followup, self.invalid = followup, invalid
        self.phase_counts = {}

    async def generate_completion(self, request):
        self.requests.append(request)
        data = json.loads(request.prompt)
        role = data["task"]["agent_id"]
        phase = data["phase"]
        key = role + ":" + phase
        self.phase_counts[key] = self.phase_counts.get(key, 0) + 1
        if role == "planner":
            action = dict(kind="submit_plan", payload=plan_payload())
        elif role == "logic_correctness":
            if not data["private_state"]["evidence_refs"]:
                action = dict(kind="call_tool", tool="read_source", arguments={"file_path": "service.py"})
            else:
                candidate = dict(category="logic", title="Empty input raises", description="The first item is indexed without an empty check",
                    impact="Request can fail", confidence=0.9, evidence_refs=data["private_state"]["evidence_refs"],
                    location=dict(snapshot_id=data["selected_context"]["snapshot_id"], file_path="service.py", start_line=2, end_line=2))
                if self.invalid:
                    candidate["evidence_refs"] = ["forged"]
                action = dict(kind="submit_candidates", payload=dict(task_id="logic-1", agent_id=role,
                    candidates=[candidate], coverage={}, stop_reason="evidence_complete"))
        elif phase == "verification":
            decisions = [dict(finding_id=identity, verdict="uncertain", confidence=0.7,
                              rationale="Boundary failure follows syntactically; caller contract is unknown", evidence_refs=candidate["evidence_refs"])
                         for identity, candidate in data["candidates"].items()]
            requests = [dict(task_id="logic-1", question="Is empty input allowed?", evidence_needed="caller contract")] if self.followup else []
            action = dict(kind="submit_verification", payload=dict(decisions=decisions, followup_requests=requests))
        else:
            verified = data["verified"]
            findings = [dict(**candidate, finding_id=identity, verification_rationale=verified["decisions"][0]["rationale"])
                        for identity, candidate in data["candidates"].items()]
            for finding in findings:
                finding["kind"], finding["confidence"] = "high_impact_candidate", 0.7
            action = dict(kind="submit_synthesis", payload=dict(**verified, report_draft=dict(
                snapshot_id=data["selected_context"]["snapshot_id"], summary="One uncertain candidate", coverage={},
                uncertain_high_impact_candidates=findings), coverage_summary={}))
        action['inspected_evidence'] = [page['evidence_ref'] for page in data['selected_context'].get('evidence', [])]
        return LLMResponse(finish_reason="stop", content=json.dumps(action), provider="scripted", model=request.model, latency_ms=0,
                           usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15))


def stores(tmp_path):
    layout = StoreLayout(tmp_path / "runtime")
    artifacts = ArtifactStore(layout.artifacts)
    snapshot = artifacts.capture(owner="alice", files={"service.py": "def first(items):\n    return items[0]\n", "skipped.ts": "export const x = 1;\n"})
    jobs, events = JobStore(layout.jobs), EventStore(layout.events)
    return layout, artifacts, snapshot, jobs, events


def test_full_graph_returns_an_accepted_report_and_persistent_agent_events(tmp_path):
    api = workflow_api()
    async def scenario():
        layout, artifacts, snapshot, jobs, events = stores(tmp_path)
        provider = ReviewProvider()
        executor = api.CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events,
                                              provider, models={tier: tier.value for tier in ModelTier})
        manager = DurableJobManager(jobs, events, executor)
        job = await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="intent-1")
        completed = await manager.wait(job.job_id, owner="alice")
        assert completed.status == "completed"
        report = json.loads(completed.result["json"])
        assert report["confirmed_defects"] == []
        assert len(report["uncertain_high_impact_candidates"]) == 1
        assert report["coverage"]["inspected_files"] == ["service.py"]
        assert report["coverage"]["skipped"]["skipped.ts"] == "not_inspected"
        assert completed.ledger.total_tokens == 75
        jobs.dispatch_events(events)
        stream = events.replay(job.job_id)
        identities = {event.payload.agent_id for event in stream if event.kind == "agent_started"}
        assert identities == {AgentId.PLANNER, AgentId.LOGIC_CORRECTNESS, AgentId.SYNTHESIZER_VERIFIER}
        assert any(event.kind == "tool_called" for event in stream)
        assert all("return items[0]" not in event.model_dump_json() for event in stream)
        await manager.close()
    asyncio.run(scenario())


def test_one_followup_reuses_cumulative_agent_budgets_and_never_renders_early(tmp_path):
    api = workflow_api()
    async def scenario():
        layout, artifacts, snapshot, jobs, events = stores(tmp_path)
        provider = ReviewProvider(followup=True)
        executor = api.CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events,
                                              provider, models={tier: tier.value for tier in ModelTier})
        manager = DurableJobManager(jobs, events, executor)
        job = await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="intent-2")
        completed = await manager.wait(job.job_id, owner="alice")
        assert completed.status == "completed"
        assert completed.ledger.review_round == 2
        assert provider.phase_counts["synthesizer_verifier:verification"] == 2
        assert provider.phase_counts["synthesizer_verifier:synthesis"] == 2
        assert completed.ledger.task_iterations["logic-1"] == 3
        assert completed.ledger.task_iterations["__final"] == 4
        assert json.loads(completed.result["json"])["limitations"]
        await manager.close()
    asyncio.run(scenario())


def test_forged_candidate_is_failed_coverage_instead_of_a_published_finding(tmp_path):
    api = workflow_api()
    async def scenario():
        layout, artifacts, snapshot, jobs, events = stores(tmp_path)
        executor = api.CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events,
            ReviewProvider(invalid=True), models={tier: tier.value for tier in ModelTier})
        manager = DurableJobManager(jobs, events, executor)
        job = await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="intent-3")
        completed = await manager.wait(job.job_id, owner="alice")
        assert completed.status == "completed"
        report = json.loads(completed.result["json"])
        assert report["uncertain_high_impact_candidates"] == []
        assert report["coverage"]["failed"]["logic-1"] == "invalid_evidence"
        await manager.close()
    asyncio.run(scenario())


def test_snapshot_ownership_is_checked_before_any_model_call(tmp_path):
    api = workflow_api()
    async def scenario():
        layout, artifacts, snapshot, jobs, events = stores(tmp_path)
        provider = ReviewProvider()
        executor = api.CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events,
                                              provider, models={tier: tier.value for tier in ModelTier})
        job = jobs.submit(owner="bob", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="intent-4")
        with pytest.raises(PermissionError):
            await executor(job)
        assert provider.requests == []
    asyncio.run(scenario())
