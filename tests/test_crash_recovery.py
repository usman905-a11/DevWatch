"""Actual process death and concurrent managers, using real local stores."""
import asyncio
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from devwatch.review.jobs import DurableJobManager, EventStore, JobConflict, JobStore


WORKER = r'''
import asyncio, json, sys
from pathlib import Path
from devwatch.review.jobs import DurableJobManager, EventStore, JobStore

root = Path(sys.argv[1])
async def main():
    store, events = JobStore(root / "jobs.sqlite"), EventStore(root / "events.sqlite")
    ready = asyncio.Event()
    async def execute(job):
        store.update_ledger(job.job_id, owner="alice", ledger={
            "elapsed_seconds": 5, "task_tools": {"t1": 4},
            "task_iterations": {"t1": 3}, "review_round": 2,
            "inflight": {"unknown-call": {"agent_id": "bug_reliability", "tokens": 700}}})
        ready.set()
        try:
            await asyncio.Event().wait()
        finally:
            (root / "drained").write_text("drained")
    manager = DurableJobManager(store, events, execute)
    active = await manager.submit(owner="alice", request={}, idempotency_key="active")
    await ready.wait()
    queued = await manager.submit(owner="alice", request={}, idempotency_key="queued")
    (root / "ready.json").write_text(json.dumps({"active": active.job_id, "queued": queued.job_id}))
    # A service lifespan has no polling client that would close this manager.
    await asyncio.Event().wait()
    await manager.close()
asyncio.run(main())
'''


