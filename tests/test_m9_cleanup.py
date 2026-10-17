"""Retention against real local stores; no user runtime is cleaned by these tests."""
import json
from contextlib import closing
import os
from pathlib import Path
import subprocess
import sys
from hashlib import sha256
import sqlite3
import time

import pytest

from devwatch.review.jobs import EventStore, JobNotFound, JobStore
from devwatch.review.stores import ArtifactStore, CacheKey, RepoCache, StoreLayout


def api():
    from devwatch.review.cleanup import RetentionPolicy, cleanup_storage
    return RetentionPolicy, cleanup_storage


def apply_cleanup(cleanup, layout, policy, **kwargs):
    """Explicitly approve the fresh preview, only inside this test's tmp_path."""
    preview = cleanup(layout, policy, **kwargs)
    return cleanup(layout, policy, dry_run=False, plan_id=preview.plan_id, **kwargs)


def setup(tmp_path):
    layout = StoreLayout(tmp_path / "runtime")
    jobs, events = JobStore(layout.jobs), EventStore(layout.events)
    return layout, jobs, events, ArtifactStore(layout.artifacts), RepoCache(layout.repo_cache)


def job(jobs, artifacts, status="completed", *, snapshot=None, owner="alice"):
    snapshot = snapshot or artifacts.capture(owner=owner, files={"app.py": "pass\n"})
    record = jobs.submit(owner=owner, request={"snapshot_id": snapshot.snapshot_id}, idempotency_key=os.urandom(8).hex())
    if status == "cancelled":
        return jobs.transition(record.job_id, owner=owner, expected_status="queued", status=status)
    if status != "queued":
        record = jobs.transition(record.job_id, owner=owner, expected_status="queued", status="running")
    if status not in {"queued", "running"}:
        record = jobs.transition(record.job_id, owner=owner, expected_status="running", status=status)
    return record


def age_job(jobs, record, timestamp):
    record.updated_at = timestamp
    with closing(sqlite3.connect(jobs.path)) as db, db:
        db.execute("UPDATE jobs SET record=? WHERE job_id=?", (record.model_dump_json(), record.job_id))


def age_tree(path, timestamp):
    for child in sorted(path.rglob("*"), reverse=True):
        os.utime(child, (timestamp, timestamp))
    os.utime(path, (timestamp, timestamp))


def test_preview_then_expiry_prunes_terminal_bundle_and_is_repeatable(tmp_path):
    Policy, cleanup = api()
    layout, jobs, events, artifacts, _ = setup(tmp_path)
    record = job(jobs, artifacts)
    now = time.time()
    old = now - 40 * 86400
    age_job(jobs, record, old)
    jobs.dispatch_events(events)
    events.admit_telemetry()
    snapshot = layout.artifacts / "snapshots" / record.request["snapshot_id"]
    age_tree(snapshot, old)
    evidence = layout.artifacts / "evidence" / snapshot.name
    evidence.mkdir(parents=True)
    (evidence / ("evidence-" + "e" * 64 + ".json")).write_text("{}")
    age_tree(evidence, old)
    artifacts.put_report_pdf(record.job_id, snapshot.name, owner=record.owner, data=b"%PDF-1.7\nfixture\n%%EOF")
    thread = sha256((record.owner + "\0" + record.job_id).encode()).hexdigest()
    from devwatch.review.workflow import AgentCheckpoints
    AgentCheckpoints(layout.checkpoints)
    with closing(sqlite3.connect(layout.checkpoints)) as db, db:
        db.execute("INSERT INTO agent_progress VALUES(?,?,?,?,?)", (thread, "task", "seven-agent-v1", 0, "{}"))
        db.execute("CREATE TABLE checkpoints(thread_id TEXT, checkpoint BLOB)")
        db.execute("CREATE TABLE writes(thread_id TEXT, value BLOB)")
        db.execute("INSERT INTO checkpoints VALUES(?,?)", (thread, b"checkpoint"))
        db.execute("INSERT INTO writes VALUES(?,?)", (thread, b"write"))
    preview = cleanup(layout, Policy(), now=now)
    assert preview.dry_run and preview.jobs == 1 and preview.events == 3 and preview.checkpoints == 3
    assert preview.snapshots == 1 and preview.evidence == 1 and preview.reports == 1
    assert preview.bytes_candidates > 0
    assert jobs.get(record.job_id, owner=record.owner) and snapshot.exists()
    result = apply_cleanup(cleanup, layout, Policy(), now=now)
    from devwatch.review.cleanup import _disk_bytes
    assert result.bytes_after == _disk_bytes(layout.root)
    assert result.jobs == 1 and result.bytes_after < result.bytes_before
    with pytest.raises(JobNotFound):
        jobs.get(record.job_id, owner=record.owner)
    assert not snapshot.exists() and not evidence.exists() and not events.replay(record.job_id)
    with closing(sqlite3.connect(layout.events)) as db, db:
        assert db.execute("SELECT count(*) FROM telemetry_attempts").fetchone()[0] == 0
    with closing(sqlite3.connect(layout.jobs)) as db, db:
        assert db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 0
    assert apply_cleanup(cleanup, layout, Policy(), now=now).jobs == 0


