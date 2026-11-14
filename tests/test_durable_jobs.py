"""Real SQLite stores and async execution, without provider/network calls."""

import asyncio
import importlib
from concurrent.futures import ThreadPoolExecutor

import pytest


def jobs():
    assert importlib.util.find_spec("devwatch.review.jobs"), "Durable jobs are missing"
    return importlib.import_module("devwatch.review.jobs")


def test_changed_accounting_publishes_transactional_metadata_without_duplicates(tmp_path):
    from devwatch.review.budgets import BudgetLedger
    api = jobs()
    store = api.JobStore(tmp_path / "devwatch.sqlite")
    job = store.submit(owner="alice", request={}, idempotency_key="accounting")
    ledger = BudgetLedger(agent_usage={"planner": {"prompt_tokens": 10, "completion_tokens": 5}})
    store.update_ledger(job.job_id, owner="alice", ledger=ledger)
    store.update_ledger(job.job_id, owner="alice", ledger=ledger)
    updates = [event for event in store.events(job.job_id, owner="alice") if event.type == "budget_updated"]
    assert len(updates) == 1
    assert updates[0].payload["total_tokens"] == 15


def test_submission_idempotency_is_atomic_owner_scoped_and_payload_guarded(tmp_path):
    api = jobs()
    store = api.JobStore(tmp_path / "devwatch.sqlite")
    def submit(_):
        return store.submit(owner="alice", request={"source_ref": "repo-a"}, idempotency_key="intent-1").job_id
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(submit, range(8)))
    assert len(set(results)) == 1
    with pytest.raises(api.JobConflict):
        store.submit(owner="alice", request={"source_ref": "repo-b"}, idempotency_key="intent-1")
    bob = store.submit(owner="bob", request={"source_ref": "repo-a"}, idempotency_key="intent-1")
    assert bob.job_id != results[0]


def test_job_and_events_survive_reopen_and_replay(tmp_path):
    api = jobs()
    db_path = tmp_path / "devwatch.sqlite"
    store = api.JobStore(db_path)
    job = store.submit(owner="alice", request={"source_ref": "repo-a"}, idempotency_key="intent-1")
    store.transition(job.job_id, owner="alice", expected_status="queued", status="running")
    reopened = api.JobStore(db_path)
    assert reopened.get(job.job_id, owner="alice").status == "running"
    history = reopened.events(job.job_id, owner="alice")
    assert [(e.seq, e.type) for e in history] == [(1, "job_queued"), (2, "job_running")]
    assert [e.seq for e in reopened.events(job.job_id, owner="alice", after=1)] == [2]


def test_owner_and_terminal_state_are_enforced(tmp_path):
    api = jobs()
    store = api.JobStore(tmp_path / "devwatch.sqlite")
    job = store.submit(owner="alice", request={}, idempotency_key="1")
    with pytest.raises(api.JobNotFound):
        store.get(job.job_id, owner="bob")
    with pytest.raises(api.JobNotFound):
        store.transition(job.job_id, owner="bob", expected_status="queued", status="cancelled")
    with pytest.raises(api.JobConflict):
        store.transition(job.job_id, owner="alice", expected_status="queued", status="completed")
    store.transition(job.job_id, owner="alice", expected_status="queued", status="cancelled")
    with pytest.raises(api.JobConflict):
        store.transition(job.job_id, owner="alice", expected_status="cancelled", status="queued")


def test_event_emission_redacts_secret_payload_fields(tmp_path):
    api = jobs()
    store = api.JobStore(tmp_path / "devwatch.sqlite")
    job = store.submit(owner="alice", request={}, idempotency_key="1")
    store.emit(job.job_id, owner="alice", event_type="tool_called", payload={"arguments": {"api_key": "secret"}})
    emitted = store.events(job.job_id, owner="alice")[-1]
    assert "secret" not in str(emitted.payload)
    assert emitted.payload["arguments"]["api_key"] == "[redacted]"


def test_client_wait_cancellation_does_not_cancel_canonical_job(tmp_path):
    api = jobs()
    async def scenario():
        store = api.JobStore(tmp_path / "devwatch.sqlite")
        started, release = asyncio.Event(), asyncio.Event()
        async def execute(job):
            started.set()
            await release.wait()
            return {"report_ref": "report-1"}
        manager = api.DurableJobManager(store, execute)
        job = await manager.submit(owner="alice", request={}, idempotency_key="1")
        await started.wait()
        subscriber = asyncio.create_task(manager.wait(job.job_id, owner="alice"))
        await asyncio.sleep(0)
        subscriber.cancel()
        with pytest.raises(asyncio.CancelledError):
            await subscriber
        assert store.get(job.job_id, owner="alice").status == "running"
        release.set()
        result = await manager.wait(job.job_id, owner="alice")
        assert result.status == "completed"
        assert result.result == {"report_ref": "report-1"}
        assert [e.type for e in store.events(job.job_id, owner="alice")] == ["job_queued", "job_running", "job_completed"]
        await manager.close()
    asyncio.run(scenario())


