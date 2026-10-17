# Milestone 9 - Basic Local Storage Cleanup

Date: 2026-10-17. Scope: the attached local side-project M9, following M8.
Status: **Complete for the tested local runtime.** Stopped before milestone 10.

## Outcome and architecture

`devwatch cleanup` previews configurable local retention as JSON. Explicit apply
requires the exact inspected preview's plan ID. A changed candidate set, selected
file metadata, job/cache metadata or affected row count invalidates the plan.
There is no force flag, automatic startup deletion or maintenance daemon.

Exactly seven AI identities remain: Planner, five Specialists and the combined
Synthesizer/Verifier. Deterministic orchestration, the shared blackboard, evidence
gates, accepted report rendering and cumulative budgets retain their responsibilities.
No agent, model call, dependency, external service or transport schema was added.

Default retention is 30 days for terminal history, orphan artifacts and unused
cache entries; 24 hours for scratch and abandoned temporary files. CLI options
override the corresponding `DEVWATCH_RETENTION_*` environment values.

| Data | Retention behavior |
| --- | --- |
| Terminal reviews | Old completed/failed/cancelled bundles expire by `updated_at`; their job, outbox, execution/tool receipts, events/telemetry, graph/private checkpoints, reports and measurements are removed. |
| Recoverable reviews | Queued/running/interrupted jobs never expire here. Their snapshots, evidence, checkpoints and final artifacts stay. A shared snapshot survives any retained reference. |
| Snapshots/evidence | Unreferenced old snapshots and evidence directories expire; orphan snapshots require a valid matching manifest. Partially deleted snapshots owned by still-present expired jobs can be retried. |
| Scratch and temporary files | Old disposable copies, pending snapshots/evidence/PDFs and measurement `.tmp` files expire only in canonical runtime locations. Newest nested modification time protects recent work. |
| Repository cache | Latest successful read/write refreshes `last_used`; migration gives old entries a full grace period. Expired entries are removed independently. |
| Unknown files/locks | User directories, source checkouts, exported reports, backups and external logs are outside cleanup. Process lock files remain permanently. |

## Files and functions

| File / functions | Change |
| --- | --- |
| `devwatch/review/cleanup.py`: `RetentionPolicy`, `CleanupReport`, `cleanup_storage`, `_plan_locked` | Retention selection, exact preview/apply binding, local counts/paths/file-byte totals, restartable scoped file and SQLite pruning. |
| `cleanup.py`: `_safe`, `_tree`, `_disk_bytes` | Resolve containment, validate canonical locations, reject symlinks/Windows reparse points/hard links, check database sidecars before opening SQLite, and measure after connections close. |
| `devwatch/review/leases.py`: `runtime_lock` | Shared service/worker lifetime lease and exclusive maintenance through a tiny SQLite rollback-journal lock file; OS release on process death, without adding a logical store. |
| `devwatch/review/jobs.py`: `DurableJobManager._use_runtime`, start/submit/cancel/resume/close | Acquire shared use before work; retain exclusion until worker/subprocess drain finishes. Existing per-job execution locks still protect terminal drain. |
| `devwatch/review/service.py`: lifespan wrapper | Exclude maintenance during snapshot capture, evidence reads, worker execution, telemetry and shutdown. Concurrent readers/services remain supported. |
| `devwatch/review/stores.py`: `RepoCache.__init__`, `put`, `get` | Backward-compatible timestamp migration and last-use refresh; existing immutable identity/conflict rules remain. |
| `devwatch/cli.py`: `cleanup` | Offline JSON preview, retention overrides, runtime selection, required `--apply --plan-id` and sanitized storage failure. |
| `tests/test_m9_cleanup.py` | 49 new cases over temporary real stores, Windows junctions and real processes. |
| `README.md`, ADR-001 addendum, task plan/checklist/progress | Usage, ages, lock/recovery tradeoffs, deletion semantics and milestone evidence. |
| `output/m9-measure-cleanup.py`, `tasks/evidence/m9-storage-metrics.json` | Reproducible measurement against fresh owned temporary stores; no provider calls or user runtime deletion. |

