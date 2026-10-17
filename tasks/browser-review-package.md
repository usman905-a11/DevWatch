# Browser durable transport review package

Spec: tasks/seven-agent-design.md; ledger: tasks/progress.md (Browser continuation).
Scope: frontend/src/review/{durable-client,durable-events,wire,wire-hashes}.ts,
wire-schema.json; scripts/export_review_contracts.py, export_browser_fixture.py;
frontend/src/__tests__/{durable-client,durable-events,wire-parity}.test.ts and
fixtures/canonical-wire.json. New files; existing shared dirty work is outside scope.

Contracts: exactly seven agent identities; no compatibility report adapter, private
reasoning, source writing or model-generated publication. Jobs belong to service,
not client. Same snapshot/scope/key for submission retries, no blind replay of
unknown POSTs. Separate explicit resume/cancel. Completion must precede report
acceptance/rendering. Client gets finalized report, never drives LLM publishing.
Keys only memory/header, no URL/build/local-storage secret. SSE fetch headers and
last cursor, metadata schema, source/job ownership checks, safe bounded payloads.

Review focus: input URLs/headers/path/identity; generated JSON Schema coverage and
custom validators; malformed/partial fields and Unicode semantics; source hashes
and scope/ranges; request/stream byte/time bounds; readers/timers/listeners drained
on stop/disconnect/expiry; callback errors/async behavior; reconnect only reads,
duplicates and cursor commit; terminal status/report/failed/interrupted; no hidden
cancel or new intent. Inspect concrete bugs; don't run code/provider/network or
edit files. One independent review, root will make one RED->GREEN fix pass.

Verification before review: frontend baseline 40, new full 58 passes, TS/Vite build;
backend schema check passes, actual ASGI fixture producer finishes accepted job.
No UI consumer cutover yet. Source review concerns about missing UI wiring are
known sequencing, not permission to delete legacy consumers prematurely.
