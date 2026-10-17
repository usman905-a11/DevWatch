# DevWatch LangGraph refactor tasks

Complete one milestone, report its verification, and wait for the user's go-ahead before starting the next.

## M1 — Contracts and evaluation foundation

### Task 1.1 — Freeze review contracts

**Description:** Keep `CodeIssue` and `ReviewReport` backward compatible while adding structured evidence, verification, manual-review, and metrics fields. Define typed internal review models and the `ReviewEngine` methods.

**Acceptance criteria:**
- [x] Existing model and transport fields remain valid.
- [x] New fields and typed task/evidence models validate expected and invalid inputs.
- [x] Repository, uploaded-file, and single-file engine methods are callable.

**Verification:** `pytest tests/test_models.py tests/test_review_contracts.py -q`.

**Dependencies:** None. **Scope:** Medium. **Files:** `devwatch/models.py`, `devwatch/review/models.py`, `devwatch/review/engine.py`, `tests/test_review_contracts.py`.

### Task 1.2 — Pin framework dependencies

**Description:** Declare the LangGraph and SQLite-checkpoint release families and keep install resolution reproducible.

**Acceptance criteria:**
- [x] `pyproject.toml` declares both compatible dependency ranges.
- [x] A dependency lock or constraints artifact records resolved versions.
- [x] Installed package imports and a minimal graph/checkpointer test pass.

**Verification:** `python -m pip check` and `pytest tests/test_langgraph_review_engine.py::test_engine_persists_graph_checkpoints_to_sqlite -q`.

**Dependencies:** 1.1. **Scope:** Small. **Files:** `pyproject.toml`, dependency lock/constraints artifact.

### Task 1.3 — Build the versioned offline evaluation set

**Description:** Add at least 20 mixed clean/buggy review cases with expected findings and a deterministic evaluator.

**Acceptance criteria:**
- [x] At least 20 labeled cases are versioned and include clean and buggy changes.
- [x] The evaluator reports precision and recall, including a silent-reviewer failure case.
- [x] The evaluator does not call a live provider or rewrite tracked result files during tests.

**Verification:** `pytest tests/test_eval_baseline.py tests/test_review_evaluation.py -q`.

**Dependencies:** 1.1. **Scope:** Medium. **Files:** `tests/test_review_evaluation.py`, `tests/fixtures/review_eval_v1.json`, existing evaluation tests as needed.

### M1 checkpoint

- [x] Tasks 1.1–1.3 pass their focused checks (13 tests; `pip check` clean on 2026-09-27).
- [x] Review the diff for accidental changes to contracts or fixtures.
- [x] M1 was already implemented when this audit began; M2 is the first remaining phase requested by the user.

## M2 — Evidence collection

### Task 2.1 — Git diff and context

**Description:** Preserve distinct staged, unstaged, and untracked changed ranges and select bounded direct imports, dependents, symbols, and tests without widening review targets.

**Acceptance criteria:**
- [x] Changed line mapping covers staged, unstaged, untracked, distant, deleted, Unicode, and clean-tree cases.
- [x] Related import, symbol-definition, dependent, and test context is bounded; changed targets remain distinct.
- [x] Uploaded and single-file paths bypass Git discovery.

**Verification:** `pytest tests/test_review_evidence.py -q`.

**Dependencies:** M1. **Scope:** Medium. **Files:** `devwatch/review/evidence.py`, `devwatch/review/engine.py`, tests.

### Task 2.2 — Snapshot and restricted runner

**Description:** Copy bounded review inputs into disposable run artifacts and execute fixed manifest/TOML argv commands with environment, path, timeout, and output controls.

**Acceptance criteria:**
- [x] Runner rejects unknown executables, shell syntax, package installs, traversal, and symlink escapes (symlink test skipped where Windows disallows creation; path resolution was reviewed).
- [x] Timeout kills the process tree; output is captured within a byte cap; secrets are stripped and command recursion is disabled in children.
- [x] Original workspace is unchanged, expanded snapshots obey file limits, and artifact retention is bounded.

**Verification:** `pytest tests/test_review_evidence.py tests/test_sandbox.py -q`.

