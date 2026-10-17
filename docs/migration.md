# Canonical service cutover

Run `uvicorn devwatch.review.service:create_app --factory` or `devwatch serve`.
CLI, browser and IDE clients use `/api/snapshots` and `/api/jobs` with owned job
status, cancel/resume, immutable source, persistent events and deterministic reports.
There is one review implementation and exactly seven AI identities.

Configure explicit `DEVWATCH_MODEL_SMALL`, `DEVWATCH_MODEL_MEDIUM` and
`DEVWATCH_MODEL_STRONG` model IDs plus service/provider credentials. Balanced review
budgets come from `BalancedLimits`; old tier/budget aliases are removed. Library
imports do not load `.env`. Export required variables in the service process.

Commands are disabled unless the operator supplies `DEVWATCH_TRUSTED_TOOLS_FILE`.
Definitions are exact approved IDs/argv/source files; project configuration cannot
grant execution. Reviewed source is immutable and commands receive disposable copies.
This is trusted host execution, not a hostile-code security sandbox. Measurement
artifact writing is granted only to approved Performance tasks. Optional SQLite
inspection uses owner-granted `DEVWATCH_DATABASE_POLICIES_FILE` read-only policies.

The new runtime root separates Job Store, Checkpoints, Repo Cache, Artifact Store
and Event Store. Legacy checkpoints/reports cannot be imported or resumed under
the new schema. Preserve them in a private archive and start new snapshots/jobs.
Do not copy legacy rows into the new stores or run two engines against one root.
Already accepted rendered checkpoints retain their original report; job history
records subsequent crash recovery and explicit resume.

Legacy source and schema-specific tests are preserved as non-executable history in
`tasks/history/backend-legacy-2026-10-14.zip`, including available staged Git blobs.
This archive is not installed or imported. The Git index was not changed.

Behavioral coverage moved to canonical tests:

| Retired responsibility | Executable replacement checks |
|---|---|
| Old report/source authentication and sockets | `test_review_service`, `test_review_client`, generated browser wire parity |
| Scanner/path/size/secret controls | `test_capture_boundaries`, `test_capture_coverage`, `test_source_capture`, `test_review_stores` |
| Standalone agents/planner/verifier/synthesizer | `test_seven_agent_contracts`, `test_control_agents`, `test_iterative_agents`, `test_canonical_workflow` |
| Issue identity/deduplication/evidence | `test_repository_context`, `test_core_review_regressions`, `test_finalization_workflow` |
| Old retry/circuit/deadline managers | `test_review_retries`, `test_review_budgets`, `test_review_deadline_recovery`, `test_review_partial_failures` |
| Client-owned background work | `test_crash_recovery`, `test_durable_jobs`, `test_m1_review_regressions`, `test_pdf_lifecycle` |
| Provider wrappers/singleton fake engine | Actual SDK/HTTP-boundary tests in `test_canonical_provider`; injected providers in graph tests |
| Auto-discovered terminal commands | `test_trusted_runtime`, `test_runtime_graph_tools`, `test_database_tools` |

Use `python -m pytest -q`, `python -m scripts.export_review_contracts --check`,
frontend tests/build and `python -m scripts.verify_browser_parity` for the cutover
gate. Browser verification requires local Chrome and the isolated Playwright tools.
Offline evaluator results and live-model accuracy are reported separately.