def test_explicit_cancel_persists_and_stops_execution(tmp_path):
    api = jobs()
    async def scenario():
        store = api.JobStore(tmp_path / "devwatch.sqlite")
        started, stopped = asyncio.Event(), asyncio.Event()
        async def execute(job):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        manager = api.DurableJobManager(store, execute)
        job = await manager.submit(owner="alice", request={}, idempotency_key="1")
        await started.wait()
        await manager.cancel(job.job_id, owner="alice")
        await stopped.wait()
        assert store.get(job.job_id, owner="alice").status == "cancelled"
        await manager.close()
    asyncio.run(scenario())


def test_shutdown_marks_interrupted_and_resume_retains_usage(tmp_path):
    api = jobs()
    async def scenario():
        store = api.JobStore(tmp_path / "devwatch.sqlite")
        started = asyncio.Event()
        async def interrupted(job):
            store.update_ledger(job.job_id, owner=job.owner, ledger={"task_tools": {"t1": 12}})
            started.set()
            await asyncio.Event().wait()
        manager = api.DurableJobManager(store, interrupted)
        job = await manager.submit(owner="alice", request={}, idempotency_key="1")
        await started.wait()
        await manager.close()
        saved = api.JobStore(tmp_path / "devwatch.sqlite").get(job.job_id, owner="alice")
        assert saved.status == "interrupted"
        assert saved.ledger.task_tools == {"t1": 12}
        async def resumed(job):
            assert job.ledger.task_tools == {"t1": 12}
            return {"report_ref": "resumed-report"}
        second = api.DurableJobManager(store, resumed)
        await second.resume(job.job_id, owner="alice")
        assert (await second.wait(job.job_id, owner="alice")).status == "completed"
        await second.close()
    asyncio.run(scenario())


def test_executor_conflict_marks_failed_rather_than_leaving_running_job(tmp_path):
    api = jobs()
    async def scenario():
        store = api.JobStore(tmp_path / "devwatch.sqlite")
        async def execute(job):
            raise api.JobConflict("invalid accounting update")
        manager = api.DurableJobManager(store, execute)
        job = await manager.submit(owner="alice", request={}, idempotency_key="1")
        await asyncio.gather(manager._tasks[job.job_id], return_exceptions=False)
        assert store.get(job.job_id, owner="alice").status == "failed"
        await manager.close()
    asyncio.run(scenario())


def test_job_time_reconciliation_does_not_double_count_agent_accounting(tmp_path):
    api = jobs()
    store = api.JobStore(tmp_path / "devwatch.sqlite")
    job = store.submit(owner="alice", request={}, idempotency_key="1")
    store.update_ledger(job.job_id, owner="alice", ledger={"elapsed_seconds": 12})
    store.account_execution_time(job.job_id, owner="alice", initial_elapsed=0, run_seconds=15)
    assert store.get(job.job_id, owner="alice").ledger.elapsed_seconds == 15


def test_shutdown_of_unclaimed_waiter_does_not_interrupt_another_manager(tmp_path):
    api = jobs()
    async def scenario():
        store = api.JobStore(tmp_path / "devwatch.sqlite")
        blocker_started, other_started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def blocking(job):
            blocker_started.set()
            await asyncio.Event().wait()
        first = api.DurableJobManager(store, blocking, concurrent_jobs=1)
        await first.submit(owner="alice", request={}, idempotency_key="blocker")
        await blocker_started.wait()
        waiting = await first.submit(owner="alice", request={}, idempotency_key="waiting")
        async def other(job):
            other_started.set()
            await release.wait()
            return {"report_ref": "report"}
        second = api.DurableJobManager(store, other)
        await second.start()
        await other_started.wait()
        await first.close()
        try:
            assert store.get(waiting.job_id, owner="alice").status == "running"
            release.set()
            assert (await second.wait(waiting.job_id, owner="alice")).status == "completed"
        finally:
            await second.close()
    asyncio.run(scenario())
