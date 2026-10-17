# ADR-001: Recover local jobs with process-held execution locks

## Status

Accepted for the local SQLite service.

## Date

2026-10-13

## Context

Durable jobs already survive viewer disconnects and graceful service shutdown.
An abruptly killed worker leaves a running Job Store record with graph/private
checkpoints, budget reservations and tool artifacts. A paused live worker must
not race a replacement over those same checkpoints and artifacts.

## Decision

Hold a non-inherited, per-job OS file lock for the complete execution and drain
interval. Claim running status, an execution lease and its outbox event atomically
in the existing Job Store. Persist monotonic execution elapsed time in the lease
without racing the agent ledger. Startup and periodic maintenance try the same
lock before interrupting an abandoned running record. Resume stays explicit;
queued work restarts automatically. Recovery preserves intent, source identity,
checkpoints, counters, follow-up admission and unresolved model reservations.

Use nonblocking [Windows byte-range locks](https://docs.python.org/3/library/msvcrt.html#msvcrt.locking)
and [Unix flock](https://docs.python.org/3/library/fcntl.html#fcntl.flock).
Do not unlink lock files: changing the locked file identity could admit another
writer. Persisted lease metadata is execution coordination within the Job Store,
not another storage responsibility or an AI agent.

The Job Store transaction also serializes bounded final artifact publication with
cancellation from another manager. A heartbeat observes remotely persisted
cancellation and drains execution; it never restarts or refunds a cancelled job.

## Alternatives considered

- Wall-clock lease expiry alone: cannot distinguish a dead worker from a paused
  live worker that can still write checkpoints and artifacts. Rejected locally.
- Automatically restarting interrupted jobs: can repeat unknown model/tool
  operations. Rejected; explicit resume uses existing checkpoint and budget rules.
- A distributed lock backend: belongs to optional storage adapters and would add
  infrastructure to the local service. Deferred to that milestone.

## Consequences

Local filesystem locking is required; network filesystems and distributed workers
are outside this adapter's contract. Windows behavior is verified with actual
subprocess termination; the Unix implementation still needs its platform CI gate.
A live stalled worker may need explicit operator termination. Unknown crash time
is conservatively charged up to the 600-second ceiling, with an explicit report
limitation; a long outage may lead to the existing partial deadline finalization.
Source remains read-only, publication remains deterministic, and seven-agent
contracts, budgets and public REST/SSE/WebSocket schemas remain unchanged.

## Observability addendum — 2026-10-17

M8 extends event payloads with optional bounded runtime metadata. Old persisted
events remain readable; no storage schema migration or execution role is added.
Model completion and its ledger settlement commit in the same Job Store/outbox
transaction. Otherwise a crash after a visible completion but before accounting
could leave a reservation falsely classified as another unknown completion.
After a genuine crash, pending calls with recorded starts receive an `unknown`
completion alongside their conservative charge; reservations without starts do
not invent model calls. Event Store dispatch keeps the existing outbox behavior.

Full job/task/evidence/finding correlation stays in the owned local timeline.
Optional metadata export uses random invocation/call IDs and bounded runtime
classifications, excluding private identifiers and their derived fingerprints.
Local replay is the complete debugging record; external account access is optional.
This preserves the existing privacy boundary without adding a tracing service.

## Offline retention addendum - 2026-10-17

M9 adds explicit local maintenance rather than a background lifecycle service.
Scratch directories have no durable job binding, so cleanup must not run beside
snapshot capture, workers, source/evidence reads or subprocess drain. Every service
holds a shared runtime lease for its lifespan; direct job managers hold one from
start/first mutation through close/drain. Cleanup requires exclusive access to the
same `.maintenance.lock` file. SQLite rollback-journal reader/writer locks provide
portable process-held exclusion without a new dependency or storage responsibility.
Concurrent services remain supported; OS process death releases their leases.

Apply requires the exact preview plan ID, bound to the resolved runtime, policy,
selected file metadata, terminal jobs, cache entries and affected row counts.
There is no force mode or automatic deletion. The CLI checks canonical store
schemas, fixed artifact locations, manifests and resolved ancestry; it refuses
links, Windows reparse points and file hard links in targets. The local runtime
directory remains trusted and private, as required by the existing host tools.

Queued, running and interrupted jobs never expire here. Terminal jobs expire as
bundles; shared snapshots are retained until no kept job references them. Their
event outbox, replay/telemetry records, graph/private checkpoints, tool-operation
receipts, reports and measurements can then be removed. Orphans and disposable
scratch/temp data have independent ages; cache timestamps migrate with a grace
period. Unknown files and all lock files remain. Expired intent keys no longer
deduplicate future submissions.

Artifact deletion precedes database pruning, and the expired Job Store records
are committed last. This is restartable retention, not an atomic transaction
across files and four databases. A failed attempt requires a fresh preview and
retry before restarting normal use. SQLite pages are reusable after row deletion;
we deliberately avoid VACUUM and automatic startup cleanup. Disk totals are read
after store connections close so transient WAL files do not inflate final usage.
Unix locking/path behavior still needs its platform gate; Windows tests use real
process termination and junctions. Agent roles, budgets and wire schemas are unchanged.