@pytest.mark.parametrize("status", ["queued", "running", "interrupted", "completed", "failed", "cancelled"])
def test_old_recoverable_and_recent_terminal_jobs_preserve_shared_snapshot(tmp_path, status):
    Policy, cleanup = api()
    layout, jobs, events, artifacts, _ = setup(tmp_path)
    first = job(jobs, artifacts)
    snapshot = artifacts.manifest(first.request["snapshot_id"], owner=first.owner)
    kept = job(jobs, artifacts, status, snapshot=snapshot)
    now = time.time()
    age_job(jobs, first, now - 40 * 86400)
    if status in {"queued", "running", "interrupted"}:
        age_job(jobs, kept, now - 40 * 86400)
    age_tree(layout.artifacts / "snapshots" / snapshot.snapshot_id, now - 40 * 86400)
    result = apply_cleanup(cleanup, layout, Policy(), now=now)
    assert result.jobs == 1 and result.snapshots == 0
    assert artifacts.read_source(snapshot.snapshot_id, "app.py", owner=first.owner) == "pass\n"
    assert jobs.get(kept.job_id, owner=kept.owner).status == status


def test_old_orphans_and_scratch_expire_but_recent_and_unknown_files_stay(tmp_path):
    Policy, cleanup = api()
    layout, jobs, events, artifacts, _ = setup(tmp_path)
    old_snapshot = artifacts.capture(owner="alice", files={"app.py": "pass"})
    recent = artifacts.capture(owner="alice", files={})
    scratch = artifacts.create_scratch(old_snapshot.snapshot_id, owner="alice")
    unknown = layout.artifacts / "scratch" / "my-notes"
    unknown.mkdir()
    (unknown / "keep.txt").write_text("keep")
    now = time.time()
    for target in (scratch, unknown, layout.artifacts / "snapshots" / old_snapshot.snapshot_id):
        age_tree(target, now - 40 * 86400)
    result = apply_cleanup(cleanup, layout, Policy(), now=now)
    assert result.snapshots == 1 and result.scratch == 1
    assert not scratch.exists() and unknown.exists()
    assert artifacts.manifest(recent.snapshot_id, owner="alice")


def test_runtime_reader_lock_blocks_cleanup_and_exclusive_blocks_readers(tmp_path):
    Policy, cleanup = api()
    from devwatch.review.leases import runtime_lock
    layout, *_ = setup(tmp_path)
    with runtime_lock(layout.root) as first, runtime_lock(layout.root) as second:
        assert first and second
        with pytest.raises(RuntimeError, match="in use"):
            cleanup(layout, Policy())
    with runtime_lock(layout.root, exclusive=True) as writer:
        assert writer
        with runtime_lock(layout.root) as reader:
            assert not reader
    assert cleanup(layout, Policy()).dry_run


def test_cache_access_migration_and_expiry(tmp_path, monkeypatch):
    Policy, cleanup = api()
    layout, *_ = setup(tmp_path)
    with closing(sqlite3.connect(layout.repo_cache)) as db, db:
        db.execute("DROP TABLE cache")
        db.execute("CREATE TABLE cache(digest TEXT PRIMARY KEY,payload TEXT NOT NULL)")
        db.execute("INSERT INTO cache VALUES('legacy','{}')")
    cache = RepoCache(layout.repo_cache)
    key = CacheKey(owner_namespace="alice", namespace="test", content_hash="hash")
    cache.put(key, {"value": 1})
    now = time.time()
    with closing(sqlite3.connect(layout.repo_cache)) as db, db:
        db.execute("UPDATE cache SET last_used=?", (now - 40 * 86400,))
    assert cache.get(key) == {"value": 1}
    assert cleanup(layout, Policy(), now=now).cache_entries == 1
    apply_cleanup(cleanup, layout, Policy(), now=now)
    assert cache.get(key) == {"value": 1}
    with closing(sqlite3.connect(layout.repo_cache)) as db, db:
        assert db.execute("SELECT count(*) FROM cache").fetchone()[0] == 1


