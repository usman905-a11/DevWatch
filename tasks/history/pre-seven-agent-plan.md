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

## Frontend remediation plan (2026-09-29)

### Outcome and scope

Make the browser a clear, accessible, report-only review workspace. Users should know whether a review uses a server repository (Git changes when available) or browser-uploaded files (no Git history), see trustworthy progress and report status, inspect evidence and source locations, and never expect DevWatch to edit code. Preserve the existing API and completed M1–M5 work. Implement one frontend phase per user prompt; after its checkpoint passes, stop until the user asks for the next phase. This section is a plan only.

### Current-state findings

| Priority | Evidence | Remediation |
| --- | --- | --- |
| P0 | App offers one Run review action; useCodeReview uploads a selected folder but otherwise sends targetPath or the server's dot path. The modes have different Git semantics. | Make the review source and scope explicit before starting. |
| P0 | useCodeReview keeps issues and partial status but drops the report summary, report ID, evidence, verification rationale, and source range. | Preserve report data in view state and present confirmed findings apart from manual candidates. |
| P1 | App shows a fixed main branch and command-palette text; CodeEditor advertises shortcuts without handlers and uses clickable tab divs. | Replace decorative status with real data and semantic controls. |
| P1 | AgentPanel shows only the latest three progress steps; uploaded reviews show one generic step. Empty and error states lack specific next actions. | Show mode-appropriate progress and distinct clean, empty, partial, failed, and canceled outcomes. |
| P1 | CodeEditor looks editable but is read-only; finding navigation may read from the server after a browser upload. | Name it source preview, resolve files by source mode, and explain missing source. |
| P1 | CSS uses 9–12 px UI text, focuses only finding cards, and animates without a reduced-motion rule. Mobile stacks three panes into a long scroll. | Establish legible tokens, focus and motion rules, and a deliberate narrow-screen workflow. |

These findings come from source inspection. Visual and interaction quality must be checked in a running browser during implementation.

### Design direction

- Use a calm developer workbench centered on review status and source evidence. Keep the useful three-pane relationship on wide screens; make results and source preview navigable views on narrow screens.
- Use restrained dark neutrals, one interaction accent, and severity colors only for actual findings. Use readable UI type and monospace only for paths, code, and metrics. Establish spacing, type, surface, border, and focus tokens.
- Use plain labels: “Review server repository,” “Review uploaded files,” “Confirmed findings,” “Needs manual review,” and “Source preview.” Remove simulated OS chrome, branch names, and shortcuts.
- State that suggestions are guidance and cannot be applied from the browser.

### Phase F1 — Honest review setup

1. **F1.1 Source contract and entry flow.** Model server repository and browser upload as separate review sources in the hook and App. Require an explicit server path or selected folder before enabling Run review; identify Git-change behavior versus uploaded-file behavior. Keep existing REST and WebSocket payloads. Reject an empty upload and show selected file count and omissions.
2. **F1.2 Truthful shell and errors.** Replace fake branch, shortcut, and OS decorations with source name, review scope, and actual state. Surface folder read and API connection failures with a retry action. Keep source selection and review state coherent when a run is replaced or canceled.

**F1 checkpoint:** A user can deliberately start each source mode; an empty workspace never reviews the server's dot path implicitly; uploads are labeled as full-file reviews; repository mode is labeled as Git-aware. Focused state and transport tests plus the frontend build pass. Stop for the next prompt.

**F1 completed (2026-09-30):** Explicit server and browser-folder sources, truthful scope and omitted-file counts, retry and cancel states, and ignored-path filtering are implemented. Frontend: 19 tests and production build passed. Browser fixture checked initial, loading, failure, retry, and canceled server states without contacting the backend; a browser folder selection checked whole-file scope. Stop until F2 is requested.

### Phase F2 — Report comprehension

