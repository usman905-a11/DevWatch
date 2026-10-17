"""Durable job ownership and transactional outbox, separate from graph checkpoints.

No client connection owns an execution task. Transport handlers may submit, replay,
poll or explicitly cancel; cancelling a polling coroutine has no job side effect.
"""

import asyncio
from contextlib import closing, contextmanager
from hashlib import sha256
import json
import logging
import math
from pathlib import Path
import sqlite3
import time
from typing import Any, Awaitable, Callable, Literal, get_args
from uuid import uuid4

from pydantic import Field

from devwatch.review.budgets import BudgetLedger
from devwatch.review.contracts import AgentId, BalancedLimits, ContractModel, FollowupRequest
from devwatch.review.leases import execution_lock

_LOG = logging.getLogger(__name__)


class JobConflict(ValueError):
    pass


class UnknownToolCompletion(PermissionError):
    """A previously admitted effect has no known result; it must not be replayed."""


class JobNotFound(LookupError):
    """Missing and inaccessible jobs deliberately have the same public error."""


MAX_EVENT_CURSOR = 2**63 - 1


JobStatus = Literal["queued", "running", "interrupted", "completed", "failed", "cancelled"]
EventKind = Literal[
    "job_queued", "job_running", "job_interrupted", "job_completed", "job_failed", "job_cancelled",
    "agent_started", "agent_status_changed", "reasoning_step", "tool_called", "tool_result",
    "file_opened", "search_performed", "finding_created", "validation_passed", "validation_failed",
    "retry_started", "error_occurred", "agent_completed", "budget_updated",
    "iteration_started", "model_call_started", "model_call_completed", "agent_reused",
    "evidence_retrieved", "evidence_delivered", "evidence_inspected", "candidate_submitted",
    "candidate_rejected", "verification_completed", "finalization_started", "finalization_completed",
    "report_render_started", "report_render_completed",
]

StopReason = Literal["evidence_complete", "finished_without_result", "invalid_schema", "model_unavailable",
    "tools_unavailable", "unknown_tool_completion", "permission_denied", "budget_exhausted",
    "prompt_context_limit", "context_timeout", "tool_timeout", "provider_truncated", "provider_incomplete",
    "cancelled", "specialist_failed", "execution_failed", "review_time_exhausted", "final_consistency_failure", "other"]


def safe_stop_reason(value):
    # Specialist stop text is model output; never copy arbitrary prose to telemetry.
    return value if value in get_args(StopReason) else "other"


class EventPayload(ContractModel):
    # Raw arguments/output/source/errors are not accepted by this metadata stream.
    # Owner-authorized evidence access supplies separately redacted tool artifacts.
    status: JobStatus | None = None
    agent_id: AgentId | None = None
    task_id: str | None = Field(default=None, max_length=128, pattern=r"^[\w.-]+$")
    tool: str | None = Field(default=None, max_length=64, pattern=r"^[a-z][a-z_]*$")
    evidence_ref: str | None = Field(default=None, max_length=128, pattern=r"^[\w.-]+$")
    error_code: Literal["execution_failed", "review_time_exhausted", "provider_authentication", "provider_quota",
        "provider_rate_limit", "provider_temporary", "provider_timeout", "provider_failure", "invalid_schema",
        "recoverable_tool_error", "permission_denied", "unknown_tool_completion", "specialist_failed"] | None = None
    duration_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    total_tokens: int | None = Field(default=None, ge=0)
    phase: Literal["planning", "investigation", "verification", "synthesis", "structural_gate",
                   "acceptance", "rendering", "finalization"] | None = None
    iteration: int | None = Field(default=None, ge=0)
    attempt: int | None = Field(default=None, ge=1)
    run_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    operation_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    outcome: Literal["succeeded", "failed", "cancelled", "unknown"] | None = None
    stop_reason: StopReason | None = None
    finish_reason: Literal["stop", "length", "content_filter", "other"] | None = None
    count: int | None = Field(default=None, ge=0)
    finding_id: str | None = Field(default=None, max_length=128, pattern=r"^[\w.-]+$")
    verdict: Literal["confirmed", "uncertain", "rejected", "advisory"] | None = None
    offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)