@contextmanager
def worker(root, script=WORKER):
    env = dict(os.environ, LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false")
    with (root / "worker.log").open("w") as log:
        process = subprocess.Popen([sys.executable, "-u", "-c", script, str(root)],
            cwd=Path(__file__).resolve().parents[1], env=env, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            deadline = time.monotonic() + 15
            while not (root / "ready.json").exists():
                if process.poll() is not None or time.monotonic() >= deadline:
                    pytest.fail("Fixture worker did not start: " + (root / "worker.log").read_text())
                time.sleep(.02)
            yield process, json.loads((root / "ready.json").read_text())
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)


def manager(root, execute):
    return DurableJobManager(JobStore(root / "jobs.sqlite"), EventStore(root / "events.sqlite"), execute)


async def reaches(store, identity, wanted):
    async with asyncio.timeout(3):
        while store.get(identity, owner="alice").status != wanted:
            await asyncio.sleep(.02)
    return store.get(identity, owner="alice")


def test_killed_worker_is_interrupted_and_queued_work_restarts_without_implicit_resume(tmp_path):
    with worker(tmp_path) as (process, identities):
        process.kill()
        process.wait(timeout=5)
        assert not (tmp_path / "drained").exists(), "This must exercise abrupt death"
        async def scenario():
            calls = []
            async def execute(job):
                calls.append(job.job_id)
                return {"report_ref": "queued-report"}
            resumed = manager(tmp_path, execute)
            try:
                await resumed.start()
                saved = resumed.store.get(identities["active"], owner="alice")
                assert saved.status == "interrupted", "Dead running jobs must not remain stuck"
                assert saved.ledger.task_tools == {"t1": 4}
                assert saved.ledger.task_iterations == {"t1": 3}
                assert saved.ledger.review_round == 2
                assert saved.ledger.inflight["unknown-call"].tokens == 700
                assert saved.ledger.elapsed_seconds >= 5
                await reaches(resumed.store, identities["queued"], "completed")
                assert calls == [identities["queued"]]
                repeat = resumed.store.submit(owner="alice", request={}, idempotency_key="active")
                assert repeat.job_id == identities["active"]
                history = resumed.events.replay(saved.job_id)
                assert [event.kind for event in history] == ["job_queued", "job_running", "budget_updated", "job_interrupted"]
                assert history[2].payload.duration_seconds == 5
                assert resumed.store.dispatch_events(resumed.events) == 0
            finally:
                await resumed.close()
        asyncio.run(scenario())


def test_start_does_not_interrupt_a_live_worker_or_duplicate_its_execution(tmp_path):
    with worker(tmp_path) as (_, identities):
        async def scenario():
            calls = []
            async def execute(job):
                calls.append(job.job_id)
                return {}
            other = manager(tmp_path, execute)
            try:
                await other.start()
                await reaches(other.store, identities["queued"], "completed")
                assert other.store.get(identities["active"], owner="alice").status == "running"
                assert identities["active"] not in calls
                with pytest.raises(JobConflict):
                    await other.resume(identities["active"], owner="alice")
            finally:
                await other.close()
        asyncio.run(scenario())


def test_already_running_manager_detects_a_later_worker_death(tmp_path):
    with worker(tmp_path) as (process, identities):
        async def scenario():
            async def execute(job):
                return {}
            other = manager(tmp_path, execute)
            try:
                await other.start()
                assert other.store.get(identities["active"], owner="alice").status == "running"
                process.kill()
                process.wait(timeout=5)
                await reaches(other.store, identities["active"], "interrupted")
                assert sum(event.kind == "job_interrupted" for event in other.events.replay(identities["active"])) == 1
            finally:
                await other.close()
        asyncio.run(scenario())


def test_cancellation_from_another_manager_drains_the_worker(tmp_path):
    with worker(tmp_path) as (_, identities):
        async def scenario():
            async def execute(job):
                return {}
            other = manager(tmp_path, execute)
            try:
                cancelled = await other.cancel(identities["active"], owner="alice")
                assert cancelled.status == "cancelled"
                async with asyncio.timeout(3):
                    while not (tmp_path / "drained").exists():
                        await asyncio.sleep(.02)
                assert other.store.get(identities["active"], owner="alice").status == "cancelled"
            finally:
                await other.close()
        asyncio.run(scenario())


GRAPH_WORKER = r'''
import asyncio, json, sys, threading, time
from pathlib import Path
from fastapi.testclient import TestClient
from tests.test_canonical_workflow import ReviewProvider
from tests.test_review_service import app, submit
root, entered = Path(sys.argv[1]), threading.Event()
class HeldSynthesis(ReviewProvider):
    async def generate_completion(self, request):
        if json.loads(request.prompt)["phase"] == "synthesis":
            entered.set()
            await asyncio.Event().wait()
        return await super().generate_completion(request)
from tests.assembly_fixtures import held_assembly
provider = HeldSynthesis()
with held_assembly(provider, entered), TestClient(app(root, provider)) as client:
    identity, snapshot = submit(client, key="graph-crash")
    if not entered.wait(10):
        raise RuntimeError("Synthesis did not start")
    (root / "ready.json").write_text(json.dumps({"active": identity, "snapshot": snapshot}))
    while True:
        time.sleep(1)
'''


def test_killed_service_resumes_saved_verification_snapshot_usage_and_replay(tmp_path):
    from fastapi.testclient import TestClient
    from tests.test_canonical_workflow import ReviewProvider
    from tests.test_review_service import ALICE, BOB, app, completed

    with worker(tmp_path, GRAPH_WORKER) as (process, identities):
        process.kill()
        process.wait(timeout=5)
        provider = ReviewProvider()
        with TestClient(app(tmp_path, provider)) as client:
            prefix = f"/api/jobs/{identities['active']}"
            saved = client.get(prefix, headers=ALICE).json()
            assert saved["status"] == "interrupted"
            assert saved["snapshot_id"] == identities["snapshot"]
            assert provider.requests == [], "Crash recovery must not implicitly call a model"
            assert client.post(prefix + "/resume", headers=BOB).status_code == 404
            assert client.get(prefix + "/report", headers=ALICE).status_code == 409
            before = client.get(prefix + "/events", headers=ALICE).json()["events"]
            assert sum(event["kind"] == "job_interrupted" for event in before) == 1
            assert client.post(prefix + "/resume", headers=ALICE).status_code == 202
            result = completed(client, identities["active"])
            assert result["status"] == "completed"
            assert provider.requests == []
            assert result["ledger"]["task_iterations"]["__final"] == 1
            assert result["ledger"]["elapsed_seconds"] >= saved["ledger"]["elapsed_seconds"]
            assert result["ledger"]["inflight"] == {}
            unknown = sum(item["tokens"] for item in saved["ledger"]["inflight"].values())
            final_before = saved["ledger"]["agent_usage"]["synthesizer_verifier"]
            final_after = result["ledger"]["agent_usage"]["synthesizer_verifier"]
            assert final_after["prompt_tokens"] + final_after["completion_tokens"] == (
                final_before["prompt_tokens"] + final_before["completion_tokens"] + unknown)
            source = client.get(prefix + "/source?file_path=service.py", headers=ALICE).json()
            assert "return items[0]" in source["data"]
            report = client.get(prefix + "/report", headers=ALICE).json()
            assert report["snapshot_id"] == identities["snapshot"]
            assert any("crash" in item.lower() for item in report["coverage"]["limitations"])
            after = client.get(prefix + "/events", headers=ALICE, params={"after": before[-1]["sequence"]}).json()["events"]
            assert [item["kind"] for item in after].count("job_completed") == 1
            unknown_calls = [item for item in after if item["kind"] == "model_call_completed"
                             and item["payload"].get("outcome") == "unknown"]
            assert {item["payload"]["operation_id"] for item in unknown_calls} == set(saved["ledger"]["inflight"])
            assert sum(item["payload"]["total_tokens"] for item in unknown_calls) == unknown
