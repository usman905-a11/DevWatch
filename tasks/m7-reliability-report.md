# Milestone 7 — Reliability & Recovery

Date: 2026-10-17. Scope: the attached local-side-project milestone 7, superseding
the historical IDE milestone with the same number. Milestone 8 has not started.

Status: **Complete for the tested local runtime.** Stopped before milestone 8.

## Changes

| File / functions | Result |
|---|---|
| `devwatch/review/subgraphs.py`: `_prepare_prompt`, `_execute_action`, `run_specialist`, `_run_control` | One sanitized `last_tool_error` receipt reaches the next model request and survives explicit resume. Successful retrieval clears it. Failed arguments cannot execute a handler. The receipt contains only tool identity and a fixed error code; it adds no reasoning transcript or unbounded error history. |
| `devwatch/review/subgraphs.py`: `_call_model`, `_investigate`, `_execute_action` | Async context selection and context actions use the existing cumulative deadline. Context selection stops as `context_timeout`; timed-out actions stop as `tool_timeout`, drain cancellation and are not automatically replayed. |
| `devwatch/review/subgraphs.py`: `run_specialist`, `_run_control` | Resuming a cancelled task clears its resolved task cancellation marker while retaining unrelated failed coverage and cumulative usage. |
| `devwatch/review/workflow.py`: `run_task_safely`, `specialists`, `finalize` | Unexpected specialist exceptions become persisted partial results with `specialist_failed` coverage. Initial execution and follow-up use the same boundary. Saved candidates and sibling results pass through the existing structural/verification gates. Cancellation propagates; unreadable/unwritable durable state still fails execution. |
| `tests/test_m7_reliability.py` | 19 additional behavioral tests, using injected providers and real graph/store/report paths where relevant. |
| `tasks/plan.md`, `tasks/todo.md`, `tasks/progress.md` | Record this request separately from the older milestone numbering and preserve existing work. |

## Acceptance evidence

| Requirement | Tests |
|---|---|
| Recoverable tool failures / invalid arguments / unavailable tools | New feedback, argument correction and resumed-feedback tests; `test_audit_scaling.py`, `test_audit_tool_catalogue.py`. |
| Malformed model output | Existing one-repair tests in `test_iterative_agents.py`, final-agent consistency/repair tests in `test_audit_finalization.py` and `test_control_agents.py`. |
| Provider/API failures | `test_review_retries.py`: at most two safe retries, persisted accounting, no replay for unknown completion/auth/quota/timeout; `test_review_partial_failures.py`: gated partial reports. |
| Iteration/token/tool exhaustion | Three new graph-level tests retain saved candidates and cumulative consumption; existing `test_review_budgets.py` and final-agent exhaustion regression retain reserved finalization capacity and partial findings. |
| Timeouts | New context/action/provider deadline tests; `test_review_deadline_recovery.py` drains workers before deterministic partial finalization. Unknown provider usage stays charged. |
| Cancellation | New real cancellation/resume tests; existing explicit cancel, cross-manager cancellation and command-drain tests. Explicit cancellation publishes no report. |
| Partial specialist failure | New two-specialist tests retain a healthy sibling and the failing specialist's persisted finding; follow-up failure retains initial findings and consumes the existing admitted round. |
| Safe resume/retry | New restored-feedback and coverage tests; `test_workflow_recovery.py`, `test_review_retries.py`, `test_crash_recovery.py` preserve checkpoints, verification phase, snapshot, ownership and budgets. |
| Bounded structured intermediate state | One optional recovery receipt, replaced rather than appended; existing eight-iteration/twelve-tool and serialized prompt limits remain intact. No new model reasoning is stored. |

## Verification

Baseline: 42 existing focused recovery tests passed in 16.00s.
The first added regression run exposed eight failures; expanded coverage then
exposed follow-up crash and pre-dispatch context timeout failures. Tests and fixes
were run incrementally. The planner resume fixture was corrected to cancel before
dispatch: cancellation after dispatch may legitimately spend most of its token
ceiling, and the product ceiling was preserved.

- First expanded milestone file: **16 passed in 10.74s**; three storage/ownership
  cases were subsequently added.
- Combined initial recovery gate: **53 passed in 21.88s** (before the final five
  additional characterization tests).
- Expanded recovery/crash gate: **112 passed, 1 failed in 85.25s**. The existing
  `test_failed_dispatch_cancels_and_drains_other_specialists` exposed overly broad
  exception isolation. The fix propagates `OSError`, SQLite errors and `JobConflict`;
  the existing test and three new persistence/ownership cases now pass.
  Original log: `tasks/evidence/m7-recovery-focused.txt`.
- Final boundary gate: **27 passed in 26.73s**, covering all 19 milestone tests and
  all eight core regressions. Log: `tasks/evidence/m7-boundaries.txt`.
- Full backend gate: **281 passed, 1 upstream SDK deprecation warning in 498.95s**.
  This includes all 19 new milestone cases. Final log:
  `tasks/evidence/m7-backend-final.txt`.
  The earlier full run started before the infrastructure correction: **272 passed,
  1 failed, 1 upstream SDK deprecation warning in 429.00s**. Its only failure was
  the storage-drain regression above. Retained as `tasks/evidence/m7-backend.txt`.
- Python compilation of changed runtime/test files: passed.
- Incremental source diff reviewed against saved workspace baselines; existing
  staged/unstaged/untracked work was preserved. Whitespace checks: passed.
  Baseline source copies are retained under `output/m7-baseline/` for comparison
  because the original workspace already contained extensive uncommitted work.

Commands use `.venv/Scripts/python.exe -m pytest`; external tracing is disabled
by test configuration. The full backend command is `-q --tb=short`; focused file
and integration paths are recorded in the evidence logs and execution ledger.

## Practical limits

- No live provider availability or paid-model accuracy measurement was performed.
  Failure handling is verified through injected failures and existing adapter tests.
- Async deadlines require cooperative cancellation. Synchronous filesystem/context
  work cannot be forcibly preempted by asyncio; existing subprocess execution owns
  and drains child processes separately. This change adds no sandbox or threads.
- Unknown provider completions remain charged conservatively; retries/resume can
  therefore end in an honest budget-limited partial report.
- Durable-store corruption/unavailability is not converted into successful
  persistence. Recovery requires readable, writable local stores.
- New failures use existing completion/coverage structures. More detailed event
  visibility belongs to the requested milestone 8.
- Frontend code and public transport contracts did not change; no new browser or
  frontend validation was needed for this backend milestone.
- The existing LangSmith OpenAI Agents SDK wrapper deprecation remains an upstream
  warning in `test_real_sdk_uses_unwrapped_transport_and_closes_it`; it is not a
  failing reliability check.

Architecture preserved: **Planner → deterministic Orchestrator → five Specialist
Agents → Shared Blackboard → combined Synthesizer/Verifier → Final Report**.
Exactly seven AI identities remain; no supervisors, services, brokers, distributed
infrastructure, dependencies or public transport schema changes were introduced.