class PersistedEvent(ContractModel):
    event_id: str
    job_id: str
    sequence: int = Field(ge=1)
    kind: EventKind
    payload: EventPayload
    timestamp: float


class JobRecord(ContractModel):
    job_id: str
    owner: str
    request: dict[str, Any]
    status: JobStatus
    workflow_version: str = "seven-agent-v1"
    ledger: BudgetLedger = Field(default_factory=BudgetLedger)
    limits: BalancedLimits = Field(default_factory=BalancedLimits)
    result: dict[str, Any] | None = None
    followup_admission: FollowupRequest | None = None
    followup_completed: bool = False
    crash_recoveries: int = Field(default=0, ge=0)
    created_at: float
    updated_at: float


class JobView(ContractModel):
    """Owned transport view: no principal, raw source, private state or API keys."""
    job_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    snapshot_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    status: JobStatus
    workflow_version: Literal["seven-agent-v1"]
    ledger: BudgetLedger
    limits: BalancedLimits
    created_at: float = Field(ge=0, allow_inf_nan=False)
    updated_at: float = Field(ge=0, allow_inf_nan=False)


_TRANSITIONS = {
    "queued": {"running", "cancelled"},
    "running": {"completed", "failed", "cancelled", "interrupted"},
    "interrupted": {"queued", "cancelled"},
    "completed": set(), "failed": set(), "cancelled": set(),
}


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class _SQLiteStore:
    def __init__(self, path: Path | str, schema: str):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(schema)

    @contextmanager
    def _transaction(self):
        # One connection per operation allows safe use from worker threads.
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
            with db:
                yield db


