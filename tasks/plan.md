# DevWatch seven-agent remediation: active implementation plan

## Current request: M15 - Tool Infrastructure Reliability (2026-10-19)

Implement the supplied M15 roadmap. Preserve seven identities, scoped immutable
evidence, M13 prompt/provider fixes, M14 orchestration and the shared dirty tree.
The user authorizes implementation; no commit, push or deployment is requested.
No additional provider spending is planned. Carry US$0.76974150 against the
original cumulative US$1 cap; do not reset prior unknown-consumption charges.

Status: COMPLETE for M15 engineering and deterministic runtime gates. Final
backend: 526 passed (36 new M15 cases), 822.71s; focused: 87 passed; matrix:
24/24 complete without failed coverage. Wire/compile/diff checks pass and source
hashes match before/after. No new provider spending. A-H report:
[m15-tool-reliability-report.md](m15-tool-reliability-report.md).

Intermediate focused infrastructure gate: 68 passed; broader
gate: 81 passed and one reproduced evidence-delivery regression. Corrected context
and execution gate: 7 passed. M15 reduces non-Planner response reservations before
dropping evidence that fits, retaining the existing 512 minimum and all ceilings.
The negative page test derives its budget from real mandatory role/schema bytes;
an initial fixed 13,500-token full-job fixture stopped at Planner admission and
was replaced rather than changing Planner admission policy.

1. Structured source/evidence failures and diagnostics (repository, catalogue,
   one focused error module, tests). Invalid ranges/offsets identify usable bounds;
   empty captured files return honest empty evidence without invented lines.
   Argument snapshots retain only bounded safe fields, redacting free text and
   unknown values. Verify failing-first repository and redaction tests.
2. Bounded recovery in the existing graph (private contracts, subgraphs, tests).
   Preserve the legacy two-field error receipt and add detailed private feedback.
   Persist bounded failed-attempt identities through restart/follow-up; suppress
   identical failed execution before repeating effects. Permissions, unknown
   completion, timeout/cancellation and integrity failures remain terminal with
   diagnosable records; success clears active guidance without erasing history.
   Verify correction, repeated failure, restart, partial findings and event privacy.
3. Audit every registered tool's description/arguments and boundary enforcement.
   Enforce assigned paths before handlers; retain owner/snapshot/evidence and exact
   command/database grants. Known read/query failures get safe structured guidance;
   ambiguous command effects are never called recoverable or automatically replayed.
   Verify real command/database/evidence integration, full backend, deterministic
   matrix, wire freshness, source hashes, diff review and an A-H milestone report.

Security scope: untrusted model actions cross PermissionedTools into captured
source, owner-granted read-only databases and exact approved commands. Assets are
snapshot/owner isolation, source and credentials, bounded resources and diagnostic
integrity. Abuse cases: out-of-scope paths, unseen/foreign evidence, repeated failed
calls, attacker-controlled exception text, and SQL/query/unknown argument values
leaking through logs. Controls: schema/role/scope checks before effects, private
allowlisted/redacted diagnostics, metadata-only public events, bounded histories
and cumulative accounting. Existing local-service authentication/deployment is
unchanged; no new trust boundary or category of sensitive data is introduced.

Stop after M15. Specialist reasoning redesign/dynamic tool filtering belong to
later milestones. Existing completed sections below are historical context.

## Current request: resolve M13 live-quality limitations before advancing

Status: COMPLETE for M13 engineering and approved live-fixture gates. Final backend
490 passed; focused 66 passed; deterministic matrix 24/24 completed without failed
coverage. Final five live full reviews: 4 TP, 0 FP, 0 FN, no duplicate findings or
failed coverage. The earlier smaller-context regression was reproduced and fixed.
Conservative provider charges are US$0.76974150 of the original cumulative US$1
cap; US$0.23025850 remains. Future work must carry these charges forward.
Broader model accuracy remains unmeasured. Detailed evidence:
[m13-live-remediation-report.md](m13-live-remediation-report.md).

