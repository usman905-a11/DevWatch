# DevWatch seven-agent implementation checklist

## Current local plan: M8 Observability & Streaming (2026-10-17)

- [x] Add bounded event metadata and actual model/retry instrumentation.
- [x] Verify lifecycle, iteration, evidence, candidate, verification and finalization events.
- [x] Add random invocation/call export correlation and local CLI event observation; keep private review correlation local.
- [x] Verify replay/SSE/WebSocket, refresh consumer contracts and run full checks.
- [x] Review, write M8 report and stop before storage cleanup M9.

## Current local plan: M7 Reliability & Recovery (2026-10-17)

- [x] Reproduce and fix bounded tool feedback/context timeout gaps.
- [x] Reproduce and fix specialist isolation and resumed coverage gaps.
- [x] Verify existing schema/provider/budget/deadline/cancellation/crash recovery.
- [x] Run full backend regression, review changes and write M7 evidence report.
- [x] Stop after M7; do not start observability/streaming M8.

The historical M7/M8 entries below use a different, superseded milestone sequence.

## Audit reliability fixes (2026-10-15)

- [x] A1: role-specific runtime catalogue and shared argument validation.
- [x] A2: bounded evidence retrieval and distinct evidence lifecycle receipts.
- [x] A3: enforced verifier inspection and scoped verifier evidence provenance.
- [x] A4: independent candidate quarantine and publication.
- [x] A5: consistency checks, bounded repair and preserved verified partial reports.
- [x] A6: complete prompt/output admission, candidate bounds and verification batches.
- [x] A7: integrated pipeline, regression verification and exact change report.

- [x] M0: executable seven-agent contracts, final schemas/prompts, Balanced limits and dependency tooling.
  - [x] Contracts/permission/budget gates and generated transport-schema freshness.
  - [x] Two clean Windows x64/Python 3.11 installs, complete hash-checked dependency closure and installed-wheel verification.
- [x] M1: durable jobs, immutable snapshots, five stores, outbox, replay/reconnect, cancellation/resume, ownership.
  - [x] Real process-kill recovery, live-worker exclusion and explicit resume with snapshot/checkpoint/intent/accounting continuity.
  - [x] Remote cancellation/publication serialization and drained checkpoint writers through repeated cancellation.
  - [x] Resilient maintenance, indexed active batches and bounded in-memory job admission.
- [x] M2: Python/JS/TS intelligence/cache, selective context, permissioned tools and trusted execution.
- [x] M3: seven-agent LangGraph, iterative subgraphs, cumulative budgets, gates and bounded follow-up.
  - [x] Planner and combined Verification/Synthesis execution, with five iterative specialist subgraphs.
  - [x] Canonical root graph, scoped evidence/blackboard and completion-first deterministic report tail.
  - [x] Persisted accounting and graceful resume of agent phase and admitted follow-up.
  - [x] Classified bounded retries, mandatory-agent partial reports and deadline recovery.
  - [x] Remaining failure recovery and full runtime/tool integration gates.
- [x] M4: migrate CLI/web to jobs, immutable source, structured reports and streaming.
  - [x] Runnable canonical FastAPI service: owned jobs/snapshots/reports/source, persistent SSE/WS and cancel/resume.
  - [x] CLI cutover to durable jobs, bounded immutable capture, honest omission coverage and JSON/Markdown reports.
  - [x] Browser canonical client/schema, immutable source retrieval and authenticated SSE replay foundation.
  - [x] Frontend job/session/report/source cutover with real-browser parity and obsolete frontend transport removal.
    - [x] Final review regressions: unknown submission guards, cleared folder on job attachment and short-screen recovery.
  - [x] Deterministic accepted-only PDF artifacts and service/CLI/web downloads with layout/browser verification.
  - [x] Canonical CLI watch with debouncing, one active job, coalesced edits, exact intents and deletion coverage.
    - [x] Final review regressions: retained deletion history after omissions and explicit coverage when the omission list is full.
  - [x] Remaining full cutover parity.
- [x] M5: cut over and remove legacy after migration checks.
- [x] M6: full regression and 60-case quality evaluation; live accuracy separately measured.
- [ ] M7: VS Code then JetBrains clients.
- [ ] M8: optional integration and PostgreSQL/Redis adapters.

See [progress.md](progress.md) for completed slices within each milestone.
