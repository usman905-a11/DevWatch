"""Durable job store and live trajectory event streaming, separate from graph checkpoints.

No client connection owns an execution task. Transport handlers may submit, replay,
stream or explicitly cancel; disconnecting a stream has no job side effect.
"""

import asyncio
from contextlib import asynccontextmanager, closing, contextmanager
from contextvars import ContextVar
from enum import Enum
from hashlib import sha256
import inspect
import json
import logging
import math
import os
from pathlib import Path
import re
import sqlite3
from threading import Lock
import time
from typing import Any, Awaitable, Callable, Literal, get_args
from uuid import uuid4

from pydantic import Field

from backend.review.budgets import BudgetLedger
from backend.review.contracts import AgentId, BalancedLimits, ContractModel, FollowupRequest, StopReason

_LOG = logging.getLogger(__name__)


class JobConflict(ValueError):
    pass


class UnknownToolCompletion(PermissionError):
    """A previously admitted effect has no known result; it must not be replayed."""


class JobNotFound(LookupError):
    """Missing and inaccessible jobs deliberately have the same public error."""


MAX_EVENT_CURSOR = 2**63 - 1


JobStatus = Literal["queued", "running", "interrupted", "completed", "failed", "cancelled"]
StepType = Literal[
    "agent_run",
    "subagent",
    "planner",
    "run_command",
    "code_search",
    "repo_map",
    "search",
    "read_file",
    "tool",
    "system",
]
StepStatus = Literal["RUNNING", "DONE", "ERROR", "CANCELING"]


def safe_stop_reason(value):
    # Specialist stop text is model output; never copy arbitrary prose to telemetry.
    return value if value in get_args(StopReason) else "other"


def observed_node(name: str, fn: Callable[..., Any], emit: Callable[..., Any], *, scope: str = "review"):
    """Wrap a LangGraph node (sync or async) to emit bounded graph_node_started/completed events."""

    async def _emit_async(kind: str, state: Any, **payload: Any) -> None:
        res = emit(kind, state, **payload)
        if inspect.isawaitable(res):
            await res

    async def _async_node(state):
        operation_id = uuid4().hex
        await _emit_async("graph_node_started", state, node=name, graph_scope=scope, operation_id=operation_id)
        try:
            result = await fn(state)
        except asyncio.CancelledError:
            await _emit_async("graph_node_completed", state, node=name, graph_scope=scope, operation_id=operation_id, outcome="cancelled")
            raise
        except Exception:
            await _emit_async("graph_node_completed", state, node=name, graph_scope=scope, operation_id=operation_id, outcome="failed")
            raise
        await _emit_async("graph_node_completed", state, node=name, graph_scope=scope, operation_id=operation_id, outcome="succeeded")
        return result

    def _sync_node(state):
        operation_id = uuid4().hex
        emit("graph_node_started", state, node=name, graph_scope=scope, operation_id=operation_id)
        try:
            result = fn(state)
        except Exception:
            emit("graph_node_completed", state, node=name, graph_scope=scope, operation_id=operation_id, outcome="failed")
            raise
        emit("graph_node_completed", state, node=name, graph_scope=scope, operation_id=operation_id, outcome="succeeded")
        return result

    return _async_node if inspect.iscoroutinefunction(fn) else _sync_node


class _DictAccessModel(ContractModel):
    def __getitem__(self, key: str) -> Any:
        if key in type(self).model_fields:
            return getattr(self, key)
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        if key in type(self).model_fields:
            value = getattr(self, key)
            return default if value is None else value
        return default

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in type(self).model_fields and getattr(self, key) is not None

    def keys(self):
        return self.model_dump(exclude_none=True).keys()

    def items(self):
        return self.model_dump(exclude_none=True).items()

    def values(self):
        return self.model_dump(exclude_none=True).values()


class StepRenderInfo(_DictAccessModel):
    title: str | None = Field(default=None, max_length=512)
    subtitle: str | None = Field(default=None, max_length=512)
    agent_name: str | None = Field(default=None, max_length=128)
    command: str | None = Field(default=None, max_length=1024)
    args_preview: dict[str, str | int | float | bool | None] | None = None
    stdout_append: str | None = Field(default=None, max_length=65536)
    stderr_append: str | None = Field(default=None, max_length=65536)
    exit_code: int | None = None
    truncated: bool | None = None
    output_truncated: bool | None = None
    query: str | None = Field(default=None, max_length=512)
    files: list[str] | None = Field(default=None, max_length=100)
    match_count: int | None = Field(default=None, ge=0)
    evidence_ref: str | None = Field(default=None, max_length=128, pattern=r"^[\w.-]+$")
    duration_ms: int | None = Field(default=None, ge=0)


