# DevWatch LangGraph refactor: milestone plan

## Goal

Replace the custom review orchestrator with a local, diff-first LangGraph workflow. Preserve the existing review interfaces, require strict evidence before confirming LLM findings, and make the product report-only.

This document is the staged execution of the supplied refactor plan. Some later-stage code already exists in the shared worktree. Preserve it; implementation presence or a green general test run does not close an acceptance criterion. Complete exactly one remaining milestone per user prompt, then stop until the user explicitly asks to continue.

## Architecture decisions

- `ReviewEngine` owns review execution. `ReviewPipeline` is a compatibility facade until parity is proven.
- LangGraph state holds typed metadata, artifact paths and hashes, tasks, findings, and failures. Source contents live under `.devwatch/runs/{job_id}`.
- Repository reviews target Git changes; uploaded and single-file reviews bypass Git. Static tools and tests are deterministic.
- One planner routes work to four specialist roles. A verifier decides which candidates pass the strict gate. Report rendering is deterministic.
- Commands use an exact, predefined argv allowlist in a disposable snapshot. The runner is containment, not a security boundary.

## Milestones and acceptance gates

### M1 — Contracts and evaluation foundation

Define the public and internal models, package dependencies, engine interface, and a versioned offline suite with at least 20 clean and buggy cases. Existing CLI/REST/WebSocket payloads must remain compatible. Focused contract and evaluation tests pass. Stop for approval.

### M2 — Evidence collection

Collect staged, unstaged, and untracked changed regions; select directly related dependency/test context; create disposable snapshots; and run only bounded configured commands. Clean Git trees return an explanatory empty report. Focused Git, artifact, runner, and workspace-integrity tests pass. Stop for approval.

### M3 — LangGraph review workflow

Run planner, relevant specialists via `Send`, deduplication, file-based verification, strict gate, and deterministic report. Add reducers, SQLite checkpoints, custom progress events, cancellation, and partial-failure behavior. Fake-provider tests prove routing, merge determinism, suppression, and resume. Stop for approval.

### M4 — Interface migration and report-only product

Delegate legacy pipeline calls to the engine. Preserve CLI, REST, report storage, auth, rate limits, and WebSocket events. Expose progress and manual-review candidates in the frontend. Mutation endpoints return `410 Gone`, and quick-fix controls are removed. Transport and frontend tests/build pass. Stop for approval.

### M5 — Removal, hardening, and final acceptance

Remove obsolete orchestration and mutation internals after parity. Document configuration, containment limits, and retention. Verify cleanup and budgets. Run the full backend/frontend/type/build suites and the 20-case evaluation; require confirmed-finding precision at least 90% and recall at least 70%. Stop and present final results.

## Dependencies and risks

M1 → M2 → M3 → M4 → M5. The main risks are unsafe command execution, source text leaking into checkpoints, false-positive confirmed findings, and legacy transport regressions. Each milestone's focused tests guard those risks before the next begins.

## Current checkpoint

M1 through M5 are complete. The staged refactor is finished; no further phase starts automatically. Preserve unrelated user work. No commit, push, deployment, or external publication is part of these milestones.

## Codebase audit (2026-09-27)

| Milestone | Status | Evidence and remaining work |
|---|---|---|
| M1 | Complete | Public/internal models, engine methods, dependency ranges plus `constraints.txt`, and 20 versioned mixed evaluation cases exist. Focused checks: 13 passed; `pip check` clean. The final precision/recall target still belongs to M5. |
| M2 | Complete | Distinct current-source hunks, Python absolute/relative and frontend script imports/dependents/tests, scanner exclusions, full bounded command snapshots, bounded UTF-8 output, executable/path controls, secret stripping, timeout process-tree termination, and recursion control were verified. Focused gate: 44 passed, 2 skipped. |
| M3 | Complete | Assigned specialist routing, bounded deterministic reducers, source-snippet-free checkpoints, strict source verification, partial reports, SQLite resume, progress metadata, and cancellation passed focused tests (36 passed with warnings as errors). Full backend suite: 189 passed, 2 skipped. |
| M4 | Complete | CLI/REST/WebSocket compatibility, shared report lookup, auth and rate limits, quiet disconnect cleanup, discoverable report-only `410` mutation routes, progress, and manual-review candidates verified. Focused backend: 54 passed with warnings as errors. Frontend: 10 passed; TypeScript/build passed. |
| M5 | Complete | Removed patcher operations, the scanner write method, mutation request models, and mutation audit helpers; documented report-only operation, command containment, and artifact/checkpoint/report lifecycle. The full backend suite passed (194 passed, 3 skipped), frontend tests passed (10) and TypeScript/build passed. The real 20-case changed-repository offline gate scored 100% precision and 80% recall (8 TP, 0 FP, 2 FN). The 5,050-file timing gate passed in the full suite; an isolated run after concurrent line counts took 13.13 seconds. Limits and cleanup checks passed. Live-model accuracy remains unmeasured; the real symlink test skipped on this Windows host, while boundary simulation tests passed. |

Initial audit commands: `python -m pytest -q` produced 157 passed, 1 skipped, and 1 subprocess decoding warning; `npm test -- --run` produced 3 passed; `npm run build` succeeded. After M2, `python -m pytest -q` produced 171 passed and 2 skipped. A separate earlier warnings-as-errors run exposed an intermittent SQLite worker warning; the M3 focused warnings-as-errors run now passes.

## Remaining execution order and stop rule

1. **M2 evidence collection: complete.** Changed-line mapping, bounded context, disposable snapshots, and runner controls passed the focused gate. **Stopped.**
2. **M3 graph workflow: complete.** Resume, cancellation, streaming, deterministic merge, SQLite cleanup, and partial-failure cases passed focused checks. **Stopped.**
3. **M4 interface migration: complete.** Legacy transport/storage/auth/rate-limit parity, WebSocket cleanup, manual-candidate UI, and report-only routes passed focused backend and frontend gates. **Stopped.**
4. **M5 removal and acceptance: complete.** Obsolete mutation paths were removed; lifecycle and containment are documented; full checks and integrated offline evaluation passed. **Stopped.**
