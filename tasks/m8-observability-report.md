# Milestone 8 — Observability & Streaming

Date: 2026-10-17. Scope: the attached local-side-project M8, following completed
reliability M7. Storage cleanup M9 has not started.

Status: **Complete for the tested local runtime.** Stopped before milestone 9.

## Outcome and architecture

The existing durable timeline records admitted investigation iterations, actual
model/tool dispatch and completion, provider failures, safe retries, evidence
retrieval/delivery/inspection, candidate submission/publication/quarantine,
verification verdicts, stop reasons, acceptance, rendering and finalization.
Random invocation and operation IDs correlate interleaved local work. No model
reasoning, prompts, source bodies, tool arguments/results or raw errors are added.

Exactly seven AI identities remain: Planner, five Specialists and the combined
Synthesizer/Verifier. Orchestration, blackboard, evidence/acceptance gates and
deterministic report rendering retain their existing responsibilities. No agents,
dependencies, brokers, distributed infrastructure or tracing services were added.

## Files and functions

| File / functions | Change |
|---|---|
| `devwatch/review/jobs.py`: `EventKind`, `EventPayload`, `safe_stop_reason`, `JobStore.update_ledger` | 14 additional event kinds; 13 optional bounded metadata fields; fixed classifications; completion events and token settlement share the existing transaction/outbox. |
| `devwatch/review/subgraphs.py`: `_event`, `_invoke`, `_call_model`, `_investigate`, `_call_with_retries`, `_execute_action` | Instrument actual agent/model/tool work, iteration/attempt, duration and charged tokens; distinguish evidence lifecycle; sanitize model stop/finish strings; propagate durable event failures. |
| `devwatch/review/workflow.py`: `reconcile_models`, `_ReviewSession.emit`, agent dispatch/cache paths, `publish`, `structural_gate`, `finalize`, `recover_timeout` | Unknown post-crash calls are reconciled without replay; cached output is marked reused; duplicate agent lifecycle emissions removed; structural rejection is not reported as a success; checkpoint rehydration does not manufacture new findings. |
| `devwatch/review/finalization.py`: `FinalizationWorkflow.run`, `_accept`, `_render` | Actual start/end, acceptance status, rendering outcome and duration, including failure/cancellation. |
| `devwatch/review/observability.py`: `MetadataExporter.export_once` | Existing opt-in export includes allowlisted runtime classifications and random invocation/call IDs. Full review correlation and private identifiers remain local. |
| `devwatch/cli.py`: `events` | JSON-lines replay, `--after`, and `--follow` polling through the owned client API. History is paginated, and disconnect never controls execution. |
| `devwatch/review/client.py`: `ReviewClient.events` | Invalid remote metadata produces a sanitized client error rather than echoing the rejected payload. |
| `scripts/export_review_contracts.py`, browser `wire.ts`, generated schema and fixture | New metadata is optional for upgraded consumers reading older events; regenerate actual service fixtures and validate wire parity. |
| `README.md`, ADR-001 addendum, task ledger/checklist | Document local debugging, correlation/privacy, event semantics, atomic accounting and milestone scope. |

## Tests and metrics

New `tests/test_m8_observability.py`: **21 cases**, covering actual calls/usage,
schema repair, retries without invented iterations, provider failure, budget
refusal, cancellation, evidence stages, failed tools without invented evidence,
candidate quarantine, verification/final acceptance, private export metadata,
paginated CLI replay/cursors, follow/disconnect, live WebSocket activity, SSE replay,
event-store failure, rendering failure, arbitrary model text, malformed remote
events, truncated output, atomic rollback and durable accounting at visibility.

Existing regressions strengthened:

- `test_review_retries.py`: retain bounded-retry assertions and verify attempt
  numbers plus actual call counts alongside the newly added events.
- `test_audit_integration.py`: use delivery/inspection events rather than the
  misleading `file_opened` label for arbitrary evidence pages.
- `test_crash_recovery.py`: actual killed-service resume must record exactly the
  pending operation IDs and corresponding unknown token charges.
- Browser `wire-parity.test.ts`: one new case checks old payloads, current runtime
  metadata and rejection of invalid numeric metadata.

Normal generated service fixture: **46 events, 5 model calls, 1 tool call,
75 scripted provider tokens, 2 delivered and 2 acknowledged evidence pages**.
These are fixture/harness metrics, not a live-model quality/cost benchmark.

Verification results:

- Existing baseline: **34 passed in 30.19s**.
- Expanded observability/recovery gate: **88 passed in 93.94s** before the final
  completion/accounting visibility regression was added.
- Final boundary gate: **38 passed in 72.90s**, including the 21 new cases and
  process-kill/deadline/resume tests. `tasks/evidence/m8-final-boundaries.txt`.
- Frontend: **50 passed**; TypeScript/Vite build passed. Existing Vite plugin
  deprecation notices remain. Latest fixture verification also passed all 50 tests.
- Generated schema freshness and compilation of changed Python files: passed.
- Full backend final gate: **302 passed, 1 existing upstream SDK warning in
  732.03s**, including all 21 new backend cases;
  `tasks/evidence/m8-backend-final.txt`.
  Earlier full suite on the preceding implementation: **301 passed, 1 existing
  upstream SDK warning in 701.73s**. Retained as `tasks/evidence/m8-backend.txt`.
  The final run includes the additional completion/accounting visibility case.

Commands: `.venv/Scripts/python.exe -m pytest -q --tb=short`, focused test paths
listed above, `python scripts/export_review_contracts.py --check`,
`python -m scripts.export_browser_fixture`, and frontend `npm test` / `npm run build`.
Incremental changes are reviewed against `output/m8-baseline/`; prior staged,
unstaged and untracked user work is preserved. No commit, push or deployment.

## Privacy and approval review

Automatic approval review rejected the initial proposal to export hashes derived
from private job/task/evidence identifiers. That patch was not applied. The
implemented alternative keeps those identifiers and their fingerprints local and
exports only existing allowlisted metadata plus random invocation/call IDs. No
external telemetry or live provider request was made during implementation/tests.

## Remaining local limitations

- Optional LangSmith behavior was tested using injected clients, not a live account.
  It remains disabled by default and is not required to debug a complete review.
- The local timeline is the authority for full job/task/evidence correlation.
  Exported metadata deliberately omits that private correlation.
- Abrupt process death can leave an agent span open; the persisted job interruption
  and conservative unknown-call reconciliation explain it. Missing work is not
  fabricated as completed, and unsafe effects are not automatically replayed.
- Evidence inspection means acknowledged receipt, not proof of correct reasoning.
  Verification and final acceptance remain separate gates.
- CLI follow uses bounded-page polling; SSE/WebSocket remain the existing service
  streaming transports. The browser activity panel was not visually redesigned.
- Retention/disk cleanup and performance optimization remain later milestones.

Stop after completing this milestone; do not start M9 automatically.