User explicitly prioritizes the failed live investigations over the next milestone.
Diagnose visible provider actions/finish reasons, source-tool ranges, specialist
completion and verifier/synthesis behavior. Preserve M14 orchestration fixes and
all seven roles. Reproduce each confirmed defect before implementing its fix.

1. Run a small diagnostic on approved synthetic fixtures, retaining visible action
   envelopes and exact bounded finish identifiers in local evidence only. Carry
   forward US$0.20180175 against the original US$1 cap; journal reservations before
   effects. No working repository source or secrets go to Gemini.
2. Correct confirmed provider/protocol/tool defects in thin test-first slices;
   preserve scope/evidence/acceptance gates and all cumulative limits. Include
   necessary downstream fixes in this remediation rather than defer the failures.
3. Verify complete live fixture investigations and defect/clean outcomes within
   the remaining cap, then full regression and review. Report actual quality,
   cost, partial cases and uncertainty; do not promote partial jobs to success.

No next-milestone implementation, commit, push or deployment in this request.

## Current request: M14 - LangGraph Workflow and Orchestration (2026-10-18)

Status: COMPLETE for M14 engineering/runtime gates. Full backend 466 passed,
focused 40 passed, scripted matrix 24/24 complete, boundary checks passed.
The M14 report records the retained TaskGroup/single-writer design and M13's
remaining live limits. No new paid calls; stop before M15.

User requested the next milestone after M13's local engineering gates passed.
Carry forward M13's PARTIAL live status; complete M14 orchestration work only.
Preserve the seven roles, graph/version, stores and shared uncommitted changes.

1. Audit and reproduce dispatch/reuse boundary failures. Validate unique scoped
   tasks before scheduling; cached outputs must belong to the same task scope and
   phase. Malformed local worker output becomes honest task failure, while durable
   integrity/ownership failures still drain siblings and fail the job.
   Check: real-store session tests, failing first for confirmed gaps.
2. Validate complete one-result-per-task aggregation before blackboard publication.
   Preserve valid partial siblings; prove interruption/resume reuses completed work
   without duplicating model calls. Keep a single aggregation writer and bounded
   TaskGroup unless evidence requires a Send/reducer topology change.
   Check: aggregation fault matrix and full graph interrupted-worker scenarios.
3. Prove deterministic order, concurrency limits, state isolation, final-agent
   reachability and bounded termination/follow-up; run full backend regression and
   existing deterministic evaluator, review the M14-only diff and record A-H report.
   Check: focused tests, full pytest, export/compilation/whitespace checks, metrics.

No new provider spending, provider migration, source-tool repair, specialist
reasoning redesign, deployment, commit or M15 implementation in this milestone.

## Current request: M13 — Planner and Provider Reliability (2026-10-18)

Status: implementation delivered; milestone PARTIAL because live downstream
reliability is not established. Final serial backend 450 passed, frontend 50
passed, production build passed; an earlier deadline flake remains documented.
Four of four live plans
dispatched specialists on their first response; all six approved evaluations ran
within US$0.202 conservative accounting. See m13-reliability-report.md.

Implement M13 of the supplied remediation roadmap; preserve the completed M12
contract correction and the seven existing identities. No commit or deployment.

1. Reproduce Planner action-envelope ambiguity, cumulative reservation failures,
   invalid delegation and provider finish/usage handling with deterministic cases.
2. Make the Planner output contract explicit, supply bounded deterministic metadata,
   and validate identity/scope/evidence/nonempty dispatch before accepting a plan.
3. Exercise the current SDK over an injected HTTP transport. Add compatible JSON
   output and Gemini reasoning controls, retain safe response diagnostics and
   reasoning usage, and preserve classified retries and unknown-call accounting.
4. Fit Planner output reservations to remaining cumulative budgets; permit one
   bounded completion/schema recovery without resetting resource limits.
5. Run full-graph failure/success scenarios, existing regressions and the evaluation
   matrix; run bounded live validation only with a supplied spending authorization.
   Record official references, actual observations, remaining uncertainty and status.