class JobStore(_SQLiteStore):
    def __init__(self, path: Path | str):
        super().__init__(path, """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY, owner TEXT NOT NULL, intent_key TEXT NOT NULL,
                request_hash TEXT NOT NULL, record TEXT NOT NULL,
                UNIQUE(owner, intent_key)
            );
            CREATE TABLE IF NOT EXISTS outbox (
                event_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                event TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0,
                UNIQUE(job_id, sequence)
            );
            CREATE INDEX IF NOT EXISTS pending_outbox ON outbox(delivered, job_id, sequence);
            CREATE TABLE IF NOT EXISTS execution_leases (
                job_id TEXT PRIMARY KEY, execution_id TEXT NOT NULL,
                started_at REAL NOT NULL, initial_elapsed REAL NOT NULL,
                elapsed_seconds REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS jobs_active_status ON jobs(json_extract(record,'$.status'));
            CREATE INDEX IF NOT EXISTS jobs_active_identity ON jobs(json_extract(record,'$.status'),job_id);
            CREATE TABLE IF NOT EXISTS tool_operations (
                operation_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, task_id TEXT NOT NULL,
                command_id TEXT NOT NULL, input_hash TEXT NOT NULL, evidence_ref TEXT
            );
            CREATE INDEX IF NOT EXISTS tool_operation_scope ON tool_operations(job_id,task_id,command_id);
        """)

    def _get(self, db, job_id: str, owner: str) -> JobRecord:
        row = db.execute("SELECT record FROM jobs WHERE job_id=? AND owner=?", (job_id, owner)).fetchone()
        if row is None:
            raise JobNotFound("job not found")
        return JobRecord.model_validate_json(row["record"])

    def _save(self, db, record: JobRecord) -> None:
        record.updated_at = time.time()
        db.execute("UPDATE jobs SET record=? WHERE job_id=? AND owner=?",
                   (record.model_dump_json(), record.job_id, record.owner))

    def _enqueue_event(self, db, job_id: str, kind: EventKind, payload: EventPayload) -> PersistedEvent:
        sequence = db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM outbox WHERE job_id=?", (job_id,)).fetchone()[0]
        event = PersistedEvent(event_id=uuid4().hex, job_id=job_id, sequence=sequence,
                               kind=kind, payload=payload, timestamp=time.time())
        db.execute("INSERT INTO outbox(event_id,job_id,sequence,event) VALUES(?,?,?,?)",
                   (event.event_id, job_id, sequence, event.model_dump_json()))
        return event

    def submit(self, *, owner: str, request: dict[str, Any], idempotency_key: str,
               limits: BalancedLimits | None = None) -> JobRecord:
        if not owner or not idempotency_key or len(owner) > 256 or len(idempotency_key) > 256:
            raise ValueError("bounded owner and idempotency key are required")
        effective_limits = limits or BalancedLimits()
        request_json = _json({"request": request, "limits": effective_limits.model_dump(mode="json")})
        if len(request_json.encode("utf-8")) > 256_000:
            raise ValueError("job request too large; source content belongs in the Artifact Store")
        request_hash = sha256(request_json.encode()).hexdigest()
        with self._transaction() as db:
            previous = db.execute("SELECT request_hash,record FROM jobs WHERE owner=? AND intent_key=?",
                                  (owner, idempotency_key)).fetchone()
            if previous is not None:
                if previous["request_hash"] != request_hash:
                    raise JobConflict("idempotency key reused for a different request")
                return JobRecord.model_validate_json(previous["record"])
            now = time.time()
            record = JobRecord(job_id=uuid4().hex, owner=owner, request=request, status="queued",
                               limits=effective_limits, created_at=now, updated_at=now)
            db.execute("INSERT INTO jobs(job_id,owner,intent_key,request_hash,record) VALUES(?,?,?,?,?)",
                       (record.job_id, owner, idempotency_key, request_hash, record.model_dump_json()))
            self._enqueue_event(db, record.job_id, "job_queued", EventPayload(status="queued"))
            return record

    def get(self, job_id: str, *, owner: str) -> JobRecord:
        with self._transaction() as db:
            return self._get(db, job_id, owner)

    def transition(self, job_id: str, *, owner: str, expected_status: JobStatus,
                   status: JobStatus, result: dict[str, Any] | None = None) -> JobRecord:
        with self._transaction() as db:
            record = self._get(db, job_id, owner)
            if record.status != expected_status or status not in _TRANSITIONS[record.status]:
                raise JobConflict("job transition is no longer valid")
            record.status = status
            if result is not None:
                record.result = result
            self._save(db, record)
            self._enqueue_event(db, job_id, f"job_{status}", EventPayload(status=status))
            return record

    def queued(self, *, limit: int = 100) -> list[JobRecord]:
        # Internal worker API. Public lookup always requires an owner.
        if not 1 <= limit <= 100:
            raise ValueError("job batch limit must be between 1 and 100")
        with self._transaction() as db:
            return [JobRecord.model_validate_json(row[0]) for row in db.execute(
                "SELECT record FROM jobs WHERE json_extract(record,'$.status')='queued' ORDER BY rowid LIMIT ?", (limit,))]

    def running(self, *, after: str = "", limit: int = 100) -> list[JobRecord]:
        if not 1 <= limit <= 100:
            raise ValueError("job batch limit must be between 1 and 100")
        with self._transaction() as db:
            return [JobRecord.model_validate_json(row[0]) for row in db.execute(
                "SELECT record FROM jobs WHERE json_extract(record,'$.status')='running' AND job_id>? "
                "ORDER BY job_id LIMIT ?", (after, limit))]

    def claim(self, job_id: str, *, owner: str, execution_id: str) -> JobRecord:
        """Internal worker call; caller holds execution_lock through drain."""
        with self._transaction() as db:
            record = self._get(db, job_id, owner)
            if record.status != "queued":
                raise JobConflict("job is no longer queued")
            elapsed = record.ledger.elapsed_seconds
            db.execute("INSERT OR REPLACE INTO execution_leases VALUES(?,?,?,?,?)",
                       (job_id, execution_id, time.time(), elapsed, elapsed))
            record.status = "running"
            self._save(db, record)
            self._enqueue_event(db, job_id, "job_running", EventPayload(status="running"))
            return record

    def heartbeat(self, job_id: str, *, owner: str, execution_id: str, run_seconds: float) -> bool:
        if not math.isfinite(run_seconds) or run_seconds < 0:
            raise ValueError("elapsed time must be finite and nonnegative")
        with self._transaction() as db:
            record = self._get(db, job_id, owner)
            if record.status != "running":
                return False
            changed = db.execute("UPDATE execution_leases SET elapsed_seconds=MAX(elapsed_seconds,initial_elapsed+?) "
                                 "WHERE job_id=? AND execution_id=?", (run_seconds, job_id, execution_id))
            if changed.rowcount != 1:
                raise JobConflict("execution lease no longer belongs to this worker")
            return True

    def recover_abandoned(self, job_id: str, *, owner: str) -> None:
        """Caller has acquired the dead worker's process lock; never auto-resume."""
        with self._transaction() as db:
            record = self._get(db, job_id, owner)
            if record.status != "running":
                return
            lease = db.execute("SELECT * FROM execution_leases WHERE job_id=?", (job_id,)).fetchone()
            estimate = record.limits.review_seconds if lease is None else max(
                lease["elapsed_seconds"], lease["initial_elapsed"] + max(0, time.time() - lease["started_at"]))
            record.ledger.elapsed_seconds = max(record.ledger.elapsed_seconds, min(record.limits.review_seconds, estimate))
            record.crash_recoveries += 1
            record.status = "interrupted"
            self._save(db, record)
            db.execute("DELETE FROM execution_leases WHERE job_id=?", (job_id,))
            self._enqueue_event(db, job_id, "job_interrupted", EventPayload(status="interrupted"))

    def release_execution(self, job_id: str, execution_id: str) -> None:
        with self._transaction() as db:
            db.execute("DELETE FROM execution_leases WHERE job_id=? AND execution_id=?", (job_id, execution_id))

    @contextmanager
    def publication(self, job_id: str, *, owner: str):
        """Serialize bounded artifact publication with remote cancellation."""
        with self._transaction() as db:
            if self._get(db, job_id, owner).status != "running":
                raise asyncio.CancelledError
            yield

    def admit_tool_operation(self, job_id, *, owner, task_id, command_id, input_hash):
        with self._transaction() as db:
            if self._get(db, job_id, owner).status != "running":
                raise asyncio.CancelledError
            previous = db.execute("SELECT input_hash,evidence_ref FROM tool_operations WHERE job_id=? AND task_id=? AND command_id=?",
                                  (job_id, task_id, command_id)).fetchall()
            if any(row["evidence_ref"] is None for row in previous):
                raise UnknownToolCompletion("Command completion is unknown; automatic replay is forbidden")
            known = next((row["evidence_ref"] for row in previous if row["input_hash"] == input_hash), None)
            if known:
                return None, known
            operation_id = uuid4().hex
            db.execute("INSERT INTO tool_operations VALUES(?,?,?,?,?,NULL)",
                       (operation_id, job_id, task_id, command_id, input_hash))
            return operation_id, None

    def complete_tool_operation(self, job_id, *, owner, operation_id, evidence_ref):
        with self._transaction() as db:
            self._get(db, job_id, owner)
            changed = db.execute("UPDATE tool_operations SET evidence_ref=? WHERE job_id=? AND operation_id=? AND evidence_ref IS NULL",
                                 (evidence_ref, job_id, operation_id))
            if changed.rowcount != 1:
                raise JobConflict("Tool operation is not pending")

    def owns_tool_evidence(self, job_id, *, owner, task_id, evidence_ref):
        with self._transaction() as db:
            self._get(db, job_id, owner)
            return db.execute("SELECT 1 FROM tool_operations WHERE job_id=? AND task_id=? AND evidence_ref=?",
                              (job_id, task_id, evidence_ref)).fetchone() is not None

    def update_ledger(self, job_id: str, *, owner: str, ledger: dict[str, Any] | BudgetLedger,
                      followup: FollowupRequest | None = None, model_completions=()) -> None:
        updated = BudgetLedger.model_validate(ledger)
        model_completions = [EventPayload.model_validate(payload) for payload in model_completions]
        if len({payload.operation_id for payload in model_completions}) != len(model_completions):
            raise JobConflict("duplicate model completion")
        with self._transaction() as db:
            record = self._get(db, job_id, owner)
            previous = record.ledger
            for payload in model_completions:
                reservation = previous.inflight.get(payload.operation_id)
                if (reservation is None or payload.operation_id in updated.inflight or payload.outcome is None
                        or payload.agent_id != reservation.agent_id or payload.total_tokens is None
                        or (payload.outcome == "unknown" and payload.total_tokens != reservation.tokens)):
                    raise JobConflict("model completion must settle a known reservation")
            for field in ("task_iterations", "task_tools", "task_schema_repairs", "operation_retries"):
                if any(getattr(updated, field).get(key, 0) < count for key, count in getattr(previous, field).items()):
                    raise JobConflict("cumulative budget counters cannot decrease")
            for agent, usage in previous.agent_usage.items():
                new_usage = updated.agent_usage.get(agent)
                if (new_usage is None or new_usage.prompt_tokens < usage.prompt_tokens
                        or new_usage.completion_tokens < usage.completion_tokens):
                    raise JobConflict("cumulative token usage cannot decrease")
            if updated.elapsed_seconds < previous.elapsed_seconds:
                raise JobConflict("cumulative elapsed time cannot decrease")
            if updated.review_round < previous.review_round:
                raise JobConflict("review round admission cannot decrease")
            if followup is not None:
                if updated.review_round != 2:
                    raise JobConflict("follow-up admission requires round two")
                if record.followup_admission is not None and record.followup_admission != followup:
                    raise JobConflict("a different follow-up was already admitted")
                record.followup_admission = followup.model_copy(deep=True)
            record.ledger = updated
            self._save(db, record)
            for payload in model_completions:
                self._enqueue_event(db, job_id, "model_call_completed", payload)
            if (updated.total_tokens != previous.total_tokens or updated.task_tools != previous.task_tools
                    or updated.review_round != previous.review_round):
                self._enqueue_event(db, job_id, "budget_updated", EventPayload(
                    total_tokens=updated.total_tokens, duration_seconds=updated.elapsed_seconds))

    def complete_followup(self, job_id: str, *, owner: str) -> None:
        with self._transaction() as db:
            record = self._get(db, job_id, owner)
            if record.followup_admission is None or record.ledger.review_round != 2:
                raise JobConflict("no follow-up is admitted")
            record.followup_completed = True
            self._save(db, record)

    def account_execution_time(self, job_id: str, *, owner: str, initial_elapsed: float, run_seconds: float) -> None:
        if any(not math.isfinite(value) or value < 0 for value in (initial_elapsed, run_seconds)):
            raise ValueError("elapsed time cannot decrease")
        with self._transaction() as db:
            record = self._get(db, job_id, owner)
            record.ledger.elapsed_seconds = max(record.ledger.elapsed_seconds, initial_elapsed + run_seconds)
            self._save(db, record)

    def emit(self, job_id: str, *, owner: str, kind: EventKind, payload: dict[str, Any]) -> PersistedEvent:
        parsed = EventPayload.model_validate(payload)
        with self._transaction() as db:
            self._get(db, job_id, owner)
            return self._enqueue_event(db, job_id, kind, parsed)

    def pending_events(self, limit: int = 1000) -> list[PersistedEvent]:
        if not 1 <= limit <= 1000:
            raise ValueError("event batch limit must be between 1 and 1000")
        with self._transaction() as db:
            return [PersistedEvent.model_validate_json(row[0]) for row in db.execute(
                "SELECT event FROM outbox WHERE delivered=0 ORDER BY rowid LIMIT ?", (limit,))]

    def dispatch_events(self, target: "EventStore") -> int:
        if target.path == self.path:
            raise ValueError("Job Store and Event Store must be separate")
        delivered = 0
        for event in self.pending_events():
            target.append(event)
            with self._transaction() as db:
                db.execute("UPDATE outbox SET delivered=1 WHERE event_id=?", (event.event_id,))
            delivered += 1
        return delivered


