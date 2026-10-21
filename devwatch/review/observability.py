"""Opt-in metadata export; local durable events remain authoritative.

Questions: which role failed, how many tokens/retries were charged, and which
tool/validation phase completed? No source, prompts, arguments or evidence bodies
cross this boundary. Failed/unknown telemetry is deliberately not retransmitted.
"""
import asyncio
from datetime import datetime, timezone
import json
import logging
import inspect
import time
from uuid import UUID, uuid4

_LOG = logging.getLogger(__name__)


def observed_node(name, node, emit, *, scope):
    """Instrument actual node entry/exit, without exposing LangGraph state.

    Synchronous nodes stay off the event loop. Drain their worker before releasing
    execution ownership on cancellation, just as checkpoint writers are drained.
    A start that cannot be journaled prevents execution; an unrecordable end fails
    closed. Process crashes can leave unmatched starts in the durable timeline.
    """
    async def observed(state):
        async def event(kind, **fields):
            result = emit(kind, state, node=name, graph_scope=scope, operation_id=operation, **fields)
            if inspect.isawaitable(result):
                await result
        operation, started, outcome = uuid4().hex, time.monotonic(), "failed"
        await event("graph_node_started")
        try:
            if inspect.iscoroutinefunction(node):
                result = await node(state)
            else:
                work = asyncio.create_task(asyncio.to_thread(node, state))
                cancelled = False
                while not work.done():
                    try:
                        await asyncio.shield(work)
                    except asyncio.CancelledError:
                        cancelled = True
                result = work.result()
                if cancelled:
                    raise asyncio.CancelledError
            outcome = "succeeded"
            return result
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        finally:
            await event("graph_node_completed", outcome=outcome,
                error_code="execution_failed" if outcome == "failed" else None,
                duration_seconds=time.monotonic() - started)
    return observed


def _order(event):
    stamp = datetime.fromtimestamp(event.timestamp, tz=timezone.utc)
    return stamp.strftime("%Y%m%dT%H%M%S%fZ") + str(UUID(event.event_id))


class MetadataExporter:
    def __init__(self, events, *, client=None, project="devwatch-metadata"):
        if not project or len(project) > 128:
            raise ValueError("bounded telemetry project required")
        self.events, self.client, self.project = events, client, project
        self.enabled = client is not None

    async def export_once(self, *, limit=20):
        if not self.enabled:
            return 0
        events = self.events.admit_telemetry(limit=limit)
        for event in events:
            # Explicit allowlist also strips evidence and task/path identifiers.
            metadata = {key: value for key, value in event.payload.model_dump(mode="json").items()
                if value is not None and key in {"status", "agent_id", "tool", "error_code", "duration_seconds", "total_tokens",
                    "phase", "iteration", "attempt", "run_id", "operation_id", "outcome", "stop_reason", "finish_reason",
                    "count", "verdict", "node", "graph_scope"}}
            # run_id/operation_id are generated random UUIDs, not job/task/source
            # fingerprints. Full review/evidence correlation remains local only.
            metadata.update(event=event.kind, sequence=event.sequence, entry_point="durable_event_export")
            stamp = datetime.fromtimestamp(event.timestamp, tz=timezone.utc)
            ancestors = self.events.trace_ancestors(event)
            hierarchy = {}
            if ancestors:
                lineage = [ancestor for ancestor in ancestors if ancestor.event_id != event.event_id]
                hierarchy = dict(trace_id=str(UUID(ancestors[0].event_id)),
                    dotted_order=".".join(_order(item) for item in [*lineage, event]))
                if lineage:
                    hierarchy["parent_run_id"] = str(UUID(lineage[-1].event_id))
            if event.payload.outcome in {"failed", "cancelled", "unknown"}:
                hierarchy["error"] = event.payload.error_code or event.payload.outcome
            task = asyncio.create_task(asyncio.to_thread(self.client.create_run,
                id=str(UUID(event.event_id)), name=event.kind, run_type="tool" if event.kind.startswith("tool_") else "chain",
                inputs={}, outputs={}, start_time=stamp, end_time=stamp,
                project_name=self.project, extra={"metadata": metadata}, **hierarchy))
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                if task.done() and not task.cancelled():
                    task.exception()
                raise
            except Exception as error:
                self.events.complete_telemetry(event.event_id, "failed")
                _LOG.warning(json.dumps({"event": "telemetry_export_failed", "entry_point": "durable_event_export",
                    "run_id": event.event_id, "error_type": type(error).__name__}))
            else:
                self.events.complete_telemetry(event.event_id, "sent")
        return len(events)

    async def run(self):
        while True:
            try:
                await self.export_once()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                _LOG.warning(json.dumps({"event": "telemetry_scan_failed", "entry_point": "durable_event_export",
                    "error_type": type(error).__name__}))
            await asyncio.sleep(.5)


def configured_metadata_client():
    """Call only after explicit DEVWATCH_LANGSMITH_METADATA=true."""
    import os
    from langsmith import Client
    from urllib3.util.retry import Retry
    key = os.getenv("LANGSMITH_API_KEY")
    if not key:
        raise ValueError("Explicit LangSmith metadata export requires a key")
    return Client(api_key=key, timeout_ms=(1000, 2000), auto_batch_tracing=False,
        retry_config=Retry(total=0), hide_inputs=True, hide_outputs=True,
        omit_traced_runtime_info=True, disable_prompt_cache=True)