Acceptance: valid plans reach specialists and synthesis; invalid scope/roles/IDs,
empty plans and exhausted budgets fail explicitly; incomplete/refused/unknown
provider responses never masquerade as completion; safe recovery is bounded and
persisted; provider diagnostics contain no source, credentials or reasoning text.
The M11 raw provider bodies were not retained, so exact historical attribution
must remain UNDETERMINED where replay or new observations cannot establish it.

## Current request: Milestone 11 - Real Agent Evaluation (2026-10-18)

Complete M11 only; stop before M12. Preserve prior milestones and all seven roles.
Build a small paired corpus spanning the five specialists and Python/JavaScript.
Keep independent gold labels outside reviewer requests. Evaluate actual individual
specialist subgraphs and the unchanged full graph, with defect-specific matching
and an explicit manual-adjudication boundary for semantic evidence correctness.

Slices: (1) corpus and scorer regression tests, including unrelated findings,
wrong locations, duplicates and missed defects; (2) real-runtime runner and metrics
from evidence/checkpoints/events/accounting; (3) reproducible local harness checks,
full regression and report. Live runs require configured credentials and spending
authorization (asked asynchronously); offline fixture scores must never claim live
model accuracy. Report unavailable severity rather than infer it from confidence.
Record precision/recall/FP/FN, localization, evidence, duplicate/tool/investigation
metrics, latency, tokens, supplied-rate cost estimates and six failure categories.
No new production roles, dependencies, services, deployment or commits.

M11 live work: user authorized USD 2 and selected the existing local Gemini key.
All 24 planned case/mode evaluations completed (26 attempts including two provider
timeouts), using configured gemini-3.8-flash at all tiers. Author inspection found
two valid individual claims; full Planner failed on all 12 samples (0/6 recall).
Retain partial model failures in quality scores; exclude external provider failures
only. Reasoning-token accounting fixed test-first; all-attempt bound < USD 0.57.
Final focused 42 passed; full backend 413 passed in 669.86s with one existing SDK
deprecation warning. Contract freshness, compilation and diff checks passed.
M11 complete; see m11-evaluation-report.md. Stop before M12.


## Current request: Milestone 10 - End-to-End Runtime Testing

Complete M10 only. Exercise repository capture -> local HTTP client/service ->
Planner -> all five specialists -> real tools -> blackboard -> combined verifier /
synthesizer -> accepted JSON/Markdown/PDF, durable events and persisted accounting.
Script external model responses; inject a missing optional tool and a task-local
exception to prove isolation. Keep tools, validation, budgets, stores and rendering.

Build a small repeatable matrix: normal; tool failure; invalid arguments;
unavailable tool; malformed output (repair and exhaustion); context limit;
oversized paged evidence; truncation; budget exhaustion; provider/job timeout;
explicit cancellation; specialist failure; graceful resume; finalization repair.
Existing actual process-kill recovery tests remain part of the milestone gate.
Assert final behavior, evidence provenance, accounting, limits, source immutability,
event replay, absence of leaked private errors and completion-before-publication.
No evaluation dataset or live accuracy/cost benchmark (M11), new agents, dependency,
frontend changes, external provider calls, commits or deployment.

Slices: (1) establish seven-agent HTTP normal path and terminal assertions;
(2) run the fault matrix and fix only reproduced runtime bugs through red/green;
(3) cancellation/resume and process recovery gate; (4) full regression, contract /
compile checks, review and M10 report. Tests live in test-only helpers and
`tests/test_m10_runtime.py`; no production test switches. Use a fresh owned E:
temporary root because C: was full during inspection. Stop before milestone 11.

Verification adjustment on resume: C: has free space again. The complete suite
must use a fresh system-temp root outside the repository; otherwise standalone
directory-capture tests inherit the project's Git scope. Reproduced both affected
capture tests inside the repository, then verified them in an external temp root.
The isolated M10 Git fixtures may stay in their owned E: test roots.

M10 complete on 2026-10-18: 20 new runtime cases; focused runtime/process recovery
33 passed in 184.48s; full backend 371 passed in 758.30s with one existing SDK
deprecation warning. JUnit confirms zero failures/errors/skips. Contract freshness,
test compilation and diff checks passed. See m10-runtime-report.md. Stop before M11.

