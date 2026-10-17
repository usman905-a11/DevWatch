"""Required M1 review cases: drain, retry and bounded durable admission."""
import asyncio
import json
import logging
import sqlite3
import threading
import time

import pytest

from devwatch.review.budgets import BudgetManager
from devwatch.review.contracts import AgentId, AgentPrivateState, ReviewTask
from devwatch.review.jobs import DurableJobManager, EventStore, JobStore
from devwatch.review.leases import execution_lock
from devwatch.review.repository import RepositoryContext
from devwatch.review.stores import RepoCache
from devwatch.review.workflow import CanonicalReviewExecutor, _ReviewSession
from tests.test_canonical_workflow import ReviewProvider, stores
from tests.test_control_agents import MODELS
from tests.test_crash_recovery import manager, reaches, worker


def test_shutdown_drains_checkpoint_thread_through_repeated_cancellation(tmp_path, monkeypatch):
    async def scenario():
        layout, artifacts, snapshot, jobs, events = stores(tmp_path)
        executor = CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events, ReviewProvider(), models=MODELS)
        entered, release = threading.Event(), threading.Event()
        save = executor.checkpoints.save
        def blocked_save(*args):
            entered.set()
            assert release.wait(5), "Controlled checkpoint write was not released"
            return save(*args)
        monkeypatch.setattr(executor.checkpoints, "save", blocked_save)
        sessions = []
        task = ReviewTask(task_id="saved-task", agent_id=AgentId.BUG_RELIABILITY, files=["service.py"], focus="Persist private progress")
        async def execute(job):
            session = _ReviewSession(executor, job,
                RepositoryContext(artifacts, executor.cache, snapshot.snapshot_id, owner="alice"),
                BudgetManager(job.limits, job.ledger.model_copy(deep=True)), ["service.py"])
            sessions.append(session)
            await session.persist_agent({"task": task, "private_state": AgentPrivateState(current_task="old-state")}, {})
            return {}
        first = DurableJobManager(jobs, events, execute)
        job = await first.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="blocked-save")
        assert await asyncio.to_thread(entered.wait, 3)
        closing = asyncio.create_task(first.close())
        await asyncio.sleep(.05)
        closing_again = asyncio.create_task(first.close())
        try:
            await asyncio.sleep(.05)
            assert not closing.done(), "Shutdown released ownership before the checkpoint thread drained"
            assert not closing_again.done()
            with execution_lock(jobs.path, job.job_id) as acquired:
                assert not acquired, "A new worker could overtake the old checkpoint writer"
            assert jobs.get(job.job_id, owner="alice").status == "running"
        finally:
            release.set()
            await asyncio.gather(closing, closing_again, return_exceptions=True)
        assert jobs.get(job.job_id, owner="alice").status == "interrupted"
        assert executor.checkpoints.load(sessions[0].thread_id, task.task_id)["state"]["private_state"]["current_task"] == "old-state"
        async def resumed(job):
            executor.checkpoints.save(sessions[0].thread_id,
                {"task": task, "private_state": AgentPrivateState(current_task="new-state")}, 1)
            return {}
        second = DurableJobManager(jobs, events, resumed)
        try:
            await second.resume(job.job_id, owner="alice")
            assert (await second.wait(job.job_id, owner="alice")).status == "completed"
            assert executor.checkpoints.load(sessions[0].thread_id, task.task_id)["state"]["private_state"]["current_task"] == "new-state"
        finally:
            await second.close()
    asyncio.run(scenario())


def test_transient_maintenance_failure_recovers_later_dead_worker(tmp_path, monkeypatch, caplog):
    with worker(tmp_path) as (process, identities):
        async def scenario():
            async def execute(job):
                return {}
            other = manager(tmp_path, execute)
            await other.start()
            original = other.store.running
            failed = asyncio.Event()
            def fail_once(*args, **kwargs):
                if not failed.is_set():
                    failed.set()
                    raise sqlite3.OperationalError("PRIVATE-SOURCE-MUST-NOT-BE-LOGGED")
                return original(*args, **kwargs)
            monkeypatch.setattr(other.store, "running", fail_once)
            try:
                await asyncio.wait_for(failed.wait(), 2)
                process.kill()
                process.wait(timeout=5)
                await reaches(other.store, identities["active"], "interrupted")
                assert "PRIVATE-SOURCE-MUST-NOT-BE-LOGGED" not in caplog.text
                assert any(record.name == "devwatch.review.jobs" and record.levelno >= logging.WARNING for record in caplog.records)
            finally:
                await other.close()
        asyncio.run(scenario())


def test_large_backlog_admits_only_worker_capacity_and_advances_without_new_submission(tmp_path):
    async def scenario():
        store, events = JobStore(tmp_path / "jobs.sqlite"), EventStore(tmp_path / "events.sqlite")
        queued = [store.submit(owner="alice", request={}, idempotency_key=str(index)) for index in range(80)]
        entered, release = asyncio.Event(), asyncio.Event()
        order = []
        async def execute(job):
            order.append(job.job_id)
            if len(order) <= 2:
                entered.set()
                await release.wait()
            return {}
        review = DurableJobManager(store, events, execute, concurrent_jobs=2)
        try:
            await review.start()
            await asyncio.wait_for(entered.wait(), 2)
            assert len(review._tasks) <= 2, "Persisted backlog must not become an unbounded in-memory task queue"
            release.set()
            await reaches(store, queued[2].job_id, "completed")
            assert order[:3] == [item.job_id for item in queued[:3]]
            assert len(review._tasks) <= 2
        finally:
            await review.close()
    asyncio.run(scenario())


def test_active_queries_do_not_deserialize_terminal_history_and_are_batched(tmp_path, monkeypatch):
    store = JobStore(tmp_path / "jobs.sqlite")
    template = store.submit(owner="alice", request={}, idempotency_key="terminal-template")
    with store._transaction() as db:
        for index in range(1000):
            record = template.model_copy(deep=True)
            record.job_id = f"archived-{index}"
            record.status = "completed"
            record.result = {"markdown": "Historical report " * 100}
            db.execute("INSERT INTO jobs VALUES(?,?,?,?,?)",
                (record.job_id, "alice", f"archive-{index}", "historical", record.model_dump_json()))
    waiting = [store.submit(owner="alice", request={}, idempotency_key=f"waiting-{i}") for i in range(120)]
    store.transition(template.job_id, owner="alice", expected_status="queued", status="cancelled")
    validated = []
    from devwatch.review.jobs import JobRecord
    validate = JobRecord.model_validate_json
    def count(raw, *args, **kwargs):
        validated.append(json.loads(raw)["status"])
        return validate(raw, *args, **kwargs)
    monkeypatch.setattr(JobRecord, "model_validate_json", count)
    began = time.perf_counter()
    running = store.running()
    ready = store.queued()
    duration = time.perf_counter() - began
    print(f"Active query sample: {duration:.6f}s, {len(validated)} deserialized records")
    assert running == []
    assert "completed" not in validated and "cancelled" not in validated
    assert 1 <= len(ready) <= 100
    assert [record.job_id for record in ready] == [record.job_id for record in waiting[:len(ready)]]