class StepUpdatePayload(_DictAccessModel):
    step_idx: int = Field(ge=0)
    parent_step_idx: int | None = Field(default=None, ge=0)
    agent_name: str | None = Field(default=None, max_length=128)
    step_type: StepType
    status: StepStatus
    delta_seq: int = Field(ge=0)
    render_info: StepRenderInfo = Field(default_factory=StepRenderInfo)
    error_details: str | None = Field(default=None, max_length=1024)


_SECRET_VALUE_RE = re.compile(
    r"(?i)(private[^\r\n]*|api[._-]?key[^\s,;]*|secret[^\s,;]*|password[^\s,;]*|"
    r"credential[^\s,;]*|authorization[^\s,;]*|bearer\s+\S+|sk-[A-Za-z0-9_-]{12,}|AIza[0-9A-Za-z_-]{16,}|"
    r"gh[pousr]_[A-Za-z0-9]{16,}|[A-Za-z0-9_=-]{24,})"
)
_SECRET_KEY_RE = re.compile(r"(secret|password|token|api.?key|credential|private.?key|authorization)", re.I)


def redact_secrets(value: Any) -> Any:
    """Scrub credentials and API keys from client-facing event payloads and errors."""
    if isinstance(value, BaseException):
        type_name = type(value).__name__
        raw_msg = str(value).strip()
        if not raw_msg:
            return type_name
        return f"{type_name}: {_SECRET_VALUE_RE.sub('[redacted]', raw_msg)}"[:512]
    if isinstance(value, str):
        return _SECRET_VALUE_RE.sub("[redacted]", value)
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(item, str) and _SECRET_KEY_RE.search(str(key)):
                redacted[key] = "[redacted]"
            else:
                redacted[key] = redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if hasattr(value, "model_dump"):
        return redact_secrets(value.model_dump(mode="json", exclude_none=True))
    if isinstance(value, Enum):
        return value.value
    return value


