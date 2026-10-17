"""Preview and explicitly apply local retention in a private local directory.

Normal service/worker processes cooperate through the runtime lease. This is not
a sandbox against a hostile process with write access to that same directory.
"""
from contextlib import ExitStack, closing
from dataclasses import dataclass, asdict, field
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import time

from devwatch.review.jobs import JobRecord
from devwatch.review.leases import execution_lock, runtime_lock
from devwatch.review.stores import SnapshotManifest, StoreLayout


@dataclass(frozen=True)
class RetentionPolicy:
    terminal_days: float = 30
    orphan_days: float = 30
    scratch_hours: float = 24
    cache_days: float = 30

    def __post_init__(self):
        if any(not math.isfinite(value) or value <= 0 for value in asdict(self).values()):
            raise ValueError("retention ages must be finite and positive")

    @classmethod
    def from_env(cls):
        return cls(**{name: float(os.getenv("DEVWATCH_RETENTION_" + name.upper(), str(default)))
                      for name, default in asdict(cls()).items()})


@dataclass
class CleanupReport:
    dry_run: bool = True
    plan_id: str = ""
    jobs: int = 0
    snapshots: int = 0
    scratch: int = 0
    evidence: int = 0
    reports: int = 0
    measurements: int = 0
    temporary: int = 0
    checkpoints: int = 0
    events: int = 0
    cache_entries: int = 0
    bytes_candidates: int = 0
    bytes_before: int = 0
    bytes_after: int = 0
    paths: list[str] = field(default_factory=list)
    job_ids: list[str] = field(default_factory=list)


def _safe(root: Path, path: Path):
    """Check every ancestor without following links, including Windows junctions."""
    if not path.is_relative_to(root) or path == root or not path.resolve().is_relative_to(root):
        raise ValueError(f"unsafe cleanup path: {path}")
    for part in (path, *path.parents):
        if part == root:
            break
        if not part.exists() and not part.is_symlink():
            continue
        info = part.lstat()
        if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                or (stat.S_ISREG(info.st_mode) and info.st_nlink > 1)):
            raise ValueError(f"linked cleanup path refused: {part}")


def _tree(root, path):
    _safe(root, path)
    paths = [path]
    if path.is_dir():
        for directory, folders, files in os.walk(path, followlinks=False):
            for name in folders + files:
                child = Path(directory) / name
                _safe(root, child)
                paths.append(child)
    return paths


def _tables(db):
    return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _disk_bytes(root):
    total = 0
    for directory, folders, files in os.walk(root, followlinks=False):
        # Never traverse unknown junctions or links while measuring disk use.
        folders[:] = [name for name in folders if not (
            (Path(directory) / name).lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
            if os.name == "nt" else (Path(directory) / name).is_symlink())]
        for name in files:
            path = Path(directory) / name
            if not path.is_symlink():
                total += path.lstat().st_size
    return total


def cleanup_storage(layout: StoreLayout, policy: RetentionPolicy, *, dry_run=True, now=None, plan_id=None):
    """Apply only a matching preview under exclusive runtime and SQLite leases.

    No automatic deletion or compaction. Callers must inspect a preview and pass
    its plan_id explicitly. Changes invalidate the plan; there is no force mode.
    """
    if not dry_run and (not isinstance(plan_id, str) or not re.fullmatch(r"[0-9a-f]{64}", plan_id)):
        raise ValueError("apply requires the plan ID from a cleanup preview")
    root = layout.root
    if not root.is_dir():
        raise ValueError("select an existing canonical runtime directory")
    required = {layout.jobs: {"jobs", "outbox", "execution_leases", "tool_operations"},
                layout.events: {"events", "telemetry_attempts"}, layout.repo_cache: {"cache"}}
    # Even a read-only SQLite connection can update shared-memory/recovery sidecars.
    # Validate them before opening any database, not after inspecting its schema.
    for path in (*required, layout.checkpoints, root / ".maintenance.lock"):
        for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm"), Path(str(path) + "-journal")):
            _safe(root, candidate)
    for path, expected in required.items():
        _safe(root, path)
        if not path.is_file():
            raise ValueError("select an existing canonical runtime directory")
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            if not expected <= _tables(db):
                raise ValueError("unrecognized canonical store schema")
    for name in ("snapshots", "scratch", "reports", "evidence", "measurements"):
        _safe(root, layout.artifacts / name)
    with runtime_lock(root, exclusive=True) as acquired:
        if not acquired:
            raise RuntimeError("runtime is in use; stop services and workers before cleanup")
        bytes_before = _disk_bytes(root)
        with ExitStack() as stack:
            report, candidates, deletions, dbs = _plan_locked(
                layout, policy, time.time() if now is None else now, stack, writable=not dry_run)
            if not dry_run:
                if report.plan_id != plan_id:
                    raise ValueError("cleanup plan changed; inspect a new preview before applying")
                # Validate the entire selected set again before the first mutation.
                for path in candidates:
                    _tree(root, path)
                for path in candidates:
                    _tree(root, path)
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                # Expired job records remain until their artifacts are gone. Each
                # store commits independently; retries finish a partial cleanup.
                # No VACUUM: freed SQLite pages are reused by later local runs.
                for name in ("checkpoints", "events", "cache", "jobs"):
                    if name in dbs:
                        for target, sql, args in deletions:
                            if target == name:
                                dbs[name].execute(sql, args)
                        dbs[name].commit()
                report.dry_run = False
        # Closing the last SQLite connection checkpoints/removes transient WAL/SHM
        # files. Measure after that drain, while the runtime remains exclusively held.
        report.bytes_before = bytes_before
        report.bytes_after = _disk_bytes(root)
        return report