@pytest.mark.parametrize("field", ["terminal_days", "orphan_days", "scratch_hours", "cache_days"])
@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_retention_rejects_invalid_thresholds(field, value):
    Policy, _ = api()
    with pytest.raises(ValueError):
        Policy(**{field: value})


def test_preview_never_changes_content_or_database_rows(tmp_path):
    Policy, cleanup = api()
    layout, jobs, events, artifacts, cache = setup(tmp_path)
    record = job(jobs, artifacts)
    now = time.time()
    age_job(jobs, record, now - 40 * 86400)
    jobs.dispatch_events(events)
    before = jobs.get(record.job_id, owner=record.owner).model_dump_json()
    history = events.replay(record.job_id)
    first = cleanup(layout, Policy(), now=now)
    second = cleanup(layout, Policy(), now=now)
    assert first.plan_id == second.plan_id and len(first.plan_id) == 64
    assert jobs.get(record.job_id, owner=record.owner).model_dump_json() == before
    assert events.replay(record.job_id) == history
    assert artifacts.read_source(record.request["snapshot_id"], "app.py", owner=record.owner) == "pass\n"


def test_runtime_process_lock_is_shared_and_released_on_process_death(tmp_path):
    Policy, cleanup = api()
    layout, *_ = setup(tmp_path)
    script = ("import sys; from devwatch.review.leases import runtime_lock; "
              "lease=runtime_lock(sys.argv[1]); assert lease.__enter__(); "
              "print('ready',flush=True); sys.stdin.read()")
    child = subprocess.Popen([sys.executable, "-u", "-c", script, str(layout.root)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "ready"
        from devwatch.review.leases import runtime_lock
        with runtime_lock(layout.root) as shared:
            assert shared
        with pytest.raises(RuntimeError, match="in use"):
            cleanup(layout, Policy())
    finally:
        child.kill()
        child.communicate(timeout=10)
    assert cleanup(layout, Policy()).dry_run


@pytest.mark.parametrize("location", ["artifact-root", "nested-scratch", "database"])
def test_links_are_refused_before_a_cleanup_plan_is_issued(tmp_path, location):
    Policy, cleanup = api()
    layout, _, _, artifacts, _ = setup(tmp_path)
    outside = tmp_path / "unrelated"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("keep")
    if location == "artifact-root":
        path = layout.artifacts / "evidence"
    elif location == "nested-scratch":
        snapshot = artifacts.capture(owner="alice", files={"app.py": "pass"})
        scratch = artifacts.create_scratch(snapshot.snapshot_id, owner="alice")
        path = scratch / "escape"
        os.utime(scratch, (0, 0))
    else:
        path = layout.checkpoints
        os.link(sentinel, path)
    if location != "database":
        if os.name == "nt":
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(path), str(outside)], capture_output=True)
            assert result.returncode == 0, result.stderr
        else:
            path.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="cleanup path"):
        cleanup(layout, Policy())
    assert sentinel.read_text() == "keep"


def test_unknown_root_and_bad_snapshot_identity_refuse_preview(tmp_path):
    Policy, cleanup = api()
    with pytest.raises(ValueError, match="existing canonical"):
        cleanup(StoreLayout(tmp_path / "missing"), Policy())
    layout, _, _, artifacts, _ = setup(tmp_path)
    snapshot = artifacts.capture(owner="alice", files={})
    path = layout.artifacts / "snapshots" / snapshot.snapshot_id / "manifest.json"
    data = json.loads(path.read_text())
    data["snapshot_id"] = "f" * 32
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="identity mismatch"):
        cleanup(layout, Policy())


def test_live_terminal_execution_lock_preserves_bundle(tmp_path):
    Policy, cleanup = api()
    from devwatch.review.leases import execution_lock
    layout, jobs, _, artifacts, _ = setup(tmp_path)
    record = job(jobs, artifacts, "cancelled")
    now = time.time()
    age_job(jobs, record, now - 40 * 86400)
    with execution_lock(layout.jobs, record.job_id) as acquired:
        assert acquired
        assert cleanup(layout, Policy(), now=now).jobs == 0
    assert cleanup(layout, Policy(), now=now).jobs == 1