## Tests and measurements

New cases cover preview preservation/stability, stale/missing plan IDs, all kept
statuses, shared snapshots, expiry boundaries, recent nested content, unknown files,
all temporary filename formats, old cache migration/access, sidecar links before
SQLite opens, junctions/hard links, malformed identities, failed/partial deletion
and retry, CLI/environment options, many terminal reviews, concurrent services,
manager exclusion, process death, and a real interrupted graph resuming synthesis
after unrelated expired history is cleaned.

Red evidence is retained for missing functionality, service/manager lease wiring,
exact apply, CLI behavior, unknown-folder/temp-file boundaries and SQLite sidecar
validation. The metrics regression exposed transient WAL inflation; final totals
are measured after closing database connections.

| Verification | Result |
| --- | --- |
| Preview/path/process safety stage | 26 passed in 2.08s; apply intentionally unavailable at that stage. |
| Final new-case boundary run | 49 passed in 12.22s. |
| Final cleanup + durable jobs/stores/CLI/service/recovery/PDF gate | 100 passed in 66.86s. |
| Full backend regression | **351 passed in 607.28s**, including all 49 new cases; one existing upstream LangSmith wrapper deprecation warning. See `tasks/evidence/m9-backend.txt`. |
| Generated review contracts | `scripts/export_review_contracts.py --check` passed. |
| Python compilation | `compileall -q devwatch/review devwatch/cli.py` passed. |
| Diff whitespace check | Passed; Git reports existing LF-to-CRLF normalization notices. |

The isolated measurement runs three cycles of 20 completed fixture reviews. Each
cycle removes 20 snapshots, scratch directories, evidence directories, reports,
private checkpoints and cache entries, plus 60 events. Each cycle selects 1,322,680
artifact bytes. Total file sizes return from **1,769,144 to 315,392 bytes** each time;
the four SQLite files stay at **307,200 bytes** across all three cycles. This is
logical file size, excluding filesystem allocation/directory overhead. SQLite
reuses freed pages without VACUUM. A separate 600-terminal-review case also passes.
These are fixture measurements, not a live-model cost, accuracy or capacity claim.

## Review and practical limits

Correctness/security review fixed overly broad temporary-file scanning and moved
sidecar validation ahead of every SQLite open. Review also checked shared snapshot
protection, interrupted graph continuity, terminal drain, partial deletion ordering,
SQL parameterization, cache migration and bounded open execution-lock handles.
No unresolved critical finding remains in the tested cooperative local runtime.

Cleanup is offline and explicitly invoked between sessions. All writers must use
the updated lifetime lease; direct unsynchronized store mutation and malicious
processes able to replace private runtime paths are outside this guarantee. Only
Windows/Python 3.11 was executed here; Unix needs its own platform gate. No frontend
files or wire contracts changed, so browser/build checks were not repeated.

Artifact deletion and four database commits are restartable, not atomic together.
On failure, inspect a fresh preview and finish before restarting normal use. An
expired job may temporarily remain while its artifacts are already gone. Expired
intent keys can create new reviews if reused. Interrupted jobs, recent history and
permanent lock-file metadata can accumulate; this is not a hard disk quota or secure
erasure of SQLite free pages. Corrupt orphan manifests require manual investigation.

No cleanup was run against the user's existing runtime. All deletions exercised
fresh temporary stores; no commit, push, deployment, telemetry export or paid call.

## Automatic approval review

The first proposed deletion/VACUUM patch was rejected because broad irreversible
cleanup had unverified path and concurrency safety. That patch did not apply.
The accepted alternative first proved preview/path/locking behavior, then added
only exact-preview explicit apply, without startup deletion or VACUUM. No approval
block remains for the delivered implementation.
