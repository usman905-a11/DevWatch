# DevWatch architecture specification v2.0

Date: 2026-10-18. Baseline: M12 of the supplied Final Architecture and Reliability
Remediation Plan v2.0. This supplements [seven-agent-design.md](seven-agent-design.md)
with the actual implementation map and the dependency-ordered M12–M23 work.
It preserves the existing seven identities, transport and immutable-source design.
The M13, M14, M15, M16, M17, M18 and M19 supplements below record subsequent changes; other later milestone
entries remain planned work, not claims of implementation.

## Installed implementation

The inspected project interpreter is `.venv/Scripts/python.exe`. Installed:
LangGraph 1.2.12, langgraph-checkpoint 4.2.0, SQLite checkpointer 3.1.1,
langchain-core 1.6.6, OpenAI SDK 3.24.0 and Pydantic 2.13.5. The `langchain` and
`langchain-google-genai` distributions are absent. Declared ranges live in
`pyproject.toml`; this document records observations, not dependency pins.

All roles use custom LangGraph action loops. None uses `create_agent` or native
function-call messages. Model requests carry JSON action/result schemas and a
permission-filtered tool catalogue in text. Do not introduce a second agent
framework to repair an action or provider contract.

## Graphs and every transition

The parent graph is `_ReviewSession.compile` in `devwatch/review/workflow.py`.
Its complete fixed edge chain is:

```text
START
  -> repository_intelligence
  -> deterministic_analysis
  -> change_analyzer
  -> planner_agent
  -> context_manager
  -> budget_manager
  -> deterministic_router
  -> specialist_subgraphs
  -> shared_blackboard
  -> structural_evidence_gate
  -> completion_workflow
  -> END
```

| Node | Implementation and responsibility |
|---|---|
| repository_intelligence | `intelligence`: snapshot-bound cached parser facts |
| deterministic_analysis | `deterministic`: parse status and branch signals |
| change_analyzer | `change_analysis`: selected changed paths |
| planner_agent | `planner`: restore or invoke Planner; explicit partial empty plan on failure |
| context_manager | `selected_context`: validate planned paths and materialize tasks |
| budget_manager | `admission`: refresh/persist cumulative ledger; each actual call reserves separately |
| deterministic_router | `route`: sort tasks by agent/task ID |
| specialist_subgraphs | `specialists`: semaphore-bounded TaskGroup; isolated task execution |
| shared_blackboard | `blackboard` / `publish`: sequential validated result reduction |
| structural_evidence_gate | `structural_gate`: emit candidate validation outcome |
| completion_workflow | `finalize`: reconstruct board on resume; invoke finalization graph |

Current worker fan-out occurs **inside one parent node**. `asyncio.TaskGroup`
joins before that node writes the ordered results list. There are no concurrent
parent-channel writes, so a reducer is not currently missing. M14 must establish
a measured benefit before replacing this with `Send`; any such replacement must
add task-keyed idempotent reducers. Do not add `Send` or `Command` just to check a
framework feature box. LangGraph's [graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
documents routing and state update semantics.

`AgentSubgraphs._build` in `devwatch/review/subgraphs.py` has this entire topology:

```text
START -> investigate
investigate -> END              if private_state.stop_reason is set
investigate -> execute_action   otherwise
execute_action -> END           if private_state.stop_reason is set
execute_action -> investigate   otherwise
```

Five independently compiled specialist graphs share the execution implementation.
A sixth compiled control graph serves separate Planner and Synthesizer/Verifier
invocations. These are seven AI identities, not six or eight. `investigate`
retrieves context, reserves/invokes the provider, parses an action and permits one
schema repair. `execute_action` enforces permissions and budgets, runs tools or
validates final payloads. Verification batches precede synthesis within the same
final identity. Classified transient model retries are bounded in Python; no
native graph retry policy is currently configured.

`FinalizationWorkflow` in `devwatch/review/finalization.py` has these transitions:

```text
START -> synthesizer_verifier -> completion_assessment
completion_assessment -> targeted_followup   if a follow-up was admitted
completion_assessment -> finalize            otherwise
targeted_followup -> synthesizer_verifier
finalize -> structured_report_draft -> final_acceptance_gate
final_acceptance_gate -> deterministic_report_renderer -> END
```