class EventStore(_SQLiteStore):
    def __init__(self, path: Path | str):
        super().__init__(path, """
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY, job_id TEXT NOT NULL,
                sequence INTEGER NOT NULL, event TEXT NOT NULL, UNIQUE(job_id,sequence)
            );
            CREATE TABLE IF NOT EXISTS telemetry_attempts (event_id TEXT PRIMARY KEY, outcome TEXT NOT NULL);
        """)

    def append(self, event: PersistedEvent) -> None:
        with self._transaction() as db:
            previous = db.execute("SELECT event FROM events WHERE event_id=? OR (job_id=? AND sequence=?)",
                                  (event.event_id, event.job_id, event.sequence)).fetchone()
            if previous is not None:
                if previous[0] != event.model_dump_json():
                    raise JobConflict("event identity reused with a different payload")
                return
            db.execute("INSERT INTO events(event_id,job_id,sequence,event) VALUES(?,?,?,?)",
                       (event.event_id, event.job_id, event.sequence, event.model_dump_json()))

    def replay(self, job_id: str, *, after: int = 0, limit: int = 1000) -> list[PersistedEvent]:
        # Internal store API: a transport must check JobStore.get(owner=...) first.
        if type(after) is not int or not 0 <= after <= MAX_EVENT_CURSOR or not 1 <= limit <= 1000:
            raise ValueError("invalid replay cursor or page size")
        with self._transaction() as db:
            return [PersistedEvent.model_validate_json(row[0]) for row in db.execute(
                "SELECT event FROM events WHERE job_id=? AND sequence>? ORDER BY sequence LIMIT ?",
                (job_id, after, limit))]

    def admit_telemetry(self, *, limit: int = 20) -> list[PersistedEvent]:
        """At-most-once optional export; unknown sends never replay review effects."""
        if not 1 <= limit <= 100:
            raise ValueError("invalid telemetry batch")
        with self._transaction() as db:
            rows = list(db.execute("SELECT event FROM events WHERE event_id NOT IN "
                "(SELECT event_id FROM telemetry_attempts) ORDER BY rowid LIMIT ?", (limit,)))
            events = [PersistedEvent.model_validate_json(row[0]) for row in rows]
            db.executemany("INSERT INTO telemetry_attempts VALUES(?, 'unknown')", [(event.event_id,) for event in events])
            return events

    def complete_telemetry(self, event_id: str, outcome: str) -> None:
        if outcome not in {"sent", "failed"}:
            raise ValueError("invalid telemetry outcome")
        with self._transaction() as db:
            db.execute("UPDATE telemetry_attempts SET outcome=? WHERE event_id=?", (outcome, event_id))