def test_running_service_excludes_preview_until_shutdown(tmp_path):
    Policy, cleanup = api()
    from fastapi.testclient import TestClient
    from tests.test_review_service import app
    application = app(tmp_path)
    with TestClient(application) as client:
        assert client.get("/health").status_code == 200
        with pytest.raises(RuntimeError, match="in use"):
            cleanup(StoreLayout(tmp_path / "runtime"), Policy())
    assert cleanup(StoreLayout(tmp_path / "runtime"), Policy()).jobs == 0


def test_direct_job_manager_excludes_preview_until_drained(tmp_path):
    Policy, cleanup = api()
    import asyncio
    from devwatch.review.jobs import DurableJobManager
    layout, jobs, events, _, _ = setup(tmp_path)

    async def scenario():
        async def execute(record):
            await asyncio.Event().wait()
        manager = DurableJobManager(jobs, events, execute)
        await manager.start()
        try:
            with pytest.raises(RuntimeError, match="in use"):
                cleanup(layout, Policy())
        finally:
            await manager.close()
        assert cleanup(layout, Policy()).dry_run
    asyncio.run(scenario())


def test_apply_requires_matching_unchanged_preview(tmp_path):
    Policy, cleanup = api()
    layout, jobs, _, artifacts, _ = setup(tmp_path)
    record = job(jobs, artifacts)
    now = time.time()
    age_job(jobs, record, now - 40 * 86400)
    with pytest.raises(ValueError, match="plan ID"):
        cleanup(layout, Policy(), dry_run=False, now=now)
    preview = cleanup(layout, Policy(), now=now)
    snapshot = layout.artifacts / "snapshots" / record.request["snapshot_id"]
    (snapshot / "source" / "app.py").write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        cleanup(layout, Policy(), dry_run=False, plan_id=preview.plan_id, now=now)
    assert jobs.get(record.job_id, owner=record.owner) and snapshot.exists()