class StepHandle:
    def __init__(
        self,
        tracker: "TrajectoryStepTracker",
        *,
        step_idx: int,
        parent_step_idx: int | None,
        step_type: StepType,
        agent_name: str | None,
        initial_info: dict[str, Any],
        extra_metadata: dict[str, Any],
    ):
        self._tracker = tracker
        self.step_idx = step_idx
        self.parent_step_idx = parent_step_idx
        self.step_type = step_type
        self.agent_name = agent_name
        self.delta_seq = 0
        self._completion_info: dict[str, Any] = {"title": initial_info.get("title")}
        self._terminal_status: StepStatus | None = None
        self._error_details: str | None = None
        self._extra_metadata = extra_metadata

    async def emit_delta(self, render_info: dict[str, Any] | StepRenderInfo | None = None, **kwargs: Any) -> None:
        await self.update(render_info, status="RUNNING", **kwargs)

    async def update(
        self,
        render_info: dict[str, Any] | StepRenderInfo | None = None,
        *,
        status: StepStatus = "RUNNING",
        error_details: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.delta_seq += 1
        merged = dict(render_info.model_dump(exclude_none=True) if isinstance(render_info, StepRenderInfo) else (render_info or {}))
        merged.update(kwargs)
        await self._tracker._emit_step(
            step_idx=self.step_idx,
            parent_step_idx=self.parent_step_idx,
            step_type=self.step_type,
            agent_name=self.agent_name,
            status=status,
            delta_seq=self.delta_seq,
            render_info=merged,
            error_details=error_details,
            extra_metadata=self._extra_metadata,
        )

    def set_completion_info(self, render_info: dict[str, Any] | StepRenderInfo | None = None, **kwargs: Any) -> None:
        merged = dict(render_info.model_dump(exclude_none=True) if isinstance(render_info, StepRenderInfo) else (render_info or {}))
        merged.update(kwargs)
        self._completion_info.update({k: v for k, v in merged.items() if v is not None})

    def mark_error(self, error_details: str, render_info: dict[str, Any] | StepRenderInfo | None = None, **kwargs: Any) -> None:
        self._terminal_status = "ERROR"
        self._error_details = str(redact_secrets(error_details.strip() or "Execution failed"))[:512]
        if render_info or kwargs:
            self.set_completion_info(render_info, **kwargs)


class TrajectoryStepTracker:
    def __init__(self, emit: Callable[..., Any] | None = None):
        self.emit = emit
        self._lock = Lock()
        self._next_idx = 0

    def allocate_step_idx(self) -> int:
        with self._lock:
            idx = self._next_idx
            self._next_idx += 1
            return idx

    async def _emit_step(
        self,
        *,
        step_idx: int,
        parent_step_idx: int | None,
        step_type: StepType,
        agent_name: str | None,
        status: StepStatus,
        delta_seq: int,
        render_info: dict[str, Any],
        error_details: str | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> None:
        if self.emit is None:
            return
        clean_info = StepRenderInfo.model_validate({k: v for k, v in render_info.items() if v is not None})
        payload: dict[str, Any] = {
            **(extra_metadata or {}),
            "step_idx": step_idx,
            "parent_step_idx": parent_step_idx,
            "agent_name": agent_name,
            "step_type": step_type,
            "status": status,
            "step_status": status,
            "delta_seq": delta_seq,
            "render_info": clean_info.model_dump(exclude_none=True),
            "error_details": error_details,
        }
        res = self.emit("step_update", **payload)
        if inspect.isawaitable(res):
            await res

    @asynccontextmanager
    async def step_scope(
        self,
        step_type: StepType,
        title: str,
        parent_step_idx: int | None = None,
        *,
        initial_render_info: dict[str, Any] | StepRenderInfo | None = None,
        agent_name: str | None = None,
        agent_id: AgentId | str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
        **extra_render_info: Any,
    ):
        step_idx = self.allocate_step_idx()
        started = time.monotonic()
        init_dict = dict(
            initial_render_info.model_dump(exclude_none=True)
            if isinstance(initial_render_info, StepRenderInfo)
            else (initial_render_info or {})
        )
        for key, value in extra_render_info.items():
            if key in StepRenderInfo.model_fields and value is not None:
                init_dict[key] = value
        init_dict["title"] = title
        if agent_name and "agent_name" not in init_dict:
            init_dict["agent_name"] = agent_name
        extra_meta: dict[str, Any] = {}
        if agent_id is not None:
            extra_meta["agent_id"] = agent_id
        if task_id is not None:
            extra_meta["task_id"] = task_id
        if run_id is not None:
            extra_meta["run_id"] = run_id

        handle = StepHandle(
            self,
            step_idx=step_idx,
            parent_step_idx=parent_step_idx,
            step_type=step_type,
            agent_name=agent_name,
            initial_info=init_dict,
            extra_metadata=extra_meta,
        )
        await self._emit_step(
            step_idx=step_idx,
            parent_step_idx=parent_step_idx,
            step_type=step_type,
            agent_name=agent_name,
            status="RUNNING",
            delta_seq=0,
            render_info=init_dict,
            extra_metadata=extra_meta,
        )
        try:
            yield handle
        except asyncio.CancelledError:
            duration_ms = max(0, int((time.monotonic() - started) * 1000))
            handle.delta_seq += 1
            final_info = {**handle._completion_info, "duration_ms": duration_ms}
            try:
                await self._emit_step(
                    step_idx=step_idx,
                    parent_step_idx=parent_step_idx,
                    step_type=step_type,
                    agent_name=agent_name,
                    status="CANCELING",
                    delta_seq=handle.delta_seq,
                    render_info=final_info,
                    error_details="Step cancelled",
                    extra_metadata=extra_meta,
                )
            except Exception:
                pass
            raise
        except Exception as exc:
            duration_ms = max(0, int((time.monotonic() - started) * 1000))
            handle.delta_seq += 1
            final_info = {**handle._completion_info, "duration_ms": duration_ms}
            try:
                await self._emit_step(
                    step_idx=step_idx,
                    parent_step_idx=parent_step_idx,
                    step_type=step_type,
                    agent_name=agent_name,
                    status="ERROR",
                    delta_seq=handle.delta_seq,
                    render_info=final_info,
                    error_details=redact_secrets(exc),
                    extra_metadata=extra_meta,
                )
            except Exception:
                pass
            raise
        else:
            duration_ms = max(0, int((time.monotonic() - started) * 1000))
            handle.delta_seq += 1
            final_info = {**handle._completion_info, "duration_ms": duration_ms}
            exit_code = final_info.get("exit_code")
            if handle._terminal_status == "ERROR" or (step_type == "run_command" and exit_code not in (None, 0)):
                status: StepStatus = "ERROR"
                err = handle._error_details or f"Command exited with code {exit_code}"
            else:
                status = "DONE"
                err = None
            await self._emit_step(
                step_idx=step_idx,
                parent_step_idx=parent_step_idx,
                step_type=step_type,
                agent_name=agent_name,
                status=status,
                delta_seq=handle.delta_seq,
                render_info=final_info,
                error_details=err,
                extra_metadata=extra_meta,
            )

    step = step_scope


class JobEvent(ContractModel):
    job_id: str
    seq: int = Field(ge=1)
    type: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
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
    snapshot_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    workspace_path: str | None = None
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


_TX_EVENTS: ContextVar[list[JobEvent] | None] = ContextVar("_TX_EVENTS", default=None)


class _SQLiteStore:
    def __init__(self, path: Path | str, schema: str):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(schema)

    def _on_commit(self, batch: list[JobEvent]) -> None:
        pass

    @contextmanager
    def _transaction(self):
        # One connection per operation allows safe use from worker threads.
        batch: list[JobEvent] = []
        token = _TX_EVENTS.set(batch)
        try:
            with closing(sqlite3.connect(self.path, timeout=10)) as db:
                db.row_factory = sqlite3.Row
                db.execute("BEGIN IMMEDIATE")
                with db:
                    yield db
        finally:
            _TX_EVENTS.reset(token)
        if batch:
            self._on_commit(batch)


class JobStore(_SQLiteStore):
    def __init__(self, path: Path | str):
        super().__init__(path, """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                folder_path TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                report TEXT,
                error TEXT,
                owner TEXT NOT NULL,
                intent_key TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                record TEXT NOT NULL,
                UNIQUE(owner, intent_key)
            );
            CREATE TABLE IF NOT EXISTS events (
                job_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                type TEXT NOT NULL,
                payload TEXT NOT NULL,
                timestamp REAL NOT NULL,
                PRIMARY KEY(job_id, seq)
            );
            CREATE TABLE IF NOT EXISTS execution_leases (
                job_id TEXT PRIMARY KEY, execution_id TEXT NOT NULL,
                started_at REAL NOT NULL, initial_elapsed REAL NOT NULL,
                elapsed_seconds REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS jobs_active_status ON jobs(status);
            CREATE INDEX IF NOT EXISTS jobs_active_identity ON jobs(status, job_id);
            CREATE TABLE IF NOT EXISTS tool_operations (
                operation_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, task_id TEXT NOT NULL,
                command_id TEXT NOT NULL, input_hash TEXT NOT NULL, evidence_ref TEXT
            );
            CREATE INDEX IF NOT EXISTS tool_operation_scope ON tool_operations(job_id,task_id,command_id);
        """)
        self._sub_lock = Lock()
        self._subscribers: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Queue[JobEvent]]]] = {}

    def _on_commit(self, batch: list[JobEvent]) -> None:
        with self._sub_lock:
            for event in batch:
                for loop, queue in list(self._subscribers.get(event.job_id, ())):
                    if loop.is_closed():
                        continue
                    try:
                        running_loop = asyncio.get_running_loop()
                    except RuntimeError:
                        running_loop = None
                    if running_loop is loop:
                        queue.put_nowait(event)
                    else:
                        loop.call_soon_threadsafe(queue.put_nowait, event)

    def subscribe(self, job_id: str, *, owner: str) -> asyncio.Queue[JobEvent]:
        self.get(job_id, owner=owner)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[JobEvent] = asyncio.Queue()
        with self._sub_lock:
            self._subscribers.setdefault(job_id, []).append((loop, queue))
        return queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue[JobEvent]) -> None:
        with self._sub_lock:
            subs = self._subscribers.get(job_id)
            if not subs:
                return
            kept = [entry for entry in subs if entry[1] is not queue]
            if kept:
                self._subscribers[job_id] = kept
            else:
                self._subscribers.pop(job_id, None)

    def _get(self, db, job_id: str, owner: str) -> JobRecord:
        row = db.execute("SELECT record FROM jobs WHERE job_id=? AND owner=?", (job_id, owner)).fetchone()
        if row is None:
            raise JobNotFound("job not found")
        return JobRecord.model_validate_json(row["record"])

    def _save(self, db, record: JobRecord, *, error: str | None = None) -> None:
        record.updated_at = time.time()
        report_json = _json(record.result) if record.result is not None else None
        db.execute(
            "UPDATE jobs SET status=?, updated_at=?, report=?, error=COALESCE(?, error), record=? WHERE job_id=? AND owner=?",
            (record.status, record.updated_at, report_json, error, record.model_dump_json(), record.job_id, record.owner),
        )

    def _enqueue_event(self, db, job_id: str, event_type: str, payload: dict[str, Any]) -> JobEvent:
        seq = db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE job_id=?", (job_id,)).fetchone()[0]
        clean_payload = redact_secrets(dict(payload))
        event = JobEvent(job_id=job_id, seq=seq, type=event_type, payload=clean_payload, timestamp=time.time())
        db.execute(
            "INSERT INTO events(job_id,seq,type,payload,timestamp) VALUES(?,?,?,?,?)",
            (event.job_id, event.seq, event.type, _json(event.payload), event.timestamp),
        )
        batch = _TX_EVENTS.get()
        if batch is not None:
            batch.append(event)
        return event

    def _settle_steps(self, db, job_id: str, status: JobStatus) -> None:
        if status not in {"failed", "cancelled", "interrupted", "completed"}:
            return
        active_steps: dict[int, dict[str, Any]] = {}
        for row in db.execute(
            "SELECT payload FROM events WHERE job_id=? AND type='step_update' ORDER BY seq",
            (job_id,),
        ):
            payload = json.loads(row["payload"])
            step_idx = payload.get("step_idx")
            if step_idx is None:
                continue
            step_status = payload.get("status") or payload.get("step_status")
            if step_status == "RUNNING":
                active_steps[step_idx] = payload
            elif step_status in {"DONE", "ERROR", "CANCELING"}:
                active_steps.pop(step_idx, None)
        if not active_steps:
            return
        terminal_step_status: StepStatus = "CANCELING" if status == "cancelled" else "ERROR"
        for step_idx, last_payload in sorted(active_steps.items()):
            next_delta = (last_payload.get("delta_seq") or 0) + 1
            title = (last_payload.get("render_info") or {}).get("title")
            self._enqueue_event(
                db,
                job_id,
                "step_update",
                {
                    "agent_id": last_payload.get("agent_id"),
                    "task_id": last_payload.get("task_id"),
                    "run_id": last_payload.get("run_id"),
                    "step_idx": step_idx,
                    "parent_step_idx": last_payload.get("parent_step_idx"),
                    "agent_name": last_payload.get("agent_name"),
                    "step_type": last_payload.get("step_type") or "tool",
                    "status": terminal_step_status,
                    "step_status": terminal_step_status,
                    "delta_seq": next_delta,
                    "render_info": {"title": title} if title is not None else {},
                    "error_details": "Interrupted by job termination",
                },
            )

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
            folder_path = str(request.get("workspace_path") or "")
            db.execute(
                "INSERT INTO jobs(job_id,folder_path,status,created_at,updated_at,report,error,owner,intent_key,request_hash,record) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (record.job_id, folder_path, record.status, now, now, None, None,
                 owner, idempotency_key, request_hash, record.model_dump_json()),
            )
            self._enqueue_event(db, record.job_id, "job_queued", {"status": "queued"})
            return record

    def get(self, job_id: str, *, owner: str) -> JobRecord:
        with self._transaction() as db:
            return self._get(db, job_id, owner)

    def list_jobs(self, *, owner: str, limit: int = 50) -> list[JobRecord]:
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        with self._transaction() as db:
            rows = db.execute(
                "SELECT record FROM jobs WHERE owner=? ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (owner, limit),
            ).fetchall()
        return [JobRecord.model_validate_json(row["record"]) for row in rows]

    def transition(self, job_id: str, *, owner: str, expected_status: JobStatus,
                   status: JobStatus, result: dict[str, Any] | None = None,
                   error: str | None = None) -> JobRecord:
        with self._transaction() as db:
            record = self._get(db, job_id, owner)
            if record.status != expected_status or status not in _TRANSITIONS[record.status]:
                raise JobConflict("job transition is no longer valid")
            self._settle_steps(db, job_id, status)
            record.status = status
            if result is not None:
                record.result = result
            self._save(db, record, error=redact_secrets(error) if error is not None else None)
            self._enqueue_event(db, job_id, f"job_{status}", {"status": status})
            return record

    def queued(self, *, limit: int = 100) -> list[JobRecord]:
        # Internal worker API. Public lookup always requires an owner.
        if not 1 <= limit <= 100:
            raise ValueError("job batch limit must be between 1 and 100")
        with self._transaction() as db:
            return [JobRecord.model_validate_json(row[0]) for row in db.execute(
                "SELECT record FROM jobs WHERE status='queued' ORDER BY rowid LIMIT ?", (limit,))]

    def running(self, *, after: str = "", limit: int = 100) -> list[JobRecord]:
        if not 1 <= limit <= 100:
            raise ValueError("job batch limit must be between 1 and 100")
        with self._transaction() as db:
            return [JobRecord.model_validate_json(row[0]) for row in db.execute(
                "SELECT record FROM jobs WHERE status='running' AND job_id>? "
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
            self._enqueue_event(db, job_id, "job_running", {"status": "running"})
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
            self._settle_steps(db, job_id, "interrupted")
            record.status = "interrupted"
            self._save(db, record)
            db.execute("DELETE FROM execution_leases WHERE job_id=?", (job_id,))
            self._enqueue_event(db, job_id, "job_interrupted", {"status": "interrupted"})

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
        completions = [dict(payload) for payload in model_completions]
        if len({payload.get("operation_id") for payload in completions}) != len(completions):
            raise JobConflict("duplicate model completion")
        with self._transaction() as db:
            record = self._get(db, job_id, owner)
            previous = record.ledger
            for payload in completions:
                op_id = payload.get("operation_id")
                reservation = previous.inflight.get(op_id)
                outcome = payload.get("outcome")
                agent_id = payload.get("agent_id")
                agent_val = agent_id.value if isinstance(agent_id, AgentId) else agent_id
                total_tokens = payload.get("total_tokens")
                if (reservation is None or op_id in updated.inflight or outcome is None
                        or agent_val != reservation.agent_id.value or total_tokens is None
                        or (outcome == "unknown" and total_tokens != reservation.tokens)):
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
            for payload in completions:
                normalized = {
                    **payload,
                    "agent_id": payload["agent_id"].value if isinstance(payload.get("agent_id"), AgentId) else payload.get("agent_id"),
                }
                self._enqueue_event(db, job_id, "model_call_completed", normalized)
            if (updated.total_tokens != previous.total_tokens or updated.task_tools != previous.task_tools
                    or updated.review_round != previous.review_round):
                self._enqueue_event(
                    db,
                    job_id,
                    "budget_updated",
                    {"total_tokens": updated.total_tokens, "duration_seconds": updated.elapsed_seconds},
                )

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

    def emit(self, job_id: str, *, owner: str, event_type: str, payload: dict[str, Any] | None = None) -> JobEvent:
        with self._transaction() as db:
            self._get(db, job_id, owner)
            return self._enqueue_event(db, job_id, event_type, payload or {})

    def events(self, job_id: str, *, owner: str, after: int = 0, limit: int = 1000) -> list[JobEvent]:
        if type(after) is not int or not 0 <= after <= MAX_EVENT_CURSOR or not 1 <= limit <= 1000:
            raise ValueError("invalid replay cursor or page size")
        with self._transaction() as db:
            self._get(db, job_id, owner)
            return [
                JobEvent(
                    job_id=job_id,
                    seq=row["seq"],
                    type=row["type"],
                    payload=json.loads(row["payload"]),
                    timestamp=row["timestamp"],
                )
                for row in db.execute(
                    "SELECT seq,type,payload,timestamp FROM events WHERE job_id=? AND seq>? ORDER BY seq LIMIT ?",
                    (job_id, after, limit),
                )
            ]


class _JobLeaseLock:
    """Non-blocking OS file lock held while a worker owns a running job."""

    def __init__(self, path: Path, fd: int):
        self.path = path
        self._fd: int | None = fd

    @classmethod
    def try_acquire(cls, path: Path) -> "_JobLeaseLock | None":
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return cls(path, fd)
        except OSError:
            os.close(fd)
            return None

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl

                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            try:
                os.close(fd)
            except OSError:
                pass


class DurableJobManager:
    def __init__(self, store: JobStore,
                 execute: Callable[[JobRecord], Awaitable[dict[str, Any]]], *, concurrent_jobs: int = 1,
                 recover_timeout: Callable[[JobRecord], Awaitable[dict[str, Any]]] | None = None):
        if concurrent_jobs < 1:
            raise ValueError("at least one job worker is required")
        self.store, self.execute = store, execute
        self.recover_timeout = recover_timeout
        self._slots = asyncio.Semaphore(concurrent_jobs)
        self._capacity = concurrent_jobs
        self._tasks: dict[str, asyncio.Task] = {}
        self._maintenance: asyncio.Task | None = None
        self._maintenance_id = uuid4().hex
        self._recovery_cursor = ""
        self._closed = False

    def _acquire_lease(self, job_id: str) -> _JobLeaseLock | None:
        safe_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", job_id)
        lease_path = Path(f"{self.store.path}.leases") / f"{safe_id}.lock"
        return _JobLeaseLock.try_acquire(lease_path)

    def _use_runtime(self):
        if self._closed:
            raise RuntimeError("job manager is closed")

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
        self._tasks = {identity: task for identity, task in self._tasks.items() if not task.done()}
        for job in running:
            if job.job_id not in self._tasks:
                lease = self._acquire_lease(job.job_id)
                if lease is None:
                    continue
                try:
                    self.store.recover_abandoned(job.job_id, owner=job.owner)
                finally:
                    lease.release()
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
                # Administrative scans are idempotent. Keep recovery
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
        self._use_runtime()
        self._scan()
        self._ensure_maintenance()

    async def submit(self, *, owner: str, request: dict[str, Any], idempotency_key: str,
                     limits: BalancedLimits | None = None) -> JobRecord:
        self._use_runtime()
        job = self.store.submit(owner=owner, request=request, idempotency_key=idempotency_key, limits=limits)
        if job.status == "queued":
            self._schedule(job)
        return job

    async def _run(self, original: JobRecord) -> None:
        started = None
        claimed = False
        deadline_expired = False
        initial_elapsed = original.ledger.elapsed_seconds
        heartbeat = None
        lease = None
        execution_id = uuid4().hex
        try:
            async with self._slots:
                lease = self._acquire_lease(original.job_id)
                if lease is None:
                    return
                try:
                    job = self.store.claim(original.job_id, owner=original.owner, execution_id=execution_id)
                    claimed = True
                except JobConflict:
                    return
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
                    self.store.emit(job.job_id, owner=job.owner, event_type="error_occurred",
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
                self.store.emit(current.job_id, owner=current.owner, event_type="error_occurred", payload={"error_code": code})
                self.store.transition(current.job_id, owner=current.owner, expected_status="running", status="failed", error=redact_secrets(exc))
        finally:
            try:
                if heartbeat is not None:
                    heartbeat.cancel()
                    await asyncio.gather(heartbeat, return_exceptions=True)
                if started is not None:
                    self.store.account_execution_time(original.job_id, owner=original.owner,
                                                      initial_elapsed=initial_elapsed, run_seconds=time.monotonic() - started)
                    self.store.release_execution(original.job_id, execution_id)
            finally:
                if lease is not None:
                    lease.release()

    async def wait(self, job_id: str, *, owner: str) -> JobRecord:
        while True:
            job = self.store.get(job_id, owner=owner)
            if job.status not in {"queued", "running"}:
                return job
            await asyncio.sleep(0.01)

    async def cancel(self, job_id: str, *, owner: str) -> JobRecord:
        self._use_runtime()
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
        return job

    async def resume(self, job_id: str, *, owner: str) -> JobRecord:
        self._use_runtime()
        job = self.store.transition(job_id, owner=owner, expected_status="interrupted", status="queued")
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