1. **F2.1 Report overview.** Preserve summary, metrics, source scope, and available report ID in view state. Present counts from confirmed issues only, and separate clean Git diff, no confirmed findings, partial, failed, and canceled outcomes. Keep manual candidates out of confirmed totals.
2. **F2.2 Finding detail.** Present file and source range, severity, verification status and rationale, evidence, confidence when available, and remediation guidance in a readable detail view. Handle absent fields honestly. Keep confirmed and manual-review sections distinct and provide no mutation control.
3. **F2.3 Progress.** Show current review stage and expandable recent history from WebSocket events. For uploaded files, show request-level progress only; do not imply per-agent streaming the endpoint does not provide. Preserve useful progress after partial completion.

**F2 checkpoint:** Fixture tests cover clean, confirmed, manual-only, partial, and failed reports; counts and evidence match the API; report-only tests and frontend build pass. Stop for the next prompt.

**F2 completed (2026-09-30):** The frontend preserves report summary, metrics, source scope, and an available report ID; shows separate clean-Git, empty-source, no-findings, manual-only, partial, failed, and canceled states; exposes source ranges, verification, evidence, confidence, and guidance; and keeps bounded server progress with expandable history. Uploads show request-level progress only. The frontend suite passed 28 tests and the production build passed. An isolated browser fixture checked report ID, counts, evidence, history, partial failures, and stale-report clearing without contacting the backend.

**F2 ruling:** The API has no explicit clean-Git outcome field, so the UI recognizes the backend's current clean-Git summary text. A backend wording change would require this classification to be updated. The upload endpoint returns no report ID, so the UI omits that field for uploads.

### Phase F3 — Source inspection and navigation

1. **F3.1 Explorer and tabs.** Make folder expansion, file selection, tab selection, and close actions semantic, keyboard operable, and visibly focused. Label the code pane as a read-only source preview. Remove inactive shortcut prompts.
2. **F3.2 Finding-to-source route.** Open the exact file and line range from a finding, including duplicate basenames. Use uploaded content for upload reviews and server reads for server reviews. Show a specific fallback when source is omitted or unavailable; never silently display placeholder text as code. Keep large-file rendering responsive.

**F3 checkpoint:** Keyboard-only navigation works across explorer, tabs, findings, and source; matching paths land at the right line; missing and large files have useful states; focused tests and build pass. Stop for the next prompt.

**F3 completed (2026-09-30):** Folder and source-tab controls use labeled native buttons with active and expanded states, keyboard focus, and a read-only source preview. Findings resolve exact file paths and ranges through the chosen review mode. Uploaded files never trigger server reads; server files use explicit repository paths. Missing, omitted, and read-failed content displays a specific unavailable state. Large files render a bounded line window. The frontend suite passed 36 tests and the production build passed. An isolated Chrome fixture verified keyboard navigation and source scrolling, duplicate-basename findings, missing-source states, source-mode routing, and a 600-line file without contacting the backend.


### Phase F4 — Visual system and inclusive validation

1. **F4.1 Visual consolidation.** Refactor CSS into a small token system and remove dead quick-fix styles, duplicate font loading, and decoration that implies unavailable capabilities. Raise small-text legibility and distinguish primary actions, report status, and evidence hierarchy.
2. **F4.2 Responsive and accessibility pass.** Provide a skip link, labels for icon controls, visible keyboard focus, sensible touch targets, wrapping for long paths, reduced-motion behavior, and narrow-screen navigation among review, files, and source. Check contrast and 200% zoom.
3. **F4.3 Browser acceptance.** Exercise both review modes and clean, findings, manual-only, partial, error, and canceled states at desktop and mobile widths. Validate keyboard flow and screen-reader announcements. Run frontend tests and build. Check protected-API behavior; if browser WebSocket authentication needs a backend contract change, document that limitation and scope it separately before claiming protected-mode support.

**F4 checkpoint:** Browser captures and test results demonstrate the states, responsive layout, and keyboard access; no fake or write actions remain; frontend tests and build pass. Stop and report final results.

