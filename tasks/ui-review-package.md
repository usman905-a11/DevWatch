# Canonical frontend cutover review package

Authority: tasks/seven-agent-design.md and the user's instruction to continue the
remaining plan. Ledger: tasks/progress.md. Exactly seven identities, unchanged
budgets/tools/storage/gates. Scope is this frontend migration, not unrelated dirty
work or a repeat review of the completed core/service/CLI slices.

Inspect frontend/src/review/{DurableApp,ReportPanel,SnapshotSource,JobActivity}.tsx,
useReviewSession.ts, review-session.ts, folder-capture.ts; the snapshot method,
default fetch closure and expected-manifest dictionary in durable-client.ts;
App.tsx entry cutover, FileExplorer type cleanup, index.css additions; owned
GET /api/jobs/{identity}/snapshot in service.py and its two tests. Test scripts:
scripts/ui_fixture_service.py and scripts/test_durable_ui.py. New/ported tests:
durable-app, durable-session, browser-capture, canonical-panels, quickfix,
workspace-access-f4, source-ui-f3 and the client/event regressions.

Old frontend socket/API/types/hook/three-role panel/source helpers and their
schema-specific tests were removed only after canonical unit/integration/browser
parity. Fifteen files are archived as non-executable history ZIP. FileExplorer
remains; source excerpts replace the old full-file editor. No compatibility adapter.
Browser supports device-folder capture and reopening CLI-created Git jobs; no
server-filesystem path read API is added. Watch/PDF remain pending milestone work.

Review focus: operation and navigation races, stale observers, StrictMode cleanup,
unknown POST outcomes and exact retry intents, explicit cancel/resume versus view
disposal, reconnect cursors/history, completed-only reports, source ranges/hashes,
credential lifetime/config changes, browser fetch semantics, dangerous filenames,
UTF-8/BOM, upload/catalog limits, omission coverage, report grouping and escaping,
download behavior, short/narrow viewport accessibility, new catalog ownership.
Check concrete regressions rather than re-reviewing unaffected backend algorithms.

Verification: 44 canonical/current frontend tests pass after removing obsolete
schema tests (74 before removal); TS/Vite build passes. Backend 371 passed with
three existing Windows symlink skips. Real Chrome + actual ASGI graph/stores and
scripted provider prove capture, detach/reopen, source, JSON/Markdown downloads,
320/768/1024/1440 widths. Existing remote font request is blocked in sandbox;
no application exception, live provider or production readiness is inferred.

Source-only independent review: do not edit, run code, invoke providers/network,
or delegate. One final review, then one RED->GREEN fix pass for required findings.
Earlier trailing-newline finding was disproved by actual Node/Pydantic execution:
both reject without production changes; do not repeat that unsupported claim.