## Current request: Milestone 9 - Basic Local Storage Cleanup (2026-10-17)

Complete M9 only. Use the existing local stores; no new services or dependencies.
Implement configurable offline retention with dry-run CLI by default. Apply must
match an inspected preview plan ID. A shared service/worker lease excludes maintenance.
Keep queued/running/interrupted jobs, recent terminal jobs and all their snapshots,
evidence, reports and checkpoints. Expired terminal jobs lose replay, reports and
idempotency history together. Keep execution lock files and unknown user files.

Slices, each with a failing behavioral test before implementation:
1. Retention selection, dry run, safe artifact paths and disk/SQLite pruning.
2. Cache access timestamps with backward-compatible migration and expiry.
3. Shared runtime exclusion, CLI configuration and explicit reviewed apply.
4. Focused and full backend checks, incremental diff review and M9 report.

Test real temporary stores, shared snapshots, all protected statuses, interrupted
recovery, process locks, malformed paths, junctions/symlinks, failed deletion and
repeat cleanup. Never apply cleanup to the user's existing runtime during testing.
Document offline operation and the age defaults; stop before M10.

Safety adjustment: automatic approval review rejected the first broad deletion /
VACUUM patch before it applied. Prove preview/path/locking behavior first, then
implement only exact-preview apply. No automatic startup deletion or VACUUM.

M9 complete: 49 new cases, 100-test focused gate, full backend 351 passed in
607.28s with one existing SDK deprecation warning. Three 20-review fixture cycles
return to the same file-byte totals; see m9-cleanup-report.md. Stopped before M10.

## Current request: Milestone 8 — Observability & Streaming (2026-10-17)

Continue the attached local plan after completed reliability M7. Stop after M8;
storage cleanup M9 and the historical IDE/infrastructure sequence remain out of scope.
Use existing durable events, SSE/WebSocket replay, CLI and opt-in metadata export.
No new agents, telemetry services, dependencies, live provider calls or publication.

Questions the timeline must answer:
1. Which agent/task/iteration made each model/tool call, and how did it finish?
2. Which evidence was retrieved, delivered and acknowledged, and which candidates
   were created, quarantined or verified?
3. What caused retries/stops and when did final acceptance/rendering complete?
4. Can local replay and optional exported metadata reconstruct the same execution
   without prompts, source, tool arguments/results or raw exception messages?

Ordered slices (each requires a failing behavioral test then a focused green gate):
1. Extend event metadata additively with bounded phase/iteration/attempt, correlation,
   outcome, count, verdict and sanitized stop/finish classifications. Instrument real
   model dispatch/completion and retries; no invented calls when budget admission fails.
2. Instrument actual agent lifecycle, evidence lifecycle, candidate publication /
   quarantine, verification and finalization. Fix misleading generic success events.
3. Preserve ownership/cursor streaming and metadata-only export; keep full job/task
   correlation local, export only random execution/call IDs and allowlisted runtime
   classifications, and add a local `events --follow` CLI observer.
4. Refresh generated browser contracts/fixtures, verify transport parity and consumer
   tests/build, run the backend suite, review the incremental diff and write M8 report.

Follow current Python/asyncio/Pydantic conventions; tests use injected providers and
temporary real stores. New focused tests: `tests/test_m8_observability.py`.
Commands: `.venv/Scripts/python.exe -m pytest tests/test_m8_observability.py -q`,
`.venv/Scripts/python.exe -m pytest -q`,
`.venv/Scripts/python.exe scripts/export_review_contracts.py --check`,
`npm test` and `npm run build` from `frontend/`.
Keep old persisted events readable, existing fields intact and export opt-in.

## Current request: M12 — Architecture and Contract Audit (2026-10-18)

The attached Final Architecture and Reliability Remediation Plan v2.0 is the
current M12–M23 roadmap. Start with M12 and retain prior milestone records below.
Preserve the seven identities, working runtime, frontend and M11 baseline.

1. Audit actual graphs, private/parent state, tools, provider and evaluator against
   the supplied design; record versions and a module map in the M12 audit.