**F4 completed (2026-09-30):** The review workspace now uses one dark color/type/spacing token system, a single font load, readable metadata, severity-specific finding colors, and no obsolete quick-fix styling. Mobile widths use Review, Files, and Source sections; opening a finding moves focus to the source, while choosing a new review source returns to Review. The UI has a skip link, named icon controls, visible focus, polite review status, and reduced-motion handling. Browser checks covered 320, 390, 720, 768, 1024, and 1440 CSS-pixel widths, a 200%-zoom-equivalent narrow viewport, all required review states, keyboard navigation, and the accessibility tree. Isolated report fixtures produced the [desktop](evidence/f4-desktop.png), [mobile results](evidence/f4-mobile.png), and [mobile source](evidence/f4-mobile-source.png) captures. A running local FastAPI fixture exercised the real WebSocket review, upload POST, and server file-read routes without invoking an LLM; [backend integration capture](evidence/f4-backend-integration.png). The frontend suite passed 38 tests, the production build passed, and 14 backend transport tests passed with workspace-local pytest temporary files.

**Protected deployment dependency (separate transport work):** [frontend/src/services/api.ts](../frontend/src/services/api.ts) currently uses fixed localhost API/WebSocket URLs and sends no authentication header for REST calls. The production backend requires `x-api-key` or `Authorization` before accepting `/ws/review`, while the browser [WebSocket constructor](https://websockets.spec.whatwg.org/#the-websocket-interface) accepts a URL and optional protocols, with no custom-header option. A process-local fixture key confirmed REST rejects missing credentials with 401, WebSocket rejects them with code 4001, and a non-browser client with the header connects. Protected browser review therefore needs a same-origin authenticated session or backend-for-frontend transport, with origin and CSRF controls and configurable endpoints, followed by a protected-browser integration test. Do not put a secret in a URL or persistent browser storage. Protected browser mode is not claimed as supported by F4.


### Dependencies and boundaries

F1 -> F2 -> F3 -> F4 -> F5. UI work may add focused frontend tests, but does not change review verdicts, backend evidence rules, or reviewed source files. Server repository reviews and browser uploads retain distinct behavior. The browser WebSocket constructor cannot supply the API key header required by a protected backend; resolve the deployment contract explicitly, with no secret in a URL or persistent browser storage. Browser acceptance requires a running backend and representative fixture reports.

### Phase F5 — Live agent activity

1. **F5.1 Safe activity contract.** Extend the existing progress event with an additive activity kind plus optional repository-relative file path and canonical tool name. Normalize separators and reject absolute or parent-traversal paths. Activity events never contain file contents, prompts, tool arguments, tool output, credentials, or raw exception data.
2. **F5.2 Truthful execution instrumentation.** Emit file-scan events when the engine reads review or context files and tool-call events immediately before deterministic tools, configured command runners, and language-model agents execute. Keep the existing stage lifecycle events. Stream repository and browser-upload reviews through the same WebSocket contract while preserving the upload REST endpoint.
3. **F5.3 Activity timeline.** Show the active agent, scanned file, and invoked tool in a bounded, readable timeline. Keep one polite current-status announcement and expose history without repeatedly announcing every historical row. Cancellation, stale-run protection, completion, and failure behavior remain intact for both source modes.

**F5 checkpoint:** Contract and transport tests prove safe metadata, ordering, upload streaming, cancellation, and backward compatibility. Frontend tests and build pass, and a running-browser fixture demonstrates repository and uploaded-file activity. Stop and report results before starting another phase.
**F5 completed (2026-10-01):** The existing progress stream now carries additive stage, file-scan, and tool-call activity with normalized repository-relative paths and canonical tool names. The engine emits events at real scanner, static-analysis, configured-command, planner, specialist, deduplication, and verification boundaries without adding file content, prompts, arguments, or output to activity metadata. Repository and browser-upload reviews use the same cancellable WebSocket flow; the upload REST endpoint remains compatible. The frontend presents the active agent plus file/tool metadata in a 100-event accessible timeline. Backend graph/transport gate: 53 passed. Frontend: 40 tests passed and the production build passed. Headless Chrome exercised both source modes with a local WebSocket fixture and produced [repository activity](evidence/f5-server-agent-activity.png) and [uploaded activity](evidence/f5-upload-agent-activity.png) captures without browser exceptions.