**Dependencies:** 2.1. **Scope:** Medium. **Files:** `devwatch/review/runner.py`, `devwatch/config.py`, tests.

### M2 checkpoint

- [x] Evidence, tools, and clean Git review tests pass: 44 passed, 2 skipped on 2026-09-27.
- [x] Runner proves bounded capture while the child runs, UTF-8-safe decoding, path controls, and workspace integrity.
- [x] Report completion and wait for the user's decision before M3.

## M3 — LangGraph review workflow

### Task 3.1 — Graph state and routing

**Description:** Wire typed state, reducers, planner, relevant specialist `Send` branches, and bounded concurrency.

**Acceptance criteria:**
- [x] Only assigned specialists execute.
- [x] Parallel candidates/failures merge deterministically within budgets.
- [x] Source contents are absent from checkpoints.

**Verification:** `pytest tests/test_langgraph_review_engine.py tests/test_review_agents.py -q`.

**Dependencies:** M2. **Scope:** Medium. **Files:** `devwatch/review/state.py`, `devwatch/review/agents.py`, `devwatch/review/engine.py`, tests.

### Task 3.2 — Verification and reporting

**Description:** Deduplicate candidates, verify in file batches, apply the strict gate, and render reports deterministically.

**Acceptance criteria:**
- [x] Confirmed findings have valid location/hash, `ACCEPTED`, and confidence ≥ 0.8.
- [x] Uncertain high-risk candidates are separate; unavailable verification suppresses LLM-only candidates.
- [x] Planner/specialist/verifier failures produce partial reports with retained conclusive tool evidence.

**Verification:** `pytest tests/test_langgraph_review_engine.py tests/test_pipeline_resilience.py -q`.

**Dependencies:** 3.1. **Scope:** Medium. **Files:** `devwatch/review/engine.py`, `devwatch/review/reporting.py`, tests.

### Task 3.3 — Resume and progress

**Description:** Persist graph checkpoints, stream node/custom events, and support cancellation without repeating completed side effects.

**Acceptance criteria:**
- [x] A resumed job reuses completed checkpointed stages.
- [x] Progress includes node/specialist, elapsed time, tool evidence, token usage, and suppressed counts.
- [x] Cancellation closes tasks and resources.

**Verification:** Targeted checkpoint, streaming, and cancellation tests.

**Dependencies:** 3.2. **Scope:** Medium. **Files:** `devwatch/review/engine.py`, `devwatch/review/state.py`, tests.

### M3 checkpoint

- [x] Focused graph tests pass (36 passed with warnings as errors); full backend suite passes (189 passed, 2 skipped) on 2026-09-27. Report completion and wait for the user's next-phase prompt.

## M4 — Interface migration and report-only product

### Task 4.1 — Review transports

**Description:** Delegate `ReviewPipeline` through the engine and preserve CLI, REST, report storage, auth, rate limits, and WebSocket shapes.

**Acceptance criteria:**
- [x] Existing review commands/endpoints and report lookup remain functional.
- [x] WebSocket progress/completion and disconnect cleanup work.
- [x] No second report database is introduced.

**Verification:** Focused CLI, server, auth, storage, and WebSocket tests.

**Dependencies:** M3. **Scope:** Medium. **Files:** `devwatch/pipeline/dag.py`, routers, operations, tests.

### Task 4.2 — Report-only frontend and endpoints

**Description:** Remove quick-fix controls, show report progress/manual candidates, and retire mutation routes with `410 Gone`.

**Acceptance criteria:**
- [x] Mutation routes remain discoverable and never change files.
- [x] Frontend has no mutation action and displays review status.
- [x] Frontend tests, type-check, and build pass.

**Verification:** `pytest tests/test_phase6.py -q`, `npm test`, `npm run build` in `frontend`.

**Dependencies:** 4.1. **Scope:** Medium. **Files:** routers, frontend components/hooks/types, tests.

### M4 checkpoint

- [x] Transport and frontend gates passed on 2026-09-28: 54 focused backend tests with warnings as errors, 10 frontend tests, and TypeScript/build. Stop until the user requests M5.

