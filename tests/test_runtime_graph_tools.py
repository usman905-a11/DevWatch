"""Canonical graph executes approved tools and grants measurement writes per task."""
import asyncio
import json
import sys

from devwatch.providers.base import LLMResponse, LLMUsage
from devwatch.review.contracts import AgentAction, AgentId, ReviewTask
from devwatch.review.jobs import DurableJobManager
from devwatch.review.repository import RepositoryContext
from devwatch.review.stores import RepoCache
from devwatch.review.tool_runtime import TrustedCommand, TrustedToolRuntime
from devwatch.review.workflow import CanonicalReviewExecutor
from tests.test_canonical_workflow import ReviewProvider, stores
from tests.test_control_agents import MODELS, plan_payload
import pytest


def test_approved_command_is_available_inside_iterative_graph_and_accounted(tmp_path):
    class CommandsProvider(ReviewProvider):
        async def generate_completion(self, request):
            data = json.loads(request.prompt)
            role = data["task"]["agent_id"]
            if role == "planner":
                plan = plan_payload()
                plan["selected_agents"] = ["bug_reliability"]
                plan["review_tasks"][0].update(task_id="bug-1", agent_id="bug_reliability")
                action = {"kind": "submit_plan", "payload": plan}
            elif role == "bug_reliability":
                assert data["selected_context"]["approved_commands"][0]["command_id"] == "compile"
                assert "argv" not in data["selected_context"]["approved_commands"][0]
                action = ({"kind": "call_tool", "tool": "run_tests", "arguments": {"command_id": "compile"}}
                    if not data["private_state"]["evidence_refs"] else {"kind": "submit_candidates", "payload": {
                        "task_id": "bug-1", "agent_id": role, "candidates": [], "coverage": {}, "stop_reason": "evidence_complete"}})
            else:
                return await super().generate_completion(request)
            action["inspected_evidence"] = [page["evidence_ref"] for page in data["selected_context"].get("evidence", [])]
            self.requests.append(request)
            return LLMResponse(finish_reason="stop", content=json.dumps(action), provider="scripted", model=request.model,
                latency_ms=0, usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15))
    async def scenario():
        layout, artifacts, snapshot, jobs, events = stores(tmp_path)
        command = TrustedCommand(command_id="compile", tool="run_tests",
            argv=(sys.executable, "-m", "compileall", "-q", "service.py"), files=("service.py",))
        executor = CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events,
            CommandsProvider(), models=MODELS, trusted_commands=(command,))
        manager = DurableJobManager(jobs, events, executor)
        try:
            job = await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="command-graph")
            saved = await manager.wait(job.job_id, owner="alice")
            assert saved.status == "completed"
            assert saved.ledger.task_tools["bug-1"] == 1
            assert saved.ledger.task_iterations["bug-1"] == 2
            report = json.loads(saved.result["json"])
            assert report["coverage"]["inspected_files"] == ["service.py"]
            assert not report["coverage"]["failed"]
            assert not list(artifacts.source_root(snapshot.snapshot_id, owner="alice").glob("**/*.pyc"))
            assert list(artifacts.root.glob("scratch/*/__pycache__/*.pyc"))
        finally:
            await manager.close()
    asyncio.run(scenario())


def test_only_granted_performance_task_can_write_runtime_measurement_artifact(tmp_path):
    async def scenario():
        layout, artifacts, snapshot, jobs, events = stores(tmp_path)
        job = jobs.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="measurement")
        job = jobs.transition(job.job_id, owner="alice", expected_status="queued", status="running")
        repo = RepositoryContext(artifacts, RepoCache(layout.repo_cache), snapshot.snapshot_id, owner="alice")
        command = TrustedCommand(command_id="timing", tool="benchmark", argv=(sys.executable, "-m", "compileall", "-q", "service.py"),
            files=("service.py",), produces_measurement_artifact=True)
        runtime = TrustedToolRuntime(repo, jobs, job, commands=(command,))
        tools = repo.tools(runtime)
        task = ReviewTask(task_id="performance-1", agent_id=AgentId.PERFORMANCE_SCALABILITY, files=["service.py"], focus="Measure compile")
        measured = await tools.execute(task, AgentAction(kind="call_tool", tool="benchmark", arguments={"command_id": "timing"}))
        action = AgentAction(kind="call_tool", tool="write_artifact", arguments={"evidence_ref": measured.evidence_ref})
        with pytest.raises(PermissionError):
            await tools.execute(task, action)
        tools.grant_measurement_artifact(task)
        saved = await tools.execute(task, action)
        assert repo.evidence(saved.evidence_ref)["data"]["artifact_ref"].startswith("measurement-")
        assert len(list(artifacts.root.glob("measurements/**/*.json"))) == 1
        artifact = next(artifacts.root.glob("measurements/**/*.json"))
        original = artifact.read_bytes()
        await tools.execute(task, action)
        assert artifact.read_bytes() == original
        artifact.write_bytes(b"interrupted or altered artifact")
        with pytest.raises(ValueError, match="integrity"):
            await tools.execute(task, action)
        bug = task.model_copy(update={"agent_id": AgentId.BUG_RELIABILITY})
        with pytest.raises(PermissionError):
            await tools.execute(bug, action)
    asyncio.run(scenario())
