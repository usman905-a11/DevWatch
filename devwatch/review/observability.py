"""Opt-in metadata export; local durable events remain authoritative.

Questions: which role failed, how many tokens/retries were charged, and which
tool/validation phase completed? No source, prompts, arguments or evidence bodies
cross this boundary. Failed/unknown telemetry is deliberately not retransmitted.
"""
import asyncio
from datetime import datetime, timezone
import json
import logging
from uuid import UUID

_LOG = logging.getLogger(__name__)


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
                    "count", "verdict"}}
            # run_id/operation_id are generated random UUIDs, not job/task/source
            # fingerprints. Full review/evidence correlation remains local only.
            metadata.update(event=event.kind, sequence=event.sequence, entry_point="durable_event_export")
            stamp = datetime.fromtimestamp(event.timestamp, tz=timezone.utc)
            task = asyncio.create_task(asyncio.to_thread(self.client.create_run,
                id=str(UUID(event.event_id)), name=event.kind, run_type="tool" if event.kind.startswith("tool_") else "chain",
                inputs={}, outputs={}, start_time=stamp, end_time=stamp,
                project_name=self.project, extra={"metadata": metadata}))
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