## M5 — Removal, hardening, and final acceptance

### Task 5.1 — Remove obsolete execution paths and document operation

**Description:** Remove unused custom orchestration and mutation internals after parity, then document config, containment limits, and retention.

**Acceptance criteria:**
- [x] No active route or engine path can mutate reviewed code.
- [x] README/config examples describe the new workflow and limits.
- [x] Generated artifacts and checkpoints have clear lifecycle rules.

**Verification:** Search active call sites, run focused compatibility tests, inspect diff.

**Dependencies:** M4. **Scope:** Medium. **Files:** legacy modules, `README.md`, `.env.example`, tests.

### Task 5.2 — Run acceptance gates

**Description:** Evaluate precision, recall, resource budgets, cleanup, and complete backend/frontend parity.

**Acceptance criteria:**
- [x] ≥20 cases, precision ≥90%, recall ≥70%.
- [x] File/token/command/concurrency budgets hold.
- [x] Backend tests, frontend tests/type-check/build pass with no unexplained regressions.

**Verification:** Full `pytest -q`; evaluation command; `npm test` and `npm run build` in `frontend`.

**Dependencies:** 5.1. **Scope:** Medium. **Files:** evaluation fixtures/tests and any discovered fixes.

### M5 checkpoint

- [x] Final gate passed on 2026-09-28: 194 backend tests passed, 3 skipped; 10 frontend tests and TypeScript/build passed; 20-case integrated offline precision 100%, recall 80%; 5,050-file benchmark passed in 13.13 seconds after the collector fix. Report limitations and changed files to the user.

## Frontend remediation — planned (2026-09-29)

The completed M1–M5 checklist above remains the refactor record. Execute exactly one F phase per user prompt, verify its checkpoint, then stop. F1-F4 are complete. The protected deployment transport dependency is recorded in tasks/plan.md.

### F1 — Honest review setup

#### F1.1 — Explicit review source

**Description:** Give users separate server-repository and browser-folder review entry paths. Show source scope, file count, and omitted files before dispatch.

**Acceptance criteria:**
- [x] Run review requires an explicitly chosen source; an empty workspace does not silently review the server's dot path.
- [x] Server mode explains Git-change review; upload mode explains whole-file review without Git metadata.
- [x] Empty or unreadable folder selections produce a visible, actionable state.

**Verification:** Focused hook and App tests for both modes and empty input; frontend build.

**Dependencies:** None. **Scope:** Medium. **Files:** frontend/src/App.tsx, frontend/src/hooks/useCodeReview.ts, frontend/src/services/api.ts, focused tests.

#### F1.2 — Truthful shell and run state

**Description:** Replace simulated OS controls, fixed branch, and inactive shortcuts with real source and run status. Show retryable folder and connection errors.

**Acceptance criteria:**
- [x] No displayed branch, shortcut, or control claims an unavailable capability.
- [x] Replacing or canceling a run clears stale results and keeps its source label correct.
- [x] User-facing errors identify the failed action and a next step.

**Verification:** App and run-lifetime tests; browser check of initial, loading, failure, and canceled states; frontend build.

**Dependencies:** F1.1. **Scope:** Medium. **Files:** frontend/src/App.tsx, frontend/src/components/CodeEditor.tsx, frontend/src/hooks/useCodeReview.ts, focused tests.

#### F1 checkpoint

- [x] Both input modes start deliberately and display the correct scope.
- [x] Focused tests and frontend build pass.
- [x] Report results and stop until the user requests F2.

### F2 — Report comprehension

#### F2.1 — Preserve and present report overview

**Description:** Retain summary, metrics, source scope, and report ID in view state and distinguish clean, empty, partial, failed, and canceled outcomes.

**Acceptance criteria:**
- [x] Confirmed counts come only from confirmed issues; manual candidates have separate counts.
- [x] A clean Git diff is explained separately from a review with no confirmed findings.
- [x] Report summary and available report ID are visible without showing stale data from a prior run.

**Verification:** Fixture-based report mapping and panel tests; frontend build.

