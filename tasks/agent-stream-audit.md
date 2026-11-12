# Agent activity stream audit (2026-10-26)

## Current flow

`DurableJobManager` claims an owned job. `_ReviewSession.emit` and `AgentSubgraphs._event` write bounded metadata through `JobStore.emit`; budget settlement writes related events in the same job transaction. `JobStore` assigns a job-wide sequence and stores events in its outbox. `dispatch_events` copies them idempotently to `EventStore`. `service.py` checks ownership, replays the persisted sequence, and sends the same records through HTTP pages, SSE, or the existing WebSocket endpoint. The browser currently consumes SSE with `observeJob`, resumes from its last accepted sequence, and keeps the last 200 events in `ReviewSession`; `JobActivity` displays metadata. The CLI and evaluation scripts also consume event pages.

## Relevant code and consumers

- `devwatch/review/jobs.py`: `EventKind`, `EventPayload`, `PersistedEvent`, `JobStore._enqueue_event/emit/update_ledger/dispatch_events`, `EventStore.append/replay/trace_ancestors`, and job lifecycle transitions.
- `devwatch/review/workflow.py`: `_ReviewSession.emit`, graph orchestration, finding and finalization publication.
- `devwatch/review/subgraphs.py`: `AgentSubgraphs._event/_invoke/_call_model/_execute_action`; agent, model, tool, candidate, verification, and retry observations.
- `devwatch/review/observability.py`: paired graph node metadata and optional telemetry export; the exporter reconstructs ancestry from old event names.
- `devwatch/review/tool_runtime.py`: approved commands capture stdout/stderr into bounded evidence only after process execution; they do not stream either pipe.
- `devwatch/review/repository.py`, `tool_catalogue.py`, `database_tools.py`, `finalization.py`: snapshot-bound reads/searches/analysis and finalization actions; most return evidence references rather than live content.
- `devwatch/providers/base.py`, `openai_adapter.py`: only `generate_completion` exists. The provider returns a full response; it has no generic delta callback or async stream.
- `devwatch/review/service.py`: existing owner-checked HTTP/SSE/WebSocket transport and cursor replay. WebSocket authenticates by header or first text frame and closes on disconnect without cancelling the job.
- `frontend/src/review/wire.ts`, `wire-schema.json`, `durable-events.ts`, `review-session.ts`, `JobActivity.tsx`: schema validation, SSE reconnect and cleanup, 200-event display window. The browser does not currently use WebSocket.
- `devwatch/review/client.py`, `devwatch/cli.py`, `scripts/evaluate_agents.py`, `scripts/evaluate_release.py`, `scripts/export_browser_fixture.py`, `scripts/export_review_contracts.py`, plus backend and frontend event tests/fixtures: current event consumers and generated contract owners.

## Confirmed problems and applicable earlier findings

The old activity stream is a flat list of metadata names, not a Run → AgentRun → Activity lifecycle. `tool_called` and `tool_result` correlate by operation ID but have no enforced terminal transition; graph node starts may remain unmatched after a crash. The browser has no activity reducer or final-state reconciliation. No live stdout, stderr, tool output, or response text reaches a client. There are no file-search or web-search tools in the current tool catalogue; `repo_map` and `code_search` are the nearest existing actions. The 200-event browser window can remove a start before its terminal event. The backend stores an unbounded event history and polls it per connection; there is no explicit slow-WebSocket-client queue bound.

The M22 report's earlier findings about missing graph node boundaries, rejected `tool_timeout`, and flattened telemetry ancestry were addressed for **metadata events**; they do not establish the requested structured stream. The audit-fixes report explicitly says raw source and tool output were excluded. `CODEBASE_AUDIT.md` describes an older frontend and is not evidence of the current event path. Existing M22 replay, owner checks, cancellation, budget settlement, private checkpoints, and recovery tests still apply and must survive migration.

## Keep, replace, and leave alone

Keep the job store, transactional outbox, persisted ordering/replay, owner checks, WebSocket/SSE transport, explicit job control, artifact access controls, private checkpoints, budget accounting, and review orchestration. Replace the agent-activity event names/payload and their frontend display/reducer with one versioned activity envelope and lifecycle publisher. Replace old event-specific telemetry ancestry and evaluation consumers only where they depend on activity names. Keep report/source APIs, authorization, provider selection, snapshot capture, and acceptance logic outside the migration.

## Expected change surface and risks

Expected production files: `jobs.py`, `workflow.py`, `subgraphs.py`, `observability.py`, `tool_runtime.py`, `repository.py`, `providers/base.py`, `providers/openai_adapter.py`, `service.py`, `client.py`, `frontend/src/review/wire.ts`, `durable-events.ts`, `review-session.ts`, `JobActivity.tsx`, and generated `wire-schema.json`. The CLI, evaluation scripts, export scripts, focused backend/frontend tests, and wire fixtures need contract migration. A shared activity module may be added.

Migration risks: historical journals use the old shape; optional telemetry and evaluations query old names; job/status events share the same sequence and transport; model JSON may contain private reasoning or source excerpts; command pipes may contain credentials despite a restricted environment; output batching must not reorder deltas or lose terminals; a crash can leave active activities that recovery must settle without fabricating success. Do not delete the old event contract until replacement tests cover these consumers and failure paths.
