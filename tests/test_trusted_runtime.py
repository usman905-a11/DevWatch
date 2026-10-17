"""Real exact commands run only in disposable source copies and drain on cancel."""
import asyncio
import importlib
import sys

import pytest

from devwatch.review.contracts import AgentAction, AgentId, ReviewTask
from devwatch.review.jobs import EventStore, JobStore
from devwatch.review.repository import RepositoryContext
from devwatch.review.stores import ArtifactStore, RepoCache


def runtime_api():
    assert importlib.util.find_spec("devwatch.review.tool_runtime"), "Trusted tool runtime is missing"
    return importlib.import_module("devwatch.review.tool_runtime")


def setup(tmp_path, source):
    artifacts = ArtifactStore(tmp_path / "artifacts")
    manifest = artifacts.capture(owner="alice", files={"probe.py": source})
    repo = RepositoryContext(artifacts, RepoCache(tmp_path / "cache.sqlite"), manifest.snapshot_id, owner="alice")
    jobs = JobStore(tmp_path / "jobs.sqlite")
    job = jobs.submit(owner="alice", request={"snapshot_id": manifest.snapshot_id}, idempotency_key="trusted")
    job = jobs.transition(job.job_id, owner="alice", expected_status="queued", status="running")
    task = ReviewTask(task_id="bug-task", agent_id=AgentId.BUG_RELIABILITY, files=["probe.py"], focus="Run approved test")
    return artifacts, manifest, repo, jobs, job, task


def test_exact_approval_and_clean_environment_do_not_mutate_snapshot(tmp_path, monkeypatch):
    api = runtime_api()
    source = "import os\nfrom pathlib import Path\nprint(os.getenv('HOST_SECRET_SENTINEL', 'clean'))\nPath('probe.py').write_text('changed scratch')\nprint('executed')\n"
    artifacts, snapshot, repo, jobs, job, task = setup(tmp_path, source)
    monkeypatch.setenv("HOST_SECRET_SENTINEL", "SHOULD-NOT-REACH-CHILD")
    command = api.TrustedCommand(command_id="test-probe", tool="run_tests", argv=(sys.executable, "probe.py"), files=("probe.py",))
    runtime = api.TrustedToolRuntime(repo, jobs, job, commands=(command,))
    async def scenario():
        action = AgentAction(kind="call_tool", tool="run_tests", arguments={"command_id": "test-probe"})
        observation = await runtime.execute(task, action)
        record = repo.evidence(observation.evidence_ref)
        assert record["data"]["exit_code"] == 0
        assert "clean" in record["data"]["stdout"] and "executed" in record["data"]["stdout"]
        assert "SHOULD-NOT-REACH-CHILD" not in str(record)
        assert artifacts.read_source(snapshot.snapshot_id, "probe.py", owner="alice") == source
        assert record["source_scope"] == ["probe.py"]
        with pytest.raises(PermissionError):
            await runtime.execute(task, action.model_copy(update={"arguments": {"command_id": "not-approved"}}))
        with pytest.raises(ValueError):
            await runtime.execute(task, action.model_copy(update={"arguments": {"command_id": "test-probe", "argv": ["other"]}}))
        denied = task.model_copy(update={"agent_id": AgentId.ARCHITECTURE_SECURITY})
        with pytest.raises(PermissionError):
            await runtime.execute(denied, action)
    asyncio.run(scenario())


def test_cancellation_drains_process_and_unknown_operation_is_not_replayed(tmp_path):
    api = runtime_api()
    source = "import time\nfrom pathlib import Path\nPath('entered').write_text('ready')\nwhile True: time.sleep(.01)\n"
    artifacts, _, repo, jobs, job, task = setup(tmp_path, source)
    command = api.TrustedCommand(command_id="held-test", tool="run_tests", argv=(sys.executable, "probe.py"), files=("probe.py",))
    runtime = api.TrustedToolRuntime(repo, jobs, job, commands=(command,))
    async def scenario():
        action = AgentAction(kind="call_tool", tool="run_tests", arguments={"command_id": "held-test"})
        operation = asyncio.create_task(runtime.execute(task, action))
        async with asyncio.timeout(5):
            while not list(artifacts.root.glob("scratch/*/entered")):
                await asyncio.sleep(.01)
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert runtime.active_processes == 0
        with pytest.raises(PermissionError, match="unknown"):
            await api.TrustedToolRuntime(repo, jobs, job, commands=(command,)).execute(task, action)
        assert len(list(artifacts.root.glob("scratch/*/entered"))) == 1
    asyncio.run(scenario())


def test_output_and_deadline_bounds_are_recorded_honestly(tmp_path):
    api = runtime_api()
    artifacts, _, repo, jobs, job, task = setup(tmp_path, "import time\nprint('x'*100000, flush=True)\ntime.sleep(20)\n")
    command = api.TrustedCommand(command_id="bounded-test", tool="run_tests", argv=(sys.executable, "probe.py"), files=("probe.py",), timeout_seconds=.2)
    runtime = api.TrustedToolRuntime(repo, jobs, job, commands=(command,), output_bytes=1024)
    async def scenario():
        output = await runtime.execute(task, AgentAction(kind="call_tool", tool="run_tests", arguments={"command_id": "bounded-test"}))
        data = repo.evidence(output.evidence_ref)["data"]
        assert data["timed_out"] and data["truncated"]
        assert len(data["stdout"].encode()) <= 1024
        assert runtime.active_processes == 0
    asyncio.run(scenario())


def test_parent_exit_cannot_leave_an_inherited_output_child_running(tmp_path):
    api = runtime_api()
    source = ("import subprocess,sys,time\nfrom pathlib import Path\n"
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])\n"
        "Path('child.pid').write_text(str(child.pid))\ntime.sleep(.1)\n")
    artifacts, _, repo, jobs, job, task = setup(tmp_path, source)
    command = api.TrustedCommand(command_id="tree-test", tool="run_tests", argv=(sys.executable, "probe.py"), files=("probe.py",))
    runtime = api.TrustedToolRuntime(repo, jobs, job, commands=(command,))
    async def scenario():
        import psutil
        try:
            output = await asyncio.wait_for(runtime.execute(task,
                AgentAction(kind="call_tool", tool="run_tests", arguments={"command_id": "tree-test"})), 3)
            assert repo.evidence(output.evidence_ref)["data"]["exit_code"] == 0
            identity = int(next(artifacts.root.glob("scratch/*/child.pid")).read_text())
            assert not psutil.pid_exists(identity), "Approved parent exit left a descendant running"
        finally:
            # Reap only our recorded controlled fixture child if the adapter failed.
            for path in artifacts.root.glob("scratch/*/child.pid"):
                identity = int(path.read_text())
                if psutil.pid_exists(identity):
                    process = psutil.Process(identity)
                    process.kill()
                    await asyncio.to_thread(process.wait, timeout=3)
    asyncio.run(scenario())