**Dependencies:** F1. **Scope:** Medium. **Files:** frontend/src/types/index.ts, frontend/src/hooks/useCodeReview.ts, frontend/src/components/AgentPanel.tsx, focused tests.

#### F2.2 — Evidence-led finding detail

**Description:** Let users inspect a finding's location, verification, evidence, and remediation guidance while keeping manual candidates separate.

**Acceptance criteria:**
- [x] Detail view shows source range, verification/rationale, and evidence only when supplied by the API.
- [x] Manual candidates are visibly uncertain and excluded from confirmed totals.
- [x] No action applies or proposes a file mutation.

**Verification:** Render tests with complete and sparse finding fixtures; report-only regression test; frontend build.

**Dependencies:** F2.1. **Scope:** Medium. **Files:** frontend/src/types/index.ts, frontend/src/components/AgentPanel.tsx, frontend/src/hooks/useCodeReview.ts, focused tests.

#### F2.3 — Honest progress history

**Description:** Present the active stage and a bounded, expandable history from server streams; show request-level status for uploads.

**Acceptance criteria:**
- [x] WebSocket updates retain their real agent, status, message, and available timing information.
- [x] Upload mode does not imply live specialist events.
- [x] Partial completion retains useful history and explains failed stages.

**Verification:** Progress-state and panel tests using WebSocket and upload fixtures; frontend build.

**Dependencies:** F2.1. **Scope:** Medium. **Files:** frontend/src/hooks/useCodeReview.ts, frontend/src/components/AgentPanel.tsx, frontend/src/types/index.ts, focused tests.

#### F2 checkpoint

- [x] Clean, confirmed, manual-only, partial, failed, and canceled fixtures render accurately.
- [x] Focused tests, report-only tests, and frontend build pass.
- [x] Report results and stop until the user requests F3.

### F3 — Source inspection and navigation

#### F3.1 — Accessible explorer and source tabs

**Description:** Make file tree and tab interactions semantic and keyboard operable; present source as read-only.

**Acceptance criteria:**
- [x] Folder expand, file select, tab select, and close are buttons or equivalent accessible controls with visible focus.
- [x] Active file and expanded folder states are conveyed to assistive technology.
- [x] No copy or affordance suggests source editing.

**Verification:** Component interaction and keyboard tests; browser keyboard pass; frontend build.

**Dependencies:** F2. **Scope:** Medium. **Files:** frontend/src/components/FileExplorer.tsx, frontend/src/components/CodeEditor.tsx, frontend/src/index.css, focused tests.

#### F3.2 — Reliable finding-to-source navigation

**Description:** Resolve exact paths by review source, highlight the reported line or range, and explain unavailable content.

**Acceptance criteria:**
- [x] Findings with duplicate basenames open the correct path and line.
- [x] Upload reviews use uploaded content; server reviews use server reads.
- [x] Missing or omitted source shows a clear fallback and does not masquerade as code.

**Verification:** Focused navigation tests for both modes, duplicate names, and missing files; browser check with a long file; frontend build.

**Dependencies:** F3.1. **Scope:** Medium. **Files:** frontend/src/hooks/useCodeReview.ts, frontend/src/components/CodeEditor.tsx, frontend/src/components/FileExplorer.tsx, focused tests.

#### F3 checkpoint

- [x] Keyboard and finding navigation work in both source modes.
- [x] Focused tests and frontend build pass.
- [x] Report results and stop until the user requests F4.

### F4 — Visual system and inclusive validation

#### F4.1 — Consolidate visual language

**Description:** Set readable color, type, spacing, and focus tokens and remove dead visual rules and duplicate font loading.

**Acceptance criteria:**
- [x] Primary action, source scope, review status, and evidence have clear hierarchy.
- [x] Small UI text is legible; severity colors encode actual severity, not decoration.
- [x] Unused quick-fix styles and duplicate font imports are removed.

**Verification:** Desktop browser screenshot review, CSS audit, and frontend build.

**Dependencies:** F3. **Scope:** Small. **Files:** frontend/src/index.css, frontend/index.html, frontend/src/App.tsx.

#### F4.2 — Responsive and accessibility pass

