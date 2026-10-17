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