Completion assessment permits at most the existing initial round plus one targeted
follow-up under cumulative limits. Acceptance and rendering are deterministic.
The process-local `AcceptedReport` capability is never checkpointed as a bypass.

## Identities, policies and tools

`AGENT_CONTRACTS` in `devwatch/review/contracts.py` defines exactly these roles.
Every role additionally permits `read_source` and `read_evidence`.

| Identity | Initial tier | Additional permitted tools |
|---|---|---|
| planner | small | repo_map, git_diff, symbol_lookup, dependency_graph, config_read |
| bug_reliability | medium | parse_ast, lint, type_check, run_tests, run_command, git_diff |
| logic_correctness | medium | parse_ast, call_graph, symbol_lookup, run_tests, code_search |
| quality_testability | medium | complexity, coverage, lint, parse_ast, code_search |
| architecture_security | strong | repo_map, dependency_graph, import_graph, sast, config_read, git_history |
| performance_scalability | medium | profile, benchmark, call_graph, db_analyze, query_analyze |
| synthesizer_verifier | strong | code_search, symbol_lookup, call_graph, dependency_graph |

Each tier is configured by `ServiceSettings` in `review/service.py`, not a new
agent. `ModelRouter` permits one policy-defined escalation. `write_artifact` is
available only to a performance task explicitly granted a measurement capability.

`review/tool_catalogue.py` owns strict typed arguments and descriptions.
`PermissionedTools` restricts registration to known names, filters registered tools
by role, and reauthorizes immediately before execution. `RepositoryContext.tools`
registers source/evidence, discovery/search, parser, configuration and captured Git
tools. It connects command/database implementations only through supplied runtime
objects. Catalogue visibility currently depends on role and registration, not on
investigation stage, remaining budget or availability of an exact command grant.

`review/tool_runtime.py` accepts exact operator-approved argv by command ID, uses
scoped scratch files and bounded subprocess lifecycle control. It is explicitly
a trusted-host runner, **not a sandbox**. It must not be used to execute arbitrary
untrusted repository scripts under this remediation plan. Separately approved
execution isolation would be required. `review/database_tools.py` uses owner-granted
database IDs and read-only SQLite inspection/query plans. Neither is changed in M12.

## State, evidence and persistence contracts

| Boundary | Existing fields and owner |
|---|---|
| Parent `ReviewGraphState` | snapshot_id, intelligence, deterministic_signals, change_analysis, plan, tasks, results, rendered |
| Durable job | owner/job ID, original request, workflow version, status, limits, cumulative ledger, follow-up admission, result; `jobs.py` |
| Private `AgentExecutionState` | task/private_state, action/output, snapshot, phase, verification/candidate batch, tier/escalation, retry and error metadata; `subgraphs.py` |
| `AgentPrivateState` | current task; hypotheses; evidence refs/cursors/pages/receipts; local findings/quarantine; coverage; usage/counters; stop code and explanation; `contracts.py` |
| Shared blackboard | stable task-keyed results, claim-keyed candidates, provenance and quarantine; `repository.py` |

Job identity and budgets intentionally live outside the parent TypedDict. There
is no reason to replace accepted fields with conceptual names from the new plan.
`run_specialist` deep-copies private input; the parent receives `SpecialistResult`,
not another task's private history. Context selection retrieves bounded pages.
No chain-of-thought transcript or unbounded message history is required.

`RepositoryContext` binds evidence to owner, snapshot/content hash, scope and task
provenance. Content-addressed artifacts are integrity-checked on retrieval.
`StructuralEvidenceGate` checks candidate location/range, source content and
referenced evidence. Processing, delivery and acknowledgment are separate receipts.
A successful tool result does not prove inspection. Verifier confirmations require
acknowledged source evidence and confidence >=0.8; final acceptance cannot invent
or alter candidate claims, decisions or snapshot identity.

`SharedBlackboard.publish` is task-keyed; candidate identities include task/claim
content, and repeated publication merges bounded evidence. Cross-task semantic
duplicates remain a Verifier responsibility. Partial coverage and valid candidate
findings are independent. Candidate quarantine never discards valid siblings.