**Description:** Give narrow screens an intentional review/files/source workflow and ensure focus, motion, labels, and touch behavior work.

**Acceptance criteria:**
- [x] At mobile widths and 200% zoom, primary actions and results remain reachable without horizontal page overflow.
- [x] Icon controls are named, keyboard focus is visible, and dynamic status is announced.
- [x] Reduced-motion preference disables nonessential animation.

**Verification:** Desktop/mobile browser checks, keyboard pass, accessibility inspection, and frontend build.

**Dependencies:** F4.1. **Scope:** Medium. **Files:** frontend/src/App.tsx, frontend/src/index.css, frontend/src/components/AgentPanel.tsx, focused tests.

#### F4.3 — End-to-end acceptance

**Description:** Validate representative review states in a running browser and check the protected-backend connection contract.

**Acceptance criteria:**
- [x] Both source modes and clean, findings, manual-only, partial, error, and canceled states are exercised.
- [x] Frontend tests, type-check, and production build pass.
- [x] Protected-API behavior is verified or its backend contract dependency is explicitly recorded; no secret is placed in a URL or persistent browser storage.

**Verification:** npm test and npm run build in frontend; browser desktop/mobile and keyboard walkthrough; protected-API integration check.

**Dependencies:** F4.2. **Scope:** Medium. **Files:** frontend/src/__tests__, frontend/src/services/api.ts if needed, frontend/src/App.tsx, plan notes.

#### F4 checkpoint

- [x] Browser evidence, tests, build, and report-only check pass.
- [x] Remaining protected-mode limitation, if any, is documented precisely.
- [x] Report results and stop.

### F5 — Live agent activity

#### F5.1 — Safe activity event contract

**Description:** Add file-scan and tool-call metadata to the existing agent progress event without exposing source or tool payloads.

**Acceptance criteria:**
- [x] Existing stage-only events remain valid.
- [x] File paths are normalized repository-relative paths; absolute and parent-traversal paths are rejected.
- [x] Activity payloads contain no source content, prompts, tool arguments, tool output, or credentials.

**Verification:** Focused model and serialization tests.

**Dependencies:** F4. **Scope:** Small. **Files:** devwatch/models.py, frontend/src/types/index.ts, focused tests.

#### F5.2 — Instrument execution and stream both review sources

**Description:** Emit activity at actual file reads and tool boundaries and use the review WebSocket for repository and browser-upload reviews.

**Acceptance criteria:**
- [x] Planner, specialists, verifier, deterministic analyzer, and configured command runner emit truthful tool-call events.
- [x] Review and context file reads emit file-scan events with the responsible agent.
- [x] Uploaded reviews stream progress, complete through the same report contract, and cancel when the socket closes; the REST upload route remains compatible.

**Verification:** Focused engine and WebSocket transport tests, including disconnect behavior.

**Dependencies:** F5.1. **Scope:** Medium. **Files:** devwatch/review/engine.py, devwatch/operations/review_operations.py, devwatch/routers/ws.py, tests.

#### F5.3 — Present a bounded accessible activity timeline

**Description:** Display active agent, scanned file, and invoked tool while keeping history bounded and screen-reader output controlled.

**Acceptance criteria:**
- [x] Current activity names the agent and shows file or tool detail when present.
- [x] History retains at most 100 events and preserves stage, timing, specialist, file, and tool metadata.
- [x] Repository and upload runs share stale-run, failure, completion, and cancellation handling.

**Verification:** Focused stream, state, and panel tests; frontend build; running-browser fixture for both source modes.

**Dependencies:** F5.2. **Scope:** Medium. **Files:** frontend/src/services/api.ts, frontend/src/hooks/useCodeReview.ts, frontend/src/components/AgentPanel.tsx, frontend/src/index.css, focused tests.

#### F5 checkpoint

- [x] Backend activity contract and transport tests pass.
- [x] Frontend tests and production build pass.
- [x] Browser evidence covers repository and uploaded-file activity.
- [x] Report results and stop.

**Completed 2026-10-01:** 53 backend graph/transport tests, 40 frontend tests, production build, and repository/upload Chrome activity checks passed. Stop until the user requests another phase.
