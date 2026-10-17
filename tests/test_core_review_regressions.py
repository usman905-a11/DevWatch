"""Concrete failures identified by the independent canonical-core review."""

import asyncio
import json

import pytest

from devwatch.review.contracts import AgentAction, AgentId, AgentPrivateState, ModelTier, ReviewPlan
from devwatch.review.jobs import DurableJobManager
from devwatch.review.stores import RepoCache
from devwatch.review.workflow import CanonicalReviewExecutor
from tests.test_canonical_workflow import ReviewProvider, stores
from tests.test_control_agents import plan_payload
from tests.test_repository_context import setup_repository


def executor_for(layout, artifacts, jobs, events, provider):
    return CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events,
                                  provider, models={tier: tier.value for tier in ModelTier})


def test_initial_specialist_interruption_resumes_investigation(tmp_path):
    async def scenario():
        layout, artifacts, snapshot, jobs, events = stores(tmp_path)
        entered = asyncio.Event()
        class PausedSpecialist(ReviewProvider):
            async def generate_completion(self, request):
                if json.loads(request.prompt)["task"]["agent_id"] == "logic_correctness":
                    entered.set()
                    await asyncio.Event().wait()
                return await super().generate_completion(request)
        manager = DurableJobManager(jobs, events, executor_for(layout, artifacts, jobs, events, PausedSpecialist()))
        job = await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="initial-resume")
        await asyncio.wait_for(entered.wait(), 10)
        await manager.close()
        provider = ReviewProvider()
        resumed = DurableJobManager(jobs, events, executor_for(layout, artifacts, jobs, events, provider))
        await resumed.resume(job.job_id, owner="alice")
        completed = await resumed.wait(job.job_id, owner="alice")
        assert completed.status == "completed"
        assert any(json.loads(request.prompt)["task"]["agent_id"] == "logic_correctness" for request in provider.requests)
        assert len(json.loads(completed.result["json"])["uncertain_high_impact_candidates"]) == 1
        await resumed.close()
    asyncio.run(scenario())


def test_failed_dispatch_cancels_and_drains_other_specialists(tmp_path, monkeypatch):
    from devwatch.review.workflow import _ReviewSession
    async def scenario():
        layout, artifacts, snapshot, jobs, events = stores(tmp_path)
        entered, cancelled = asyncio.Event(), asyncio.Event()
        class PausedSibling(ReviewProvider):
            async def generate_completion(self, request):
                role = json.loads(request.prompt)["task"]["agent_id"]
                if role == "planner":
                    response = await super().generate_completion(request)
                    action = json.loads(response.content)
                    action["payload"]["selected_agents"].append("bug_reliability")
                    action["payload"]["review_tasks"].append(dict(task_id="bug-1", agent_id="bug_reliability", files=["service.py"], focus="failure"))
                    return response.model_copy(update={"content": json.dumps(action)})
                if role == "bug_reliability":
                    entered.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        cancelled.set()
                return await super().generate_completion(request)
        original = _ReviewSession.run_task
        async def fail_one(self, task, **kwargs):
            if task.agent_id == AgentId.LOGIC_CORRECTNESS:
                await entered.wait()
                raise OSError("event persistence unavailable")
            return await original(self, task, **kwargs)
        monkeypatch.setattr(_ReviewSession, "run_task", fail_one)
        manager = DurableJobManager(jobs, events, executor_for(layout, artifacts, jobs, events, PausedSibling()))
        job = await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="sibling")
        failed = await manager.wait(job.job_id, owner="alice")
        assert failed.status == "failed"
        assert cancelled.is_set(), "a sibling provider call survived job failure"
        assert not failed.ledger.inflight
        await manager.close()
    asyncio.run(scenario())


def test_planner_task_ids_must_be_safe_for_event_persistence():
    payload = plan_payload()
    payload["review_tasks"][0]["task_id"] = "logic/1"
    with pytest.raises(ValueError):
        ReviewPlan.model_validate(payload)


