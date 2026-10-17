"""Real subprocesses prove cancellation drains PDF work before publication."""
import asyncio
import json
import sys

import pytest

from devwatch.review.contracts import Coverage, ReportDraft
from devwatch.review.finalization import FinalAcceptanceGate
from devwatch.review.jobs import DurableJobManager
from devwatch.review.stores import RepoCache
from devwatch.review.workflow import CanonicalReviewExecutor
from tests.test_canonical_workflow import ReviewProvider, stores
from tests.test_control_agents import MODELS


def held_worker(tmp_path, monkeypatch):
    marker = tmp_path / "render-entered"
    script = tmp_path / "held_pdf_worker.py"
    script.write_text("import pathlib, sys, time\n"
        "sys.stdin.buffer.read()\n"
        f"pathlib.Path({str(marker)!r}).write_text('entered')\n"
        "while True: time.sleep(.01)\n", encoding="utf-8")
    original = asyncio.create_subprocess_exec
    children = []
    async def start(*arguments, **options):
        if not children:
            arguments = (sys.executable, str(script))
        process = await original(*arguments, **options)
        children.append(process)
        return process
    monkeypatch.setattr(asyncio, "create_subprocess_exec", start)
    return marker, children


def test_cancelled_pdf_is_reaped_and_cannot_write_artifact(tmp_path, monkeypatch):
    marker, children = held_worker(tmp_path, monkeypatch)
    async def scenario():
        layout, artifacts, snapshot, jobs, events = stores(tmp_path)
        executor = CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events, ReviewProvider(), models=MODELS)
        job = jobs.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="pdf-cancel")
        accepted = FinalAcceptanceGate({}).accept(ReportDraft(snapshot_id=snapshot.snapshot_id,
            summary="Accepted review", coverage=Coverage()), [])
        operation = asyncio.create_task(executor.render_report(job, accepted))
        try:
            async with asyncio.timeout(5):
                while not marker.exists() and not operation.done():
                    await asyncio.sleep(.01)
            assert not operation.done(), "PDF work did not remain attached to its cancellable worker"
        finally:
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
            drained = bool(children) and all(child.returncode is not None for child in children)
            # Always reap the controlled real process, including a broken implementation.
            for child in children:
                if child.returncode is None:
                    child.kill()
                    await child.wait()
        assert drained, "Cancellation returned before the PDF worker was reaped"
        assert list(layout.artifacts.glob("reports/**/*.pdf")) == []
    asyncio.run(scenario())


def test_deadline_recovers_only_after_pdf_worker_is_reaped(tmp_path, monkeypatch):
    marker, children = held_worker(tmp_path, monkeypatch)
    async def scenario():
        layout, artifacts, snapshot, jobs, events = stores(tmp_path)
        provider = ReviewProvider()
        executor = CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events, provider, models=MODELS)
        accepted = FinalAcceptanceGate({}).accept(ReportDraft(snapshot_id=snapshot.snapshot_id,
            summary="Original report", coverage=Coverage()), [])
        async def execute(job):
            return await executor.render_report(job, accepted)
        async def recover(job):
            assert marker.exists() and children[0].returncode is not None
            assert list(layout.artifacts.glob("reports/**/*.pdf")) == []
            return await executor.recover_timeout(job)
        job = jobs.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="pdf-deadline")
        ledger = job.ledger.model_copy(deep=True)
        ledger.elapsed_seconds = 599.5
        jobs.update_ledger(job.job_id, owner="alice", ledger=ledger)
        manager = DurableJobManager(jobs, events, execute, recover_timeout=recover)
        try:
            await manager.start()
            complete = await asyncio.wait_for(manager.wait(job.job_id, owner="alice"), 8)
            assert complete.status == "completed"
            assert json.loads(complete.result["json"])["coverage"]["failed"]["__job"] == "review_time_exhausted"
            assert not provider.requests
            assert len(list(layout.artifacts.glob("reports/**/*.pdf"))) == 1
            assert len(children) == 2 and all(child.returncode is not None for child in children)
        finally:
            await manager.close()
            for child in children:
                if child.returncode is None:
                    child.kill()
                    await child.wait()
    asyncio.run(scenario())


def test_remote_cancellation_blocks_pdf_publication_before_worker_notification(tmp_path):
    async def scenario():
        layout, artifacts, snapshot, jobs, events = stores(tmp_path)
        executor = CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events, ReviewProvider(), models=MODELS)
        job = jobs.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="remote-cancel")
        jobs.transition(job.job_id, owner="alice", expected_status="queued", status="running")
        accepted = FinalAcceptanceGate({}).accept(ReportDraft(snapshot_id=snapshot.snapshot_id,
            summary="Accepted review", coverage=Coverage()), [])
        # Another service instance persists cancellation before this worker's
        # heartbeat notification. Rendering must consult durable status itself.
        jobs.transition(job.job_id, owner="alice", expected_status="running", status="cancelled")
        with pytest.raises(asyncio.CancelledError):
            await executor.render_report(job, accepted)
        assert list(layout.artifacts.glob("reports/**/*.pdf")) == []
    asyncio.run(scenario())
