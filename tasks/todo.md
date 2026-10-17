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