2. Reproduce completion-contract gaps with failing regressions. Publish controlled
   stop codes and a separate bounded explanation. Preserve source-backed candidates
   from legacy narrative stops while explicitly marking the completion invalid;
   never infer successful inspection from prose. Verify canonical and partial paths.
3. Run focused contracts/runtime/evaluation tests, real local graph execution, full
   backend regression and transport-schema freshness. Review only the M12 diff.
4. Record the versioned architecture specification, root-cause evidence, milestone
   results and M13 handoff. Live quality is unchanged unless newly measured.

M12 does not require a provider migration or a paid evaluation. Model-dependent
reliability fixes belong to M13 onward. No commit, push or deployment is requested.

## Previous request: Milestone 7 — Reliability & Recovery (2026-10-17)

The attached local-side-project plan supersedes the older remaining-milestone
sequence below. Complete this milestone only, then stop. Its M7 is reliability,
not the historical IDE-client M7. No commits, deployment, new agents or services.

Acceptance: recoverable tool errors permit a bounded next action with sanitized
structured feedback; malformed output and provider failures remain bounded;
iteration/token/tool exhaustion preserves partial data; deadlines and explicit
cancellation drain work; specialist failure preserves sibling results; explicit
resume preserves accounting and completed work without stale cancellation status.
Keep intermediate recovery metadata bounded and do not store model reasoning.

Implementation order:
1. Establish existing recovery test baseline; reproduce gaps in tool feedback,
   context deadlines, specialist isolation and resumed coverage.
2. Fix each reproduced gap through a failing regression then a focused green gate.
3. Run the backend suite, inspect the incremental changes, and record the M7
   acceptance matrix, files, tests, results and limitations in a separate report.

Use existing Python/asyncio/Pydantic/LangGraph conventions, injected providers,
real temporary stores and immutable test repositories. Runtime source lives in
`devwatch/review/`; regressions live in `tests/test_m7_reliability.py`.
Focused command: `.venv/Scripts/python.exe -m pytest tests/test_m7_reliability.py -q`.
Full command: `.venv/Scripts/python.exe -m pytest -q`.
Preserve shared edits, permissions, evidence gates and cumulative limits. Add no
dependencies or public transport changes. Milestones 8–13 remain out of scope.

## Audit reliability fixes (2026-10-15)

The attached six-fix request is the acceptance specification. Preserve all seven
identities, LangGraph, distributed execution and existing responsibilities.
Execute inline, without commits or deployment, in these dependency-ordered slices:

1. Runtime tool schemas/catalogue: exercise every role and reject malformed calls.
2. Evidence paging and separate processing/delivery/inspection receipts: test large
   artifacts, bounded retrieval, scope, provenance and persistence.
3. Verification gate: reject uninspected confirmations; allow scoped verifier reads.
4. Independent candidate validation/quarantine: preserve valid siblings and coverage.
5. Consistency validation, one repair and deterministic partial recovery: preserve
   verified claims through malformed synthesis, missing IDs and immutable changes.
6. Whole-prompt admission, candidate admission, staged verification, output budgets
   and explicit finish reasons: test small/medium/large and truncation paths.
7. Full pipeline integration, backend regressions, schema/build checks and review.

Telemetry questions: was evidence processed, delivered or acknowledged; were
candidates quarantined; did verification/synthesis stop or recover? Keep payloads
in owned artifacts/checkpoints and emit metadata through existing events.

The binding design is [seven-agent-design.md](seven-agent-design.md).
The previous completed refactor/frontend records are preserved under [history/](history/)
and do not define the architecture being built.

Migration: implement new → test → migrate → cut over → remove legacy → regression test.

Track executable slices in [todo.md](todo.md) and evidence/rulings in [progress.md](progress.md).
The service is not cut over until the graph, durability, permissions, reporting and
consumer migration pass their gates. No commit, push or deployment is authorized.

## Completed two-milestone execution: M0 and M1

