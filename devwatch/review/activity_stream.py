"""One transport-independent lifecycle for public agent activity.

The publisher must durably assign a sequence and return the stored event. State
changes only after that write succeeds, so failed persistence cannot turn a
started activity into an invisible completion.
"""

import json
import re
from threading import RLock
import time
from typing import Any, Callable, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


ActivityType = Literal[
    "planning", "file_search", "code_search", "file_read", "web_search",
    "command", "tool_call", "test_execution", "code_analysis", "finding",
    "response", "result",
]
EventType = Literal["activity.started", "activity.delta", "activity.completed",
                    "activity.failed", "activity.cancelled"]
TERMINAL = {"activity.completed", "activity.failed", "activity.cancelled"}


class InvalidActivity(ValueError):
    """A lifecycle transition or identity is invalid."""


class ActivityData(BaseModel):
    """Allowlisted public fields. Producers must redact output before publication."""

    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, max_length=60000)
    stdout: str | None = Field(default=None, max_length=60000)
    stderr: str | None = Field(default=None, max_length=60000)
    path: str | None = Field(default=None, max_length=512)
    query: str | None = Field(default=None, max_length=256)
    tool: str | None = Field(default=None, max_length=64)
    agentId: str | None = Field(default=None, max_length=64)
    taskId: str | None = Field(default=None, max_length=128)
    phase: str | None = Field(default=None, max_length=64)
    verdict: str | None = Field(default=None, max_length=32)
    outcome: str | None = Field(default=None, max_length=32)
    commandId: str | None = Field(default=None, max_length=64)
    evidenceRef: str | None = Field(default=None, max_length=128)
    findingId: str | None = Field(default=None, max_length=128)
    errorCode: str | None = Field(default=None, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    message: str | None = Field(default=None, max_length=512)
    count: int | None = Field(default=None, ge=0)
    progress: int | None = Field(default=None, ge=0)
    exitCode: int | None = None
    durationSeconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    totalTokens: int | None = Field(default=None, ge=0)
    truncated: bool | None = None


class ActivityEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    eventId: str
    sequence: int = Field(ge=0)
    timestamp: float = Field(ge=0, allow_inf_nan=False)
    runId: str
    agentRunId: str
    activityId: str
    parentActivityId: str | None = None
    type: EventType
    activityType: ActivityType
    data: ActivityData


class ActivityStream:
    """Publish ordered activity events for one run through a durable callback."""

    def __init__(self, run_id: str, publish: Callable[[ActivityEvent], ActivityEvent]):
        self.run_id, self._publish = run_id, publish
        self._lock = RLock()
        self._agents: dict[str, bool] = {}
        self._active: dict[str, tuple[str, ActivityType, str | None]] = {}
        self._known: set[str] = set()
        self._closed = False

    def begin_agent(self, agent_run_id: str, *, required: bool = False) -> None:
        with self._lock:
            if self._closed or agent_run_id in self._agents:
                raise InvalidActivity("agent run already registered or run closed")
            self._agents[agent_run_id] = False

    def start(self, agent_run_id: str, activity_type: ActivityType, data: dict[str, Any],
              *, parent_activity_id: str | None = None, activity_id: str | None = None) -> str:
        with self._lock:
            if self._closed or self._agents.get(agent_run_id) is not False:
                raise InvalidActivity("agent run is not active")
            if parent_activity_id is not None and (parent_activity_id not in self._active
                    or self._active[parent_activity_id][0] != agent_run_id):
                raise InvalidActivity("parent activity is not active in this agent run")
            activity_id = activity_id or uuid4().hex
            if activity_id in self._known:
                raise InvalidActivity("activity identity already used")
            self._emit(agent_run_id, activity_id, parent_activity_id, "activity.started", activity_type, data)
            self._known.add(activity_id)
            self._active[activity_id] = (agent_run_id, activity_type, parent_activity_id)
            return activity_id

    def delta(self, activity_id: str, data: dict[str, Any]) -> ActivityEvent:
        return self._update(activity_id, "activity.delta", data)

    def complete(self, activity_id: str, data: dict[str, Any]) -> ActivityEvent:
        return self._update(activity_id, "activity.completed", data)

    def fail(self, activity_id: str, error_code: str, data: dict[str, Any] | None = None) -> ActivityEvent:
        if not error_code or len(error_code) > 64 or not error_code.replace("_", "").isalnum():
            raise InvalidActivity("invalid public error code")
        return self._update(activity_id, "activity.failed", {**(data or {}), "errorCode": error_code})

    def cancel(self, activity_id: str) -> ActivityEvent:
        return self._update(activity_id, "activity.cancelled", {})

    def _update(self, activity_id: str, event_type: EventType, data: dict[str, Any]) -> ActivityEvent:
        with self._lock:
            if activity_id not in self._active:
                raise InvalidActivity("activity is not active")
            agent_run_id, activity_type, parent_id = self._active[activity_id]
            event = self._emit(agent_run_id, activity_id, parent_id, event_type, activity_type, data)
            if event_type in TERMINAL:
                del self._active[activity_id]
            return event

    def _emit(self, agent_run_id: str, activity_id: str, parent_id: str | None,
              event_type: EventType, activity_type: ActivityType, data: dict[str, Any]) -> ActivityEvent:
        parsed = ActivityData.model_validate(data)
        if len(json.dumps(parsed.model_dump(exclude_none=True), ensure_ascii=False, allow_nan=False).encode("utf-8")) > 65536:
            raise InvalidActivity("activity data exceeds the public event limit")
        event = ActivityEvent(eventId=uuid4().hex, sequence=0, timestamp=time.time(),
                              runId=self.run_id, agentRunId=agent_run_id, activityId=activity_id,
                              parentActivityId=parent_id, type=event_type,
                              activityType=activity_type, data=parsed)
        return self._publish(event)

    def end_agent(self, agent_run_id: str) -> None:
        with self._lock:
            if self._agents.get(agent_run_id) is not False or any(
                    owner == agent_run_id for owner, _, _ in self._active.values()):
                raise InvalidActivity("agent run has active activities or is not active")
            self._agents[agent_run_id] = True

    def end_run(self) -> None:
        with self._lock:
            if self._closed or self._active or not self._agents or not all(self._agents.values()):
                raise InvalidActivity("run has unfinished agent activity")
            self._closed = True


class AgentActivityPublisher:
    """Translate current review observations into the one public activity stream.

    This is the migration seam for existing agent callbacks. Job status and budget
    accounting remain in their separate durable job record.
    """

    _COMMANDS = {"run_command", "lint", "type_check", "coverage", "sast", "profile", "benchmark", "db_analyze", "query_analyze"}
    _ANALYSIS = {"parse_ast", "symbol_lookup", "call_graph", "dependency_graph", "import_graph", "complexity", "config_read", "git_diff", "git_history"}

    def __init__(self, stream: ActivityStream):
        self.stream = stream
        self.stream.begin_agent("review")
        self._agents = {"review"}
        self._result: dict[str, str] = {}
        self._operations: dict[str, str] = {}
        self._nodes: dict[str, list[str]] = {}
        self._phases: dict[str, str] = {}
        self._output: dict[str, dict[str, str]] = {}

    def _owner(self, payload):
        run_id = payload.get("run_id")
        return run_id if run_id in self._agents else "review"

    def _instant(self, owner, activity_type, data):
        activity = self.stream.start(owner, activity_type, data)
        self.stream.complete(activity, data)

    def record(self, kind: str, **payload) -> None:
        if kind == "step_update":
            return
        operation = payload.get("operation_id")
        owner = self._owner(payload)
        if kind == "tool_progress":
            if operation not in self._operations or payload.get("stream") not in {"stdout", "stderr"}:
                raise InvalidActivity("output has no active command or channel")
            channel = payload["stream"]
            chunk = payload.get("text", "")
            self.stream.delta(self._operations[operation], {channel: chunk})
            output = self._output.setdefault(operation, {"stdout": "", "stderr": ""})
            output[channel] = (output[channel] + chunk)[:16000]
            return
        if kind == "agent_started":
            run_id = payload["run_id"]
            self.stream.begin_agent(run_id, required=True)
            self._agents.add(run_id)
            self._result[run_id] = self.stream.start(run_id, "result", {
                "agentId": getattr(payload.get("agent_id"), "value", payload.get("agent_id")),
                "taskId": payload.get("task_id")})
            return
        if kind == "agent_completed":
            run_id = payload["run_id"]
            activity = self._result.pop(run_id)
            outcome = payload.get("outcome", "failed")
            if outcome == "cancelled":
                self.stream.cancel(activity)
            elif outcome == "succeeded":
                self.stream.complete(activity, {"outcome": outcome,
                    "durationSeconds": payload.get("duration_seconds"), "totalTokens": payload.get("total_tokens")})
            else:
                self.stream.fail(activity, "execution_failed")
            self.stream.end_agent(run_id)
            return
        if kind in {"graph_node_started", "model_call_started", "tool_called"}:
            if not operation:
                raise InvalidActivity("observable operation requires a stable identity")
            if kind == "graph_node_started":
                activity_type = "planning" if payload.get("node") == "planner_agent" else "code_analysis"
                data = {"message": payload.get("node"), "phase": payload.get("phase"),
                        "taskId": payload.get("task_id")}
            elif kind == "model_call_started":
                activity_type, data = "response", {"message": "Model response pending",
                    "phase": payload.get("phase"), "taskId": payload.get("task_id")}
            else:
                tool = payload.get("tool")
                activity_type = ("file_search" if tool == "repo_map" else "code_search" if tool == "code_search"
                    else "file_read" if tool in {"read_source", "read_evidence"} else "test_execution" if tool == "run_tests"
                    else "command" if tool in self._COMMANDS else "code_analysis" if tool in self._ANALYSIS else "tool_call")
                data = {"tool": tool, "phase": payload.get("phase"), "taskId": payload.get("task_id"),
                        "agentId": getattr(payload.get("agent_id"), "value", payload.get("agent_id"))}
            parent = self._nodes.get(owner, [])[-1] if self._nodes.get(owner) else None
            activity = self.stream.start(owner, activity_type, data,
                parent_activity_id=parent, activity_id=operation)
            self._operations[operation] = activity
            if kind == "graph_node_started":
                self._nodes.setdefault(owner, []).append(operation)
            return
        if kind in {"graph_node_completed", "model_call_completed", "tool_result"}:
            if not operation or operation not in self._operations:
                raise InvalidActivity("terminal observation has no active operation")
            if kind == "graph_node_completed":
                nodes = self._nodes.get(owner, [])
                if not nodes or nodes[-1] != operation:
                    raise InvalidActivity("graph node completion is out of order")
            activity = self._operations[operation]
            outcome = payload.get("outcome", "succeeded")
            if outcome == "cancelled":
                self.stream.cancel(activity)
            elif outcome in {"failed", "unknown"}:
                self.stream.fail(activity, payload.get("error_code") or "execution_failed", {
                    "tool": payload.get("tool"), "outcome": outcome,
                    "taskId": payload.get("task_id"),
                    "agentId": getattr(payload.get("agent_id"), "value", payload.get("agent_id")),
                    **{channel: value for channel, value in self._output.get(operation, {}).items() if value}})
            else:
                self.stream.complete(activity, {"tool": payload.get("tool"),
                    "evidenceRef": payload.get("evidence_ref"),
                    "taskId": payload.get("task_id"),
                    "agentId": getattr(payload.get("agent_id"), "value", payload.get("agent_id")),
                    "durationSeconds": payload.get("duration_seconds"),
                    "totalTokens": payload.get("total_tokens"), "outcome": outcome,
                    **{channel: value for channel, value in self._output.get(operation, {}).items() if value}})
            self._operations.pop(operation)
            self._output.pop(operation, None)
            if kind == "graph_node_completed":
                self._nodes[owner].pop()
            return
        if kind in {"finalization_started", "report_render_started"}:
            self._phases[kind] = self.stream.start("review", "result", {"message": kind})
            return
        if kind in {"finalization_completed", "report_render_completed"}:
            started = kind.replace("_completed", "_started")
            activity = self._phases[started]
            if payload.get("outcome") == "cancelled":
                self.stream.cancel(activity)
            elif payload.get("outcome") == "failed":
                self.stream.fail(activity, payload.get("error_code") or "execution_failed")
            else:
                self.stream.complete(activity, {"outcome": "succeeded"})
            self._phases.pop(started)
            return
        if kind in {"evidence_retrieved", "evidence_delivered", "evidence_inspected"}:
            data = {"evidenceRef": payload.get("evidence_ref"),
                    "progress": payload.get("end_offset", payload.get("offset")),
                    "message": kind, "agentId": getattr(payload.get("agent_id"), "value", payload.get("agent_id"))}
            if operation in self._operations:
                self.stream.delta(self._operations[operation], data)
            else:
                self._instant(owner, "file_read", data)
            return
        if kind == "error_occurred":
            activity = self.stream.start(owner, "result", {"taskId": payload.get("task_id"),
                "agentId": getattr(payload.get("agent_id"), "value", payload.get("agent_id")),
                "phase": payload.get("phase")})
            self.stream.fail(activity, payload.get("error_code") or "execution_failed")
            return
        if kind in {"finding_created", "candidate_submitted", "candidate_rejected", "verification_completed",
                    "validation_passed", "validation_failed", "iteration_started", "retry_started", "agent_reused"}:
            activity_type = ("finding" if kind == "finding_created" else "planning" if kind in
                {"iteration_started", "retry_started"} else "result" if kind == "agent_reused" else "code_analysis")
            self._instant(owner, activity_type, {"message": kind, "findingId": payload.get("finding_id"),
                "count": payload.get("count"), "verdict": payload.get("verdict"), "phase": payload.get("phase"),
                "errorCode": payload.get("error_code")})
            return
        raise InvalidActivity("unmapped review observation")

    def finish(self) -> None:
        self.stream.end_agent("review")
        self.stream.end_run()

    def public_response(self, text: str) -> None:
        # The accepted report is the public answer. Internal model action JSON is
        # private and never used as response text in this stream.
        if re.search(r"(?i)(api.?key|token|secret|password|credential|authorization|bearer|[A-Za-z0-9_-]{24,})", text):
            text = "Review completed. Open the report for details."
        truncated = len(text) > 60000
        final = text[:60000]
        activity = self.stream.start("review", "response", {"message": "Review summary"})
        for offset in range(0, len(final), 1024):
            self.stream.delta(activity, {"text": final[offset:offset + 1024]})
        self.stream.complete(activity, {"text": final, "truncated": truncated})
