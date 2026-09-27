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

M1 and M2 are complete. M3 is the next phase and must wait for a new user prompt. `AGENTS.md` is untracked user work and must remain untouched. No commit, push, deployment, or external publication is part of these milestones.

## Codebase audit (2026-09-27)

| Milestone | Status | Evidence and remaining work |
|---|---|---|
| M1 | Complete | Public/internal models, engine methods, dependency ranges plus `constraints.txt`, and 20 versioned mixed evaluation cases exist. Focused checks: 13 passed; `pip check` clean. The final precision/recall target still belongs to M5. |
| M2 | Complete | Distinct current-source hunks, Python absolute/relative and frontend script imports/dependents/tests, scanner exclusions, full bounded command snapshots, bounded UTF-8 output, executable/path controls, secret stripping, timeout process-tree termination, and recursion control were verified. Focused gate: 44 passed, 2 skipped. |
| M3 | Implemented in part, unaccepted | Graph routing, strict gate, and SQLite checkpoints exist. Resume without repeated side effects, cancellation, stream metadata, deterministic parallel merge, and SQLite worker cleanup need explicit evidence. A warnings-as-errors full run exposed an event-loop-closed SQLite worker warning. |
| M4 | Implemented in part, unaccepted | Compatibility pipeline and `410` routes exist; transport and frontend tests pass. Confirm WebSocket disconnect cleanup, report storage parity, and visible manual-review candidates before closing. |
| M5 | Pending | Legacy removal, documentation, resource cleanup, budget checks, integrated evaluation threshold, and final acceptance remain. |

Initial audit commands: `python -m pytest -q` produced 157 passed, 1 skipped, and 1 subprocess decoding warning; `npm test -- --run` produced 3 passed; `npm run build` succeeded. After M2, `python -m pytest -q` produced 171 passed and 2 skipped. A separate warnings-as-errors run exposed an intermittent SQLite worker warning assigned to M3.

## Remaining execution order and stop rule

1. **M2 evidence collection: complete.** Changed-line mapping, bounded context, disposable snapshots, and runner controls passed the focused gate. **Stopped.**
2. **M3 graph workflow: next prompt.** Close resume, cancellation, streaming, deterministic merge, SQLite cleanup, and partial-failure gaps. Verify fake-provider and checkpoint tests. **Stop.**
3. **M4 interface migration:** prove legacy transport/storage/auth/rate-limit parity, WebSocket cleanup, manual-candidate UI, and report-only routes. Verify backend and frontend checks. **Stop.**
4. **M5 removal and acceptance:** remove obsolete paths after parity, document lifecycle and containment, run full checks and integrated evaluation at the specified thresholds. **Stop.**