def test_aggregate_evidence_cannot_be_retrieved_or_attached_outside_task_scope(tmp_path):
    api, _, manifest, repo, task = setup_repository(tmp_path)
    async def scenario():
        broad = task.model_copy(update={"files": ["service.py", "other.py"]})
        observed = await repo.tools().execute(broad, AgentAction(kind="call_tool", tool="code_search", arguments={"query": "not-in-context"}))
        with pytest.raises(PermissionError):
            await repo.tools().execute(task, AgentAction(kind="call_tool", tool="read_evidence", arguments={"evidence_ref": observed.evidence_ref}))
        with pytest.raises(PermissionError):
            repo.context({"task": task, "private_state": AgentPrivateState(evidence_refs=[observed.evidence_ref]), "action": None})
        source = await repo.tools().execute(task, AgentAction(kind="call_tool", tool="read_source", arguments={"file_path": "service.py"}))
        from devwatch.review.contracts import FindingCandidate
        candidate = FindingCandidate(category="logic", title="Claim", description="Claim", impact="Failure", confidence=0.7,
            location=dict(snapshot_id=manifest.snapshot_id, file_path="service.py", start_line=2, end_line=2),
            evidence_refs=[source.evidence_ref, observed.evidence_ref])
        with pytest.raises(PermissionError):
            api.StructuralEvidenceGate(repo).validate(candidate, task)
    asyncio.run(scenario())


def test_large_python_ast_does_not_exhaust_planner_before_first_call(tmp_path):
    async def scenario():
        layout, artifacts, _, jobs, events = stores(tmp_path)
        source = "\n".join(f"def function_{index}(items):\n    return items[0]\n" for index in range(600))
        snapshot = artifacts.capture(owner="alice", files={"service.py": source})
        provider = ReviewProvider()
        manager = DurableJobManager(jobs, events, executor_for(layout, artifacts, jobs, events, provider))
        job = await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="large-ast")
        completed = await manager.wait(job.job_id, owner="alice")
        assert completed.status == "completed"
        assert provider.requests
        context = json.loads(provider.requests[0].prompt)["selected_context"]
        assert len(json.dumps(context).encode("utf-8")) <= 6000
        await manager.close()
    asyncio.run(scenario())


def test_final_agent_receives_task_ids_and_runtime_candidate_provenance(tmp_path):
    async def scenario():
        layout, artifacts, snapshot, jobs, events = stores(tmp_path)
        provider = ReviewProvider()
        manager = DurableJobManager(jobs, events, executor_for(layout, artifacts, jobs, events, provider))
        job = await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="provenance")
        assert (await manager.wait(job.job_id, owner="alice")).status == "completed"
        context = next(json.loads(request.prompt)["selected_context"] for request in provider.requests if json.loads(request.prompt)["phase"] == "verification")
        assert context["review_tasks"]["logic-1"]["files"] == ["service.py"]
        assert set(context["candidate_tasks"].values()) == {"logic-1"}
        await manager.close()
    asyncio.run(scenario())


def test_synthesis_cannot_claim_inspection_of_unopened_source(tmp_path):
    async def scenario():
        layout, artifacts, snapshot, jobs, events = stores(tmp_path)
        class InventedCoverage(ReviewProvider):
            async def generate_completion(self, request):
                response = await super().generate_completion(request)
                if json.loads(request.prompt)["phase"] == "synthesis":
                    action = json.loads(response.content)
                    action["payload"]["report_draft"]["coverage"] = dict(inspected_files=["service.py", "skipped.ts"], inspected_symbols=["invented"])
                    response = response.model_copy(update={"content": json.dumps(action)})
                return response
        manager = DurableJobManager(jobs, events, executor_for(layout, artifacts, jobs, events, InventedCoverage()))
        job = await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="coverage")
        completed = await manager.wait(job.job_id, owner="alice")
        assert completed.status == "completed"
        coverage = json.loads(completed.result["json"])["coverage"]
        assert coverage["inspected_files"] == ["service.py"]
        assert coverage["inspected_symbols"] == []
        assert coverage["skipped"]["skipped.ts"] == "not_inspected"
        await manager.close()
    asyncio.run(scenario())


def test_final_iteration_exhaustion_returns_a_partial_uncertain_report(tmp_path):
    async def scenario():
        layout, artifacts, snapshot, jobs, events = stores(tmp_path)
        from devwatch.review.budgets import BudgetLedger
        job = jobs.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="partial")
        jobs.update_ledger(job.job_id, owner="alice", ledger=BudgetLedger(task_iterations={"__final": 7}))
        provider = ReviewProvider()
        manager = DurableJobManager(jobs, events, executor_for(layout, artifacts, jobs, events, provider))
        await manager.start()
        completed = await manager.wait(job.job_id, owner="alice")
        assert completed.status == "completed"
        report = json.loads(completed.result["json"])
        assert report["confirmed_defects"] == []
        assert len(report["uncertain_high_impact_candidates"]) == 1
        assert report["coverage"]["failed"]["__final"] == "budget_exhausted"
        assert any("partial" in limitation.lower() for limitation in report["limitations"])
        assert completed.ledger.task_iterations["__final"] == 8
        assert not any(json.loads(request.prompt)["phase"] == "synthesis" for request in provider.requests)
        await manager.close()
    asyncio.run(scenario())