The user requested two complete milestones. These are the earliest unchecked
milestones; existing verified slices remain intact. The seven-agent design does
not change. Later intelligence, full consumer parity and legacy-removal gates are
not folded into these foundation milestones.

1. M0 tooling: install the declared runtime/test extra in a clean Python 3.11
   environment, record the resolved dependency closure, build/install the package
   outside the checkout and verify contracts plus full regression. Verify the
   generated frontend transport schemas. Inventory unavailable later adapters.
2. M1 crash recovery: hold an OS-managed per-job execution lock alongside an
   atomic Job Store lease. A dead process releases its lock; another manager
   interrupts the orphan, preserves budgets/checkpoints and requires explicit
   resume. A live process is never displaced based on wall-clock expiry alone.
   Test actual killed subprocesses, queued restart and concurrent managers.
3. M1 accounting/control: persist heartbeat elapsed time without overwriting
   agent accounting; reconcile unknown crash duration conservatively. Observe
   cancellation from another manager and drain work before releasing the lock.
   Verify original intents, counters, unresolved reservations and ownership.
4. M1 integrated gate: test service restart/replay, immutable snapshot and private
   checkpoint continuity through recovery, then run all backend and frontend
   regression/build gates. One fresh combined review follows the two milestones;
   reproduce and fix required findings in one pass before marking M0/M1 complete.

Local SQLite/runtime files require a local filesystem with reliable process locks.
Locks are Job Store execution coordination, not a sixth store or a new AI role.
No lease state is added to the public transport schema. Distributed/network-file
recovery belongs to the optional storage-adapter milestone.

## Remaining milestone execution (2026-10-14)

The user now authorizes completing all unchecked milestones. Existing tested
foundation, service, CLI, UI and PDF work stays intact. Implement inline in this
order, testing each slice; one fresh final combined review follows the migration.

1. M2: real Python/JS/TS AST/symbol/import/call intelligence with versioned cache;
   role-specific graph/search/config/static-analysis tools; immutable Git metadata;
   explicitly approved exact commands and measurement/DB adapters in disposable
   scratch, with clean environment, bounded output, deadline and process drain.
   Gate: parser/graph/scoping/cache tests plus real trusted command lifecycle tests.
2. M3: connect the complete tool runtime to iterative graph execution, include
   tool admission and unknown-operation recovery in cumulative budgets, and add
   opt-in metadata-only observability. Gate: all seven roles, action iterations,
   rejection, tool/provider failure, cancellation/resume and follow-up integration.
3. M4: finish client parity and runtime metadata/export/reconnect checks, including
   earlier minor UI/watch/report recovery notes. Gate: owned service/CLI/frontend
   tests, generated schema freshness and real browser flow.
4. M5: migrate remaining public entry points to the canonical service, archive
   incompatible historical runtime artifacts, remove obsolete engines/agents,
   routers/schemas/config/dependencies/tests after porting useful behaviors.
   Gate: import/reference inventory, built package and full regression.
5. M6: version at least 60 mixed clean/defective cases and evaluate canonical
   outcomes against independent labels. Confirmed precision >=90%, recall >=70%.
   Keep deterministic fixtures and live-model measurements explicitly separate;
   never manufacture live quality from scripted provider output. Gate: evaluator,
   budgets/resource tests, full backend/frontend/build and dependency checks.
6. M7: VS Code and JetBrains clients of the same durable job contract; capture,
   original submission intent, reconnect/status, explicit cancel/resume, report
   groups/exports and immutable source navigation. Gate: client protocol tests,
   extension/plugin build/package and available IDE/runtime validation.
7. M8: disabled-by-default integration and PostgreSQL/Redis adapters with bounded
   typed I/O, explicit credentials and metadata-only LangSmith. Gate: adapter
   contract/integration tests and configuration docs. External publication or
   messaging and deployment are not authorized; live-account checks require a
   configured environment and are reported separately from adapter implementation.

Reproducible dependency records follow actual installed/tested packages. Legacy
removal follows implement -> test -> migrate -> cut over -> remove -> regression;
no permanent compatibility engine or extra AI identity is permitted. The final
review must assess complete milestone claims, not count files or unchecked boxes.