`AsyncSqliteSaver` persists parent progress. `AgentCheckpoints` persists private
progress explicitly with the existing `seven-agent-v1` version and generation.
Child graphs use `checkpointer=False`. Invocation mapping rather than implicit
shared-state inheritance is consistent with the documented
[subgraph boundary patterns](https://docs.langchain.com/oss/python/langgraph/use-subgraphs).
Stable thread IDs derive from owner and job ID. Job Store, checkpoints, Repo Cache,
Artifact Store and Event Store retain separate responsibilities. Resume drains or
reconciles effects, reuses completed work and preserves reservations/counters;
[LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
does not replace application idempotency.

## M12 completion correction

`StopReason` now has one definition in `contracts.py`; `jobs.py` imports the same
literal union for telemetry. Its existing event values and wire schema are unchanged.
`SpecialistResult` publishes that controlled set and an optional `stop_explanation`
of at most 1,000 characters. The private checkpoint retains the explanation too.
Only `evidence_complete` indicates execution success; runtime evidence receipts
still determine actual inspected coverage. Other codes retain partial candidates
and failed coverage. No new independent execution-status field is introduced yet.

For compatibility, a nonempty legacy string outside the controlled set becomes
`invalid_schema`, and its bounded text becomes the explanation if none was supplied.
This deterministic migration never interprets prose as proof of completion. It
allows old results/checkpoints and valid candidate siblings to remain readable.
Null, empty and non-string reasons still fail validation. Known codes are unchanged.
Explanations stay out of event metadata and external traces. This uses existing
[Pydantic before-model validation](https://docs.pydantic.dev/latest/concepts/validators/)
and [bounded fields](https://docs.pydantic.dev/latest/concepts/fields/).

## Provider and evaluation boundaries at the M12 baseline

`providers/base.py` defines text-only request/response and aggregate usage.
`providers/openai_adapter.py` is the only active concrete provider. It uses the
OpenAI SDK with Gemini's documented OpenAI-compatible endpoint or configured
OpenAI/OpenRouter transport. It sends system/user messages, output ceiling and
temperature for non-Gemini calls; SDK retries are disabled. It returns first-choice
text, raw finish reason and aggregate prompt/completion/total counts. Runtime
timeouts, cancellation drain and bounded safe retries sit in `subgraphs.py`.

There is no native tool binding, `response_format`, streamed model response,
thought-signature exchange or native conversational tool history in the current
request contract. This is an implementation gap to evaluate, not evidence that a
native tool-call signature was dropped. Excess total usage is charged conservatively;
separate thinking-token detail is not retained. All non-`stop` reasons currently
terminate an action; M13 must test this against actual provider outputs.
Google documents [compatibility, structured output and function calling](https://ai.google.dev/gemini-api/docs/openai);
OpenAI's [Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
defines finish reasons and usage. Support must be tested per provider/model rather
than assumed from interface similarity. No adapter/provider migration is made here.

`scripts/evaluate_reviews.py` retains the 60-case deterministic corpus path.
`scripts/evaluate_agents.py` and `run_agent_evaluation.py` implement M11's 12-case
paired individual/full evaluation, provenance/facet/location matching, eligibility,
author adjudication and cost guard. Scripted execution measures harness behavior;
it cannot establish live model accuracy. Current triage uses six coarse hints,
not the new plan's twelve-category root-cause taxonomy. Missing tool arguments and
raw provider envelopes limit attribution. Preserve M11 artifacts without rescoring
them as new live observations or calling author checks independent human review.

## Actual-module roadmap

| Milestone | Existing modules to extend and evidence required |
|---|---|
| M12 | contracts/jobs/subgraphs; architecture map; legacy and canonical completion regressions |
| M13 | providers/base + openai_adapter; subgraphs call/parse/retry/prompt; workflow planner/context; replay/inject observed failures before any compatibility migration |
| M14 | workflow route/specialists/run_task_safely; repository blackboard; cancellation/replay/concurrency gates before any Send/reducer rewrite |
| M15 | tool_catalogue; repository read_source/evidence_page/tools; subgraphs error feedback; invalid range/actionable recovery and repeated-failure tests |
| M16 | subgraphs investigation/actions; contracts private/results; budgets; goal, evidence, stop/status and useful-progress tests |
| M17 | PermissionedTools.catalogue/authorize; tool_catalogue; subgraphs prompt/model requests; stage/budget filters with unchanged execution enforcement |
| M18 | contracts role prompts; repository context; workflow selected context; subgraphs prompt preparation; explicit prompt versions and quality comparison |
| M19 | five existing role policies and M11/evaluation corpora; evidence-provided/autonomous and held-out comparisons |
| M20 | repository structural gate/blackboard; subgraphs verification; finalization acceptance/assembly; causal, duplicate/conflict and provenance cases |
| M21 | budgets; subgraphs reservation/accounting; providers usage; evaluation meter; comparable completed-review cost/latency measurements |
| M22 | jobs event/outbox/replay; workflow checkpoints/recovery; observability; service streams and frontend review consumers; privacy and resume parity |
| M23 | existing backend/runtime/evaluation suites; held-out corpus and explicitly bounded live runs; engineering/model-quality gates reported separately |

The active `devwatch` package contains no old four-agent engine or duplicate native
provider. Historical backend/frontend archives under `tasks/history` and ignored
runtime archives are historical data, not active implementations. Scripted test
providers and the two evaluation corpora serve distinct purposes. M12 deletes none
of them. The stale milestone numbering in historical planning sections is retained
as history; the new current section and this table identify active work.

## M13 Planner/provider supplement (2026-10-18)

The role topology and graph boundaries above are unchanged. Planner receives a
small deterministic repository summary and an explicit AgentAction envelope:
`kind=submit_plan`, `payload=ReviewPlan`. A nonempty scope requires tasks; selected
specialists must exactly match task owners. Scope, unique IDs, reserved IDs, role
permissions, retrieved evidence references and remaining specialist headroom are
validated before delegation. Atomic model reservations remain authoritative.

`BalancedLimits.planner_output_tokens` defaults to 4,096 (512–8,192 configurable).
The cumulative Planner ceiling stays 25,000. Output admission shrinks against
remaining job/role headroom using the existing conservative input estimate; it
cannot reset prior consumption or spend the reserved final-agent budget. Older
saved job views may omit the new field; backend restoration supplies its default
and the generated browser wire schema treats that property as optional.

The current adapter adds opt-in JSON-object output and Gemini `reasoning_effort`;
Planner requests JSON mode plus low reasoning. JSON mode constrains syntax, not
the ReviewPlan schema; runtime validation remains required. Refusal is retained
as a boolean and can never pass as a successful action. Reported reasoning counts
are preserved when present, while unallocated total usage remains charged at the
conservative output rate. SDK retries stay disabled.

Only returned Planner completions with length/unknown finish can use the existing
schema-repair allowance (one by default). Completion recovery and malformed-schema
repair share that persisted allowance. Authentication, quota, refusal and unknown
network consumption are not automatically replayed. Existing transient retries
remain bounded. Repair feedback contains structural field paths/error categories;
successful actions clear stale feedback before the next investigation turn.

Private checkpoints retain a bounded history of structural response observations:
finish category, shape/length, refusal, requested output and reported usage. No
body, source excerpt, thought text or refusal explanation is added to telemetry.
The existing text-action tool protocol remains in use. Native function calling,
thought signatures, streamed model deltas and full conversational SDK messages
remain unimplemented and unverified; no provider/framework migration is claimed.

See [M13 reliability report](m13-reliability-report.md) for actual live outcomes,
regressions, resource accounting and the remaining validation limits.

## M14 orchestration supplement (2026-10-18)

The parent remains one eleven-node StateGraph. Its specialist node owns bounded
TaskGroup workers and produces one results update; blackboard publication remains
serial. Initial worker reuse now validates exact task scope, generation one and
result identity before emitting reuse or skipping investigation. A duplicate task
ID is rejected before workers start. Missing/foreign internal outputs become
explicit task failures inside run_task_safely; durable integrity errors propagate
through the existing cancellation/drain boundary.

The blackboard join now validates all typed assignments/results and requires one
unique matching task/role result for each assigned task before publication. This
is a validation barrier, not a database transaction around all publication effects;
existing task-keyed publication and replay remain the idempotency mechanism.

The M14 runtime checks demonstrate interrupted-worker reuse, distinct private
state for multiple tasks of one role, shared three-call concurrency across two
jobs, deterministic dispatch, partial sibling preservation and final-agent
reachability. Existing follow-up, failure drain, acceptance and termination tests
remain applicable. The result field still has one writer, so an append reducer
and Send topology change were not introduced. See the rationale and actual
verification in m14-orchestration-report.md; live model quality remains separate.

## M13 live-quality remediation supplement (2026-10-18)

At the user's request, downstream live failures were addressed before advancing
past M14. Every role now requests JSON-object actions and low Gemini reasoning
effort. Prompts specify object-valued action fields, specialist completion
ownership, and the current verification/synthesis result. Advertised actions are
filtered by role and phase. Runtime validation and the existing single schema
repair remain authoritative; JSON mode is not schema-constrained generation.
Finding and synthesis instructions require source/contract support, explicit
candidate fields and one failure mechanism per claim; unresolved input-domain
assumptions belong in limitations. Semantic correctness remains a verifier judgment.

After optional prompt context and evidence pages have been pruned, non-Planner
requests may reduce their response reservation to the remaining model-context
headroom (minimum 512 tokens). The existing maximum response allowance and all
cumulative limits stay unchanged. Requests that already fit are unchanged. This
repairs the reproduced 20,000-token admission regression without weakening the
required schemas or claiming inspection of omitted evidence pages.

The source tool accepts an end beyond EOF only within its existing 200-line
request bound and with a valid start; returned evidence records the actual range.
This prevents repeated failures when reading short source files.

Verified duplicate groups now determine report representatives. Overlapping
groups merge; confirmed claims outrank uncertain/advisory claims, followed by
confidence and stable finding ID. Assembly and acceptance share this policy.
All candidate/decision records remain intact and evidence checks apply even to
suppressed duplicates. Suppression authority comes from verification bound to
the current checkpoint candidates/round, never synthesis prose. Partial and
deadline recovery retain the groups; deterministic acceptance repair retains
failed coverage. Decision identity/value matching is independent of list order.

The five approved live fixtures reached verification and synthesis with 4 TP,
0 FP, 0 FN, zero duplicate findings and no failed task coverage. Cumulative
conservative Gemini charges, including original unknown-consumption reservations,
are US$0.76974150 of US$1. These are small reused-fixture screens, not a general
accuracy guarantee. Current regression status, exact evidence and remaining
measurement limits are in [m13-live-remediation-report.md](m13-live-remediation-report.md).

Final verification on 2026-10-19: 490 backend tests and 66 focused checks pass;
24/24 deterministic case-mode runs complete without failed coverage. M13's
engineering and approved-fixture gates are complete; broader model accuracy is
unmeasured. Later milestone entries remain planned.

## M15 tool infrastructure supplement (2026-10-19)

All 24 tool names have specific descriptions and strict argument contracts. File
paths are normalized and checked against task assignment before handlers; owner,
snapshot, capability and database boundaries remain runtime-enforced. SQLite
parameters must be finite; query plans remain read-only EXPLAIN without result
rows. Missing/parser/configuration/query errors carry safe correction guidance;
source/evidence integrity failures stop before more model work.

`tool_errors.py` defines private structured diagnostics with static hints, safe
argument coordinates, redacted free text and normalized failed-request identities.
The graph persists at most eight diagnostics, suppresses identical failed actions
before effects, and exposes only the latest active feedback to the model alongside
the legacy receipt. Recovery uses existing cumulative iterations/tool calls; no
automatic command replay is added. Unknown effects, permission denial and timeout
remain terminal. Checkpoint actions are redacted; public events remain metadata.

After optional metadata pruning, non-Planner output reservations now fit remaining
headroom (minimum 512) before evidence pages are discarded. Thus a fitting page can
be delivered and acknowledged rather than losing inspection to an output ceiling.
Pages that still cannot fit are omitted without delivery/inspection receipts;
mandatory prompts that cannot fit stop with the existing context-limit reason.
Processing, delivery, explicit page inspection and semantic verification remain
separate. Recovered calls retain their historical failed-call coverage receipt.

Implementation and fresh validation: [M15 report](m15-tool-reliability-report.md).
The initial engineering pass needs no paid calls, graph topology/wire changes or
new dependencies. Requested live follow-up uses only the approved synthetic inputs.
M15 is complete for engineering/deterministic runtime gates: 526 backend tests,
87 focused tests and 24/24 matrix runs pass. The matrix has no failed coverage;
source/test hashes remain unchanged through verification. Live range correction,
duplicate suppression and integrity-stop controls pass. Five full fixture reports
complete after one query-only serial recheck; the initial reservation-limited query
attempt remains recorded. Two secondary semantic claims remain overbroad. New cost
US$0.18621000; cumulative US$0.95595150 of US$1. Broader live accuracy is unmeasured.

## M16 specialist investigation supplement (2026-10-19)

Specialists retain private goal, required-file, stage and bounded successful-action
progress. The focused investigation module owns requirements, candidate retention
and repeat detection; RepositoryContext validates source evidence. Source-file
metadata comes only from actual read_source pages. Parser/search/graph scope no
longer counts as source inspection. Each assigned file needs an acknowledged
source artifact before evidence_complete; this is a minimum window requirement,
not exhaustive line coverage. Missing requirements yield evidence_incomplete.

New candidates require fully acknowledged immutable source covering their exact
location. Existing response repair may guide retrieval/acknowledgment; valid
siblings survive unsuccessful repair and later empty submissions. Terminal
evidence rejection emits controlled metadata. Publication retains the existing
invalid_evidence classification for quarantined candidates.

Eight recent successful request identities and inspection-progress signatures
survive restart/follow-up. An identical acknowledged artifact stops before another
effect; two identical unacknowledged successes stop before a third effect. The
controlled reason is no_progress, distinct from tool failure. Different requests
and advancing offsets remain possible within unchanged cumulative budgets.
Legacy private progress defaults to absent and initializes from the bound task;
completed historical results are not retroactively re-reviewed.

The two additive stop codes are generated into the frontend schema. No graph,
framework, dependency, route or resource ceiling changes. SDK-to-report and
frontend gates pass. COMPLETE for engineering/deterministic gates: 543 backend
tests, 50 frontend tests/build, and 24/24 matrix runs without failed coverage.
All 147 frozen source/fixture hashes match; scripted detection scores are unchanged.
The requested live follow-up passes four runtime controls. Eleven of twelve full
attempts have complete source/goal coverage without failure; one initial local
post-response PermissionError remains recorded and two targeted rechecks pass.
Windows journal write contention is reproduced and locally guarded; attribution
of the original untraced exception remains inferred. All 89 API responses stop,
with no unknown consumption/refusal. Three unsupported secondary semantic clauses
remain despite correct core findings. New estimated cost US$0.28089150; cumulative
US$1.23684300 of the expanded US$2 cap. No production changes during live follow-up.
At M16 completion, M17/M18/M20 remained planned. Evidence and limits:
[M16 report](m16-investigation-reliability-report.md).

## M17 dynamic tool-selection supplement (2026-10-20)

PermissionedTools.catalogue remains the complete registered-role inventory.
for_model(state, context) returns a visible catalogue plus bounded measurement
metadata. The separate tool_selection policy shows source retrieval before a
specialist has trusted source, analysis after source is available, evidence
paging when refs/pages exist, and no tools during synthesis. Candidate pages
preserve paging access on the first verification call even without private refs.
The custom JSON action schema binds its tool enum to the current visible names.

Registration can supply a trusted availability callback. Repository bindings hide
commands without scoped approved definitions, databases without owner grants and
measurement serialization without its existing runtime/operator grants. These
callbacks guide presentation; authorize/execute and the trusted runtime's command
and grant methods are unchanged. Hidden but role-permitted actions still undergo
normal execution enforcement and are counted as unadvertised. A non-measurement
source record now rejects with PermissionError before nested measurement lookup.

Private tool_selections checkpoints retain bounded stage/names/size/proposal
metadata with existing history limits. They survive restart and do not enter
prompts, public events or reports. No new framework, dependency, route or public
wire contract. LangChain create_agent middleware is not compatible with this
custom StateGraph loop; binding stays at the existing model-call seam.

Engineering and scoped verification complete: backend 557 passed, 14 new cases;
matrix 24/24 complete without failed coverage, programmed detection unchanged.
Inventory covers 24 tools. Initial paired live reviews preserve 4 TP / 0 FP / 0 FN
per arm, with full source/goal coverage. Summed standalone catalogue text tokens
fall 29.58%, but generation cost rises 5.95% with 39 versus 34 model calls. Three
secondary semantic clauses remain unsupported; broader semantic non-regression
is not established. A fresh narrow SQL recheck passes after one retained local
reservation-limited partial review. All 13 attempts remain: raw 10 TP / 0 FP /
1 FN, 12 complete source/goal reviews, 91 known stop responses and 17 schema
counts. No unknown API consumption. All 151 frozen source/fixture hashes match.

New conservative M17 charges US$0.33330675; shared cumulative US$1.57014975 of
US$4, leaving US$2.42985025. Live verification is required for subsequent
completed milestones. M18 is next; M18/M20 and other later milestones are not
implemented by this supplement. Evidence and limits:
[M17 report](m17-dynamic-tool-selection-report.md).

## M18 prompt/context supplement (2026-10-20)

The pure prompts module owns compact common/seven role policies and curated
completion, verification, synthesis and partial-evidence paging guidance. Stable
system policy is separated from task/source data; unrelated phase/role guidance
is absent. Explicit Planner consistency and candidate-field requirements remain
after live compaction regressions. Version review-prompts-v2.3 and context version
scoped-evidence-priority-v2 are recorded with a policy/guidance fingerprint in
existing bounded private provider history. Finish/refusal/usage/reasoning counts
are retained. No public wire schema, dependency or new agent framework changes.

Repository context validates scoped immutable pages, prioritizing new undelivered
tool pages, incomplete continuation offsets, active candidate refs and uninspected
source before inspected/ancillary pages. Stable ties preserve recency. Selection
cannot fabricate inspection, alter offsets or expand scope; existing budgets and
authorization/evidence gates remain. Fingerprints exclude task/source data and
do not establish exhaustive observation of unknown provider requests.

M18 Prompt and Context Engineering (2026-10-20), COMPLETE for engineering and
scoped verification: versioned compact shared/seven role policies, conditional
guidance and private provider revision metadata are implemented. Context prefers
pending tool delivery, continuation pages, candidate refs and uninspected source
without fabricating inspection or weakening scope. Final revision v2.3/context v2.
Backend 571 passed (14 new cases); matrix 24/24 complete without failed coverage.
All 155 frozen files match. Final five live reviews have complete source/goal
coverage, no failed coverage and 4 TP/0 FP/0 FN; performance clean control passes.
Final sample uses 22.86% fewer input tokens and 26.77% less known generation cost
than retained M17 controls; different step counts limit causal/general claims.
Two of four final findings contain unsupported secondary input-domain clauses;
broader semantic non-regression is not established. All 26 attempts retained:
raw 18 TP/0 FP/2 FN; 23 complete source/goal reviews without failed coverage.
177 known stop responses and one HTTP 503; its US$0.04114425 unknown reservation
remains charged. M18 total US$0.55952325, cumulative US$2.12967300 of US$4,
remaining shared budget US$1.87032700. No commit/push/deployment or M19/M20 work.
Report: [m18-prompt-context-report.md](m18-prompt-context-report.md).

## M19 specialist-intelligence supplement (2026-10-20)

The optional direct-specialist evaluator mode supplies immutable source artifacts
before the first model request to separate reasoning from autonomous retrieval.
Actual context delivery, continuation paging, acknowledgment and scoped candidate
validation remain canonical. Prefetch has its own metric; it does not fabricate
inspection or tool effects. Provided/full combinations are rejected before effects.

Five role policies now require contract witnesses and appropriate advisory/defect
classification. Performance allocation/lifetime guidance loads progressively only
after source delivery. Final policy revision is review-prompts-v3.3. An all-invalid
structural candidate batch gets the existing bounded schema repair; terminal
rejections and mixed valid siblings retain explicit behavior. Eight authority and
evidence methods remain unchanged. No public wire or dependency change.

The frozen corpus has twelve original cases and five new paired held-out families.
Latest-attempt evidence combines 36 unchanged-role v3.1 and eight v3.3 performance
reviews: 22 TP / 0 FP / 0 FN across both modes, all 22 kinds correct, all 44
source/goal/runtime/quarantine gates pass. Held-out kind accuracy improves 80% to
100%; primary detection was already perfect. Three secondary impact extensions
remain flagged; direct specialist checks do not prove final synthesis correctness.
No held-out outcomes select corrections and all 148 attempts remain in evidence.
Backend 596 passed, zero failures/errors/skips; all 159 frozen inputs match,
with zero credential leaks. M20 remains planned.
See [M19 report](m19-specialist-intelligence-report.md).