class DurableJobManager:
    def __init__(self, store: JobStore, events: EventStore,
                 execute: Callable[[JobRecord], Awaitable[dict[str, Any]]], *, concurrent_jobs: int = 1,
                 recover_timeout: Callable[[JobRecord], Awaitable[dict[str, Any]]] | None = None):
        if store.path == events.path:
            raise ValueError("Job Store and Event Store must be separate")
        if concurrent_jobs < 1:
            raise ValueError("at least one job worker is required")
        self.store, self.events, self.execute = store, events, execute
        self.recover_timeout = recover_timeout
        self._slots = asyncio.Semaphore(concurrent_jobs)
        self._capacity = concurrent_jobs
        self._tasks: dict[str, asyncio.Task] = {}
        self._maintenance: asyncio.Task | None = None
        self._maintenance_id = uuid4().hex
        self._recovery_cursor = ""
        self._closed = False

    def _schedule(self, job: JobRecord) -> None:
        self._ensure_maintenance()
        self._tasks = {identity: task for identity, task in self._tasks.items() if not task.done()}
        if job.job_id not in self._tasks and len(self._tasks) < self._capacity:
            self._tasks[job.job_id] = asyncio.create_task(self._run(job), name=f"review-{job.job_id}")

    def _ensure_maintenance(self) -> None:
        if self._maintenance is None or self._maintenance.done():
            if self._maintenance is not None and not self._maintenance.cancelled():
                self._maintenance.exception()  # Retrieve any prior failure before supervising its replacement.
            self._maintenance = asyncio.create_task(self._maintain(), name="review-job-recovery")

    def _scan(self) -> None:
        running = self.store.running(after=self._recovery_cursor)
        self._recovery_cursor = running[-1].job_id if len(running) == 100 else ""
        for job in running:
            with execution_lock(self.store.path, job.job_id) as acquired:
                if acquired:
                    self.store.recover_abandoned(job.job_id, owner=job.owner)
        self.store.dispatch_events(self.events)
        self._tasks = {identity: task for identity, task in self._tasks.items() if not task.done()}
        available = self._capacity - len(self._tasks)
        if available:
            for job in self.store.queued(limit=min(available, 100)):
                self._schedule(job)

    async def _maintain(self) -> None:
        delay = .25
        while not self._closed:
            await asyncio.sleep(delay)
            try:
                self._scan()
            except Exception as error:
                # Administrative scans/delivery are idempotent. Keep recovery
                # alive with capped backoff; never log payloads or error text.
                _LOG.warning(json.dumps({"event": "job_maintenance_failed", "entry_point": "job_maintenance",
                    "run_id": self._maintenance_id, "error_type": type(error).__name__, "retry_seconds": delay}))
                delay = min(1., delay * 2)
            else:
                delay = .25

    async def _heartbeat(self, job, execution_id, started, worker) -> None:
        try:
            while True:
                await asyncio.sleep(.25)
                if not self.store.heartbeat(job.job_id, owner=job.owner, execution_id=execution_id,
                                             run_seconds=time.monotonic() - started):
                    worker.cancel()
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            # Losing durable lease accounting must stop execution, not let a
            # worker keep making effects without a valid execution claim.
            worker.cancel()

    async def start(self) -> None:
        if self._closed:
            raise RuntimeError("job manager is closed")
        self._scan()
        self._ensure_maintenance()

    async def submit(self, *, owner: str, request: dict[str, Any], idempotency_key: str,
                     limits: BalancedLimits | None = None) -> JobRecord:
        if self._closed:
            raise RuntimeError("job manager is closed")
        job = self.store.submit(owner=owner, request=request, idempotency_key=idempotency_key, limits=limits)
        self.store.dispatch_events(self.events)
        if job.status == "queued":
            self._schedule(job)
        return job

    async def _run(self, original: JobRecord) -> None:
        started = None
        claimed = False
        deadline_expired = False
        initial_elapsed = original.ledger.elapsed_seconds
        lease_lock = None
        heartbeat = None
        execution_id = uuid4().hex
        try:
            async with self._slots:
                lease_lock = execution_lock(self.store.path, original.job_id)
                if not lease_lock.__enter__():
                    return
                try:
                    job = self.store.claim(original.job_id, owner=original.owner, execution_id=execution_id)
                    claimed = True
                except JobConflict:
                    return
                self.store.dispatch_events(self.events)
                started = time.monotonic()
                heartbeat = asyncio.create_task(self._heartbeat(job, execution_id, started, asyncio.current_task()))
                initial_elapsed = job.ledger.elapsed_seconds
                remaining = job.limits.review_seconds - job.ledger.elapsed_seconds
                deadline = None
                try:
                    if remaining <= 0:
                        deadline_expired = True
                        raise TimeoutError("review time exhausted")
                    async with asyncio.timeout(remaining) as deadline:
                        result = await self.execute(job)
                except TimeoutError:
                    deadline_expired = deadline_expired or (deadline is not None and deadline.expired())
                    if not deadline_expired:
                        raise
                    # The timeout context has drained execution and child work.
                    self.store.account_execution_time(job.job_id, owner=job.owner,
                        initial_elapsed=initial_elapsed, run_seconds=time.monotonic() - started)
                    current = self.store.get(job.job_id, owner=job.owner)
                    # Clock granularity cannot make a fired deadline unexhausted.
                    current.ledger.elapsed_seconds = max(current.ledger.elapsed_seconds, current.limits.review_seconds)
                    self.store.update_ledger(job.job_id, owner=job.owner, ledger=current.ledger)
                    if self.recover_timeout is None:
                        raise
                    self.store.emit(job.job_id, owner=job.owner, kind="error_occurred",
                                    payload={"error_code": "review_time_exhausted"})
                    # Administrative finalization only: no new investigation,
                    # model/tool calls or extension of the cumulative budget.
                    result = await asyncio.wait_for(self.recover_timeout(current), timeout=5)
                self.store.transition(job.job_id, owner=job.owner, expected_status="running",
                                      status="completed", result=result)
        except asyncio.CancelledError:
            current = self.store.get(original.job_id, owner=original.owner)
            if claimed and current.status == "running":
                self.store.transition(current.job_id, owner=current.owner,
                                      expected_status="running", status="interrupted")
            raise
        except Exception as exc:
            current = self.store.get(original.job_id, owner=original.owner)
            if claimed and current.status == "running":
                code = "review_time_exhausted" if deadline_expired else "execution_failed"
                self.store.emit(current.job_id, owner=current.owner, kind="error_occurred", payload={"error_code": code})
                self.store.transition(current.job_id, owner=current.owner, expected_status="running", status="failed")
        finally:
            try:
                # Flush the terminal outbox before yielding to heartbeat drain;
                # polling a completed job must already have its replay event.
                self.store.dispatch_events(self.events)
                if heartbeat is not None:
                    heartbeat.cancel()
                    await asyncio.gather(heartbeat, return_exceptions=True)
                if started is not None:
                    self.store.account_execution_time(original.job_id, owner=original.owner,
                                                      initial_elapsed=initial_elapsed, run_seconds=time.monotonic() - started)
                    self.store.release_execution(original.job_id, execution_id)
                self.store.dispatch_events(self.events)
            finally:
                if lease_lock is not None:
                    lease_lock.__exit__(None, None, None)

    async def wait(self, job_id: str, *, owner: str) -> JobRecord:
        while True:
            job = self.store.get(job_id, owner=owner)
            if job.status not in {"queued", "running"}:
                return job
            await asyncio.sleep(0.01)

    async def cancel(self, job_id: str, *, owner: str) -> JobRecord:
        job = self.store.get(job_id, owner=owner)
        if job.status in {"queued", "running", "interrupted"}:
            try:
                job = self.store.transition(job_id, owner=owner, expected_status=job.status, status="cancelled")
            except JobConflict:
                return self.store.get(job_id, owner=owner)
            task = self._tasks.get(job_id)
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            self.store.dispatch_events(self.events)
        return job

    async def resume(self, job_id: str, *, owner: str) -> JobRecord:
        if self._closed:
            raise RuntimeError("job manager is closed")
        job = self.store.transition(job_id, owner=owner, expected_status="interrupted", status="queued")
        self.store.dispatch_events(self.events)
        self._schedule(job)
        return job

    async def close(self) -> None:
        self._closed = True
        if self._maintenance is not None:
            self._maintenance.cancel()
            await asyncio.gather(self._maintenance, return_exceptions=True)
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