def test_failed_artifact_deletion_keeps_job_for_retry(tmp_path, monkeypatch):
    Policy, cleanup = api()
    import shutil
    layout, jobs, events, artifacts, _ = setup(tmp_path)
    record = job(jobs, artifacts)
    now = time.time()
    age_job(jobs, record, now - 40 * 86400)
    jobs.dispatch_events(events)
    real = shutil.rmtree

    def fail(path, *args, **kwargs):
        if Path(path).is_relative_to(layout.artifacts):
            raise PermissionError("busy test artifact")
        return real(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(shutil, "rmtree", fail)
        with pytest.raises(PermissionError):
            apply_cleanup(cleanup, layout, Policy(), now=now)
    assert jobs.get(record.job_id, owner=record.owner) and events.replay(record.job_id)
    assert apply_cleanup(cleanup, layout, Policy(), now=now).jobs == 1


def test_cleanup_cli_previews_and_requires_exact_plan_for_apply(tmp_path):
    from typer.testing import CliRunner
    from devwatch.cli import app
    layout, jobs, _, artifacts, _ = setup(tmp_path)
    record = job(jobs, artifacts)
    age_job(jobs, record, time.time() - 40 * 86400)
    runner = CliRunner()
    base = ["cleanup", "--runtime-dir", str(layout.root)]
    preview = runner.invoke(app, base)
    assert preview.exit_code == 0, preview.output
    data = json.loads(preview.output)
    assert data["dry_run"] and data["jobs"] == 1
    assert data["retention"]["terminal_days"] == 30
    refused = runner.invoke(app, base + ["--apply"])
    assert refused.exit_code == 1 and "plan ID" in refused.output
    assert jobs.get(record.job_id, owner=record.owner)
    applied = runner.invoke(app, base + ["--apply", "--plan-id", data["plan_id"]])
    assert applied.exit_code == 0, applied.output
    assert not json.loads(applied.output)["dry_run"]
    assert not runner.invoke(app, base + ["--terminal-days", "0"]).exit_code == 0


def test_policy_from_environment_and_cli_override(tmp_path, monkeypatch):
    Policy, cleanup = api()
    from typer.testing import CliRunner
    from devwatch.cli import app
    layout, *_ = setup(tmp_path)
    monkeypatch.setenv("DEVWATCH_RUNTIME_DIR", str(layout.root))
    monkeypatch.setenv("DEVWATCH_RETENTION_SCRATCH_HOURS", "12")
    assert Policy.from_env().scratch_hours == 12
    result = CliRunner().invoke(app, ["cleanup", "--cache-days", "7"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["retention"] == {
        "scratch_hours": 12, "cache_days": 7, "orphan_days": 30, "terminal_days": 30}


def test_scratch_boundary_and_recent_nested_content_are_preserved(tmp_path):
    Policy, cleanup = api()
    layout, _, _, artifacts, _ = setup(tmp_path)
    snapshot = artifacts.capture(owner="alice", files={"app.py": "pass"})
    boundary = artifacts.create_scratch(snapshot.snapshot_id, owner="alice")
    active = artifacts.create_scratch(snapshot.snapshot_id, owner="alice")
    expired = artifacts.create_scratch(snapshot.snapshot_id, owner="alice")
    now = time.time()
    cutoff = now - 86400
    for path in (boundary, active):
        age_tree(path, cutoff)
    # A directory timestamp alone must never expire newly written nested output.
    os.utime(active / "app.py", (now, now))
    age_tree(expired, cutoff - 1)
    result = apply_cleanup(cleanup, layout, Policy(), now=now)
    assert result.scratch == 1
    assert boundary.exists() and active.exists() and not expired.exists()


def test_measurements_reports_and_abandoned_pending_files_expire(tmp_path):
    Policy, cleanup = api()
    layout, jobs, _, artifacts, _ = setup(tmp_path)
    record = job(jobs, artifacts, "interrupted")
    now = time.time()
    owner = sha256(record.owner.encode()).hexdigest()
    kept_evidence = layout.artifacts / "evidence" / record.request["snapshot_id"]
    kept_evidence.mkdir(parents=True)
    retained = kept_evidence / ("evidence-" + "e" * 64 + ".json")
    retained.write_text("{}")
    old_pending = kept_evidence / ("pending-" + "a" * 32)
    old_pending.write_text("partial")
    age_tree(kept_evidence, now - 40 * 86400)
    recent_pending = kept_evidence / ("pending-" + "b" * 32)
    recent_pending.write_text("recent")
    measurement_root = layout.artifacts / "measurements" / owner / record.job_id
    measurement_root.mkdir(parents=True)
    measurement_pending = measurement_root / ("measurement-" + "e" * 64 + "." + "f" * 32 + ".tmp")
    measurement_pending.write_text("partial measurement")
    age_tree(measurement_root, now - 40 * 86400)
    expired_paths = []
    for category in ("reports", "measurements"):
        path = layout.artifacts / category / owner / ("c" * 32)
        path.mkdir(parents=True)
        (path / "artifact.json").write_text("{}")
        age_tree(path, now - 40 * 86400)
        expired_paths.append(path)
    staged = layout.artifacts / "snapshots" / ("pending-" + "d" * 32)
    staged.mkdir()
    (staged / "partial.py").write_text("partial")
    age_tree(staged, now - 40 * 86400)
    result = apply_cleanup(cleanup, layout, Policy(), now=now)
    assert result.measurements == 1 and result.reports == 1 and result.temporary == 3
    assert not any(path.exists() for path in [old_pending, staged, measurement_pending, *expired_paths])
    assert retained.exists() and recent_pending.exists()
    assert jobs.get(record.job_id, owner=record.owner).status == "interrupted"


def test_partial_snapshot_removal_can_be_retried(tmp_path, monkeypatch):
    Policy, cleanup = api()
    import shutil
    layout, jobs, _, artifacts, _ = setup(tmp_path)
    record = job(jobs, artifacts)
    now = time.time()
    age_job(jobs, record, now - 40 * 86400)
    snapshot = layout.artifacts / "snapshots" / record.request["snapshot_id"]
    real = shutil.rmtree

    def partial(path, *args, **kwargs):
        if Path(path) == snapshot:
            (snapshot / "manifest.json").unlink()
            raise PermissionError("partial test deletion")
        return real(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(shutil, "rmtree", partial)
        with pytest.raises(PermissionError):
            apply_cleanup(cleanup, layout, Policy(), now=now)
    assert jobs.get(record.job_id, owner=record.owner)
    assert apply_cleanup(cleanup, layout, Policy(), now=now).snapshots == 1


def test_service_and_manager_refuse_to_start_during_exclusive_maintenance(tmp_path):
    Policy, cleanup = api()
    import asyncio
    from fastapi.testclient import TestClient
    from devwatch.review.jobs import DurableJobManager
    from devwatch.review.leases import runtime_lock
    from tests.test_review_service import app
    layout, jobs, events, *_ = setup(tmp_path)

    async def scenario():
        async def execute(record):
            return {}
        manager = DurableJobManager(jobs, events, execute)
        with pytest.raises(RuntimeError, match="maintenance"):
            await manager.submit(owner="alice", request={}, idempotency_key="blocked")
        assert not jobs.queued()
        await manager.close()

    with runtime_lock(layout.root, exclusive=True) as acquired:
        assert acquired
        with pytest.raises(RuntimeError, match="maintenance"):
            with TestClient(app(tmp_path)):
                pass
        asyncio.run(scenario())


def test_unknown_directories_with_temporary_looking_files_stay(tmp_path):
    Policy, cleanup = api()
    layout, *_ = setup(tmp_path)
    unrelated = layout.artifacts / "reports" / "my-notes"
    unrelated.mkdir()
    path = unrelated / ("pending-" + "a" * 32)
    path.write_text("user notes")
    age_tree(unrelated, time.time() - 40 * 86400)
    result = apply_cleanup(cleanup, layout, Policy())
    assert result.temporary == 0 and path.read_text() == "user notes"


def test_interrupted_graph_resumes_after_offline_cleanup(tmp_path):
    Policy, cleanup = api()
    import asyncio
    from devwatch.review.jobs import DurableJobManager
    from devwatch.review.contracts import ModelTier
    from devwatch.review.workflow import CanonicalReviewExecutor
    from tests.test_canonical_workflow import ReviewProvider, stores

    async def scenario():
        layout, artifacts, snapshot, jobs, events = stores(tmp_path)
        entered = asyncio.Event()

        class Paused(ReviewProvider):
            async def generate_completion(self, request):
                if json.loads(request.prompt)["phase"] == "synthesis":
                    entered.set()
                    await asyncio.Event().wait()
                return await super().generate_completion(request)

        models = {tier: tier.value for tier in ModelTier}
        executor = CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events, Paused(), models=models)
        manager = DurableJobManager(jobs, events, executor)
        record = await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="recover")
        await asyncio.wait_for(entered.wait(), timeout=10)
        await manager.close()
        interrupted = jobs.get(record.job_id, owner="alice")
        assert interrupted.status == "interrupted"
        now = time.time()
        age_job(jobs, interrupted, now - 40 * 86400)
        age_tree(layout.artifacts / "snapshots" / snapshot.snapshot_id, now - 40 * 86400)
        expired = job(jobs, artifacts)
        age_job(jobs, expired, now - 40 * 86400)
        assert apply_cleanup(cleanup, layout, Policy(), now=now).jobs == 1
        provider = ReviewProvider()
        resumed = DurableJobManager(jobs, events, CanonicalReviewExecutor(
            layout, artifacts, RepoCache(layout.repo_cache), jobs, events, provider, models=models))
        try:
            await resumed.resume(record.job_id, owner="alice")
            completed = await resumed.wait(record.job_id, owner="alice")
            assert completed.status == "completed"
            assert [json.loads(request.prompt)["phase"] for request in provider.requests] == ["synthesis"]
            assert completed.ledger.total_tokens == interrupted.ledger.total_tokens + 15
        finally:
            await resumed.close()
    asyncio.run(scenario())


def test_cleanup_handles_many_terminal_runs_without_exhausting_file_handles(tmp_path):
    Policy, cleanup = api()
    layout, jobs, _, artifacts, _ = setup(tmp_path)
    original = job(jobs, artifacts)
    now = time.time()
    original.updated_at = now - 40 * 86400
    age_job(jobs, original, original.updated_at)
    rows = []
    for index in range(599):
        record = original.model_copy(update={"job_id": f"{index:032x}"})
        rows.append((record.job_id, record.owner, f"old-{index}", "unused", record.model_dump_json()))
    with closing(sqlite3.connect(layout.jobs)) as db, db:
        db.executemany("INSERT INTO jobs VALUES(?,?,?,?,?)", rows)
    result = apply_cleanup(cleanup, layout, Policy(), now=now)
    assert result.jobs == 600 and result.snapshots == 1


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_database_sidecar_links_are_refused_before_opening_sqlite(tmp_path, suffix):
    Policy, cleanup = api()
    layout, *_ = setup(tmp_path)
    sentinel = tmp_path / "unrelated.txt"
    sentinel.write_bytes(b"unrelated data")
    os.link(sentinel, Path(str(layout.jobs) + suffix))
    with pytest.raises(ValueError, match="cleanup path"):
        cleanup(layout, Policy())
    assert sentinel.read_bytes() == b"unrelated data"