def _plan_locked(layout, policy, now, stack, *, writable=False):
    if not math.isfinite(now) or now < 0:
        raise ValueError("cleanup time must be finite and nonnegative")
    root = layout.root
    report = CleanupReport()
    mode = "rw" if writable else "ro"
    dbs = {name: stack.enter_context(closing(sqlite3.connect(path.as_uri() + "?mode=" + mode, uri=True, timeout=0))) for name, path in
           (("jobs", layout.jobs), ("events", layout.events), ("cache", layout.repo_cache))}
    if layout.checkpoints.exists():
        dbs["checkpoints"] = stack.enter_context(closing(sqlite3.connect(layout.checkpoints.as_uri() + "?mode=" + mode, uri=True, timeout=0)))
    if writable:
        for db in dbs.values():
            db.execute("BEGIN IMMEDIATE")
    records = [JobRecord.model_validate_json(row[0]) for row in dbs["jobs"].execute("SELECT record FROM jobs ORDER BY job_id")]
    expired, kept = [], []
    for record in records:
        if record.status in {"completed", "failed", "cancelled"} and record.updated_at < now - policy.terminal_days * 86400:
            # Terminal jobs cannot be resumed or claimed again. The runtime lease
            # excludes new workers; release this drain probe promptly rather than
            # hold one file descriptor for every historical review in the store.
            with execution_lock(layout.jobs, record.job_id) as acquired:
                if acquired:
                    expired.append(record)
                    continue
        kept.append(record)
    report.jobs = len(expired)
    report.job_ids = [record.job_id for record in expired]
    protected = {record.request.get("snapshot_id") for record in kept}
    expired_snapshots = {record.request.get("snapshot_id") for record in expired} - protected
    expired_ids = {(sha256(record.owner.encode()).hexdigest(), record.job_id) for record in expired}
    kept_ids = {(sha256(record.owner.encode()).hexdigest(), record.job_id) for record in kept}
    candidates, fingerprints, temporary_parents = [], [], []

    def add(path, kind, *, cutoff=None):
        entries = _tree(root, path)
        if cutoff is not None and max(item.stat().st_mtime for item in entries) >= cutoff:
            return False
        for item in entries:
            info = item.stat()
            fingerprints.append((item.relative_to(root).as_posix(), info.st_size, info.st_mtime_ns, info.st_ino))
            if item.is_file():
                report.bytes_candidates += info.st_size
        setattr(report, kind, getattr(report, kind) + 1)
        candidates.append(path)
        return True

    orphan_cutoff = now - policy.orphan_days * 86400
    scratch_cutoff = now - policy.scratch_hours * 3600
    removed_snapshots = set()
    for category in ("snapshots", "scratch", "evidence"):
        parent = layout.artifacts / category
        for path in sorted(parent.iterdir()) if parent.exists() else ():
            if re.fullmatch(r"pending-[0-9a-f]{32}", path.name):
                add(path, "temporary", cutoff=scratch_cutoff)
            elif re.fullmatch(r"[0-9a-f]{32}", path.name):
                if category == "evidence":
                    temporary_parents.append((category, path))
                if category != "scratch" and path.name in protected:
                    continue
                if category == "snapshots":
                    manifest_path = path / "manifest.json"
                    _safe(root, manifest_path)
                    # An interrupted deletion can leave an expired owned snapshot
                    # without its manifest. Keep the job until retry finishes it.
                    if manifest_path.exists() or path.name not in expired_snapshots:
                        manifest = SnapshotManifest.model_validate_json(manifest_path.read_bytes())
                        if manifest.snapshot_id != path.name:
                            raise ValueError("snapshot identity mismatch during cleanup")
                    if add(path, category, cutoff=None if path.name in expired_snapshots else orphan_cutoff):
                        removed_snapshots.add(path.name)
                else:
                    add(path, category, cutoff=(scratch_cutoff if category == "scratch" else
                        None if path.name in removed_snapshots or path.name in expired_snapshots else orphan_cutoff))
    for category in ("reports", "measurements"):
        parent = layout.artifacts / category
        for owner in sorted(parent.iterdir()) if parent.exists() else ():
            if not re.fullmatch(r"[0-9a-f]{64}", owner.name):
                continue
            _safe(root, owner)
            for path in sorted(owner.iterdir()):
                if not re.fullmatch(r"[0-9a-f]{32}", path.name):
                    continue
                temporary_parents.append((category, path))
                if (owner.name, path.name) not in kept_ids:
                    add(path, category, cutoff=None if (owner.name, path.name) in expired_ids else orphan_cutoff)
    # Inspect only canonical bundle locations, never arbitrary nested user folders.
    for category, parent in temporary_parents:
        if parent in candidates:
            continue
        _safe(root, parent)
        for path in sorted(parent.iterdir()):
            pending = re.fullmatch(r"pending-[0-9a-f]{32}", path.name)
            measurement = category == "measurements" and re.fullmatch(
                r"measurement-[0-9a-f]{64}\.[0-9a-f]{32}\.tmp", path.name)
            if pending or measurement:
                add(path, "temporary", cutoff=scratch_cutoff)
    deletions, row_counts = [], []

    def delete(db, sql, args=(), counter=None):
        count = dbs[db].execute("SELECT count(*) " + sql, args).fetchone()[0]
        row_counts.append(count)
        if counter:
            setattr(report, counter, getattr(report, counter) + count)
        deletions.append((db, "DELETE " + sql, args))

    for record in expired:
        thread = sha256((record.owner + "\0" + record.job_id).encode()).hexdigest()
        if "checkpoints" in dbs:
            for table in ("checkpoints", "writes", "agent_progress"):
                if table in _tables(dbs["checkpoints"]):
                    delete("checkpoints", f"FROM {table} WHERE thread_id=?", (thread,), "checkpoints")
        delete("events", "FROM telemetry_attempts WHERE event_id IN (SELECT event_id FROM events WHERE job_id=?)", (record.job_id,))
        delete("events", "FROM events WHERE job_id=?", (record.job_id,), "events")
        for table in ("outbox", "execution_leases", "tool_operations", "jobs"):
            delete("jobs", f"FROM {table} WHERE job_id=?", (record.job_id,))
    cache_rows = []
    if "last_used" in {row[1] for row in dbs["cache"].execute("PRAGMA table_info(cache)")}:
        cache_rows = list(dbs["cache"].execute("SELECT digest,last_used FROM cache WHERE last_used<? ORDER BY digest",
                          (now - policy.cache_days * 86400,)))
        report.cache_entries = len(cache_rows)
        for digest, _ in cache_rows:
            deletions.append(("cache", "DELETE FROM cache WHERE digest=?", (digest,)))
    report.paths = sorted(path.relative_to(root).as_posix() for path in candidates)
    # Changes in selected files, jobs, cache entries or row counts invalidate approval.
    binding = {"root": str(root), "policy": asdict(policy), "paths": sorted(fingerprints),
               "jobs": [(record.job_id, record.updated_at) for record in expired], "cache": cache_rows,
               "counts": row_counts, "deletions": deletions}
    report.plan_id = sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
    return report, candidates, deletions, dbs
