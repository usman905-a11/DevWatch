# Audit reliability fixes

Implementation started 2026-10-15; verification continued 2026-10-16 (Asia/Karachi).
This report covers the attached six fixes and their integration gate. It does not
claim production readiness.

## Milestone status

| Milestone | Implementation | Verification |
|---|---|---|
| 1: Agent tool interface | Implemented | Seven-role catalogue and argument/permission checks pass. |
| 2: Evidence retrieval | Implemented | Large Unicode artifacts, long source lines, offsets, prioritization, and lifecycle checks pass. |
| 3: Evidence-backed verification | Implemented | Uninspected/forged confirmations fail; acknowledged scoped specialist/verifier evidence succeeds. |
| 4: Candidate integrity | Implemented | Schema/structural errors and capacity overflow are isolated; valid siblings and failure coverage survive. |
| 5: Finalization/recovery | Implemented | Consistency repair, deterministic assembly, failed-repair partial reports and deadline preservation pass. |
| 6: Prompt/context/output scaling | Implemented | 0/5/24 candidates, batches, whole-prompt admission and provider finish-reason checks pass. |
| 7: Integration/regression | Complete | Full pipeline, all 262 backend cases, 49 frontend cases, build and schema checks pass. |

## Runtime decisions and behavior

`PermissionedTools.catalogue()` intersects registered tools with the existing role
contract and task grants. Its JSON argument schemas are the same Pydantic models
used by `authorize()` before handler execution. Database registrations select
database/query schemas instead of trusted-command schemas. The model receives
tool descriptions, required/optional fields, defaults, constraints and output
semantics on every request; live-model tool-use reliability is not measured here.

Evidence artifacts remain immutable and snapshot-bound. `read_evidence` accepts
character `offset` and bounded `max_chars`; selected context delivers canonical
JSON fragments with offsets, total length, continuation and provenance. Pages are
bounded by serialized UTF-8 size, including metadata. An explicit read becomes
the most recent reference so older artifacts cannot be starved by newer results.
Source reads retain a line bound and can store large excerpts for paged retrieval;
the public source-view endpoint retains its existing 6000-byte wire limit.

Private checkpoints distinguish processing, delivery and inspection. A successful
tool call records processing. Only pages surviving complete-prompt admission and
sent in a completed provider request receive delivery receipts. The model must
acknowledge delivered pages with `inspected_evidence`; it cannot acknowledge an
unseen reference. Receipt spans persist separately, including the last delivered
span when an earlier page is revisited. File coverage requires complete artifact
inspection. Confirmation additionally requires inspected source evidence covering
the candidate location. Specialist and verifier provenance stays on artifacts.

Schema-invalid candidates are quarantined independently during result validation;
structurally invalid candidates are isolated by the blackboard reducer. Rejection
records retain index, title and reason. The blackboard keeps valid siblings,
capacity omissions, earlier failures and bounded merged references. Existing task
ownership checks remain mandatory for the whole result envelope.

The combined final agent records verification before synthesis. Full drafts are
checked against known candidate IDs, decisions, required findings, immutable claim
fields, evidence, rationale, classification and confidence before successful agent
completion. One existing schema/consistency repair allowance applies. Compact
`SynthesisSummary` output lets runtime code assemble invariant report fields.
Failed synthesis/repair preserves recorded verification in a partial report;
remaining candidates are explicitly uncertain/advisory. Deadline recovery reloads
the matching round's persisted verification without further model calls. The final
acceptance gate repeats consistency and inspection checks before rendering.

Candidate admission is capped at 24; excess candidates are quarantined explicitly.
Verification uses at most eight candidates per batch and can shrink a batch to fit
the complete request. Prior batches remain in durable state; the model receives a
compact progress view. Large synthesis uses prose-only output and deterministic
assembly. Whole-prompt admission includes system instructions, catalogue, both
schemas, task, private projection, repository context, candidates and decisions.
UTF-8 bytes conservatively upper-bound input tokens, with framing and output
reserves inside configurable `model_context_tokens` (default 32768). Optional
context is omitted explicitly; irreducible requests stop before dispatch.
Job/role/iteration/tool/time budgets remain cumulative. A review that exhausts them
preserves admitted findings in a partial report instead of silently losing them.

Provider finish reasons and usage survive the adapter, including empty truncated
output. Missing reasons become `unknown`; only `stop` is accepted. `length` stops
with `provider_truncated`; other incomplete finishes use `provider_incomplete`.
These completions are charged and never retried with the same inadequate limits.
The adapter behavior follows the [official completion finish-reason contract](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create).

Existing metadata events describe actual states: `tool_result` means processing,
`file_opened` with an evidence reference means page delivery, and
`validation_passed` with that reference means acknowledged inspection. Exact spans
and provenance live in private checkpoints. Invalid candidates/actions and known
read failures emit `validation_failed`; classified read failures can be followed
by another bounded action. Unknown command completion, permission denial and
cancellation retain their existing stop/replay rules. No raw source or tool output
is added to event payloads.

## Exact implementation files and functions

| File | Changes |
|---|---|
| `devwatch/review/tool_catalogue.py` (new) | Argument models, `SourceArguments.bounded_range`, `TOOL_ARGUMENTS`, descriptions, `describe_tool`. |
| `devwatch/review/contracts.py` | `BalancedLimits`, `FindingCandidate`, `CandidateRejection`, `SpecialistResult.isolate_candidate_errors`, `VerificationDecision`, `SynthesisSummary`, `AgentAction`, `EvidenceProgress.fully_inspected`, `AgentPrivateState`, safety prompt. |
| `devwatch/review/subgraphs.py` | `ToolObservation`; `PermissionedTools.__init__/register/catalogue/authorize`; execution-state fields; `AgentSubgraphs._stop/_parse_action/_prepare_prompt/_call_model/_investigate/_execute_action/_run_control`. |
| `devwatch/review/repository.py` | `RepositoryContext._record/_read_source/evidence_page/context/validate_confirmation/tools`; nested `read_source/read_evidence/facts/config/git/repo_map/search/database` handlers/registrations; `SharedBlackboard.__init__/publish`. |
| `devwatch/review/finalization.py` | `FinalAcceptanceGate.__init__/accept`; `assemble_report`. Existing finalization graph and renderer remain. |
| `devwatch/review/workflow.py` | `CanonicalReviewExecutor.recover_timeout`; `_ReviewSession.publish/finalize/partial_result`, including synthesis/acceptance closures. |
| `devwatch/review/tool_runtime.py` | `TrustedToolRuntime.write_measurement/execute` attach originating task/agent provenance. |
| `devwatch/review/database_tools.py` | `DatabaseTools.execute` attaches originating task/agent provenance. |
| `devwatch/review/service.py` | `source` preserves the bounded public source response independently of internal evidence provenance/paging. |
| `devwatch/providers/base.py` | `LLMResponse.finish_reason`, defaulting to unknown. |
| `devwatch/providers/openai_adapter.py` | `generate_completion` preserves empty output, usage and finish reason. |
| `devwatch/config.py` | Realistic candidate admission ceiling. |
| `scripts/evaluate_reviews.py` | `ContractProbeProvider` follows paging with role-local caches, acknowledges actual deliveries and explicitly supplies finish reasons. |
| `frontend/src/review/wire-schema.json` | Regenerated canonical schema for added context limit and finding bounds. |
| `frontend/src/__tests__/fixtures/canonical-wire.json` | Regenerated owned service fixture with current schema/events. |
| `tasks/plan.md`, `tasks/todo.md`, `tasks/seven-agent-design.md`, this report | Audit plan/checklist, protocol refinement and change/verification record; existing milestones retained. |

## Tests added and updated

New regression files:

- `tests/test_audit_tool_catalogue.py`: all seven roles, model prompt catalogue,
  required/optional/unknown arguments, strict argument types.
- `tests/test_audit_evidence.py`: large artifact reassembly, processing versus
  delivery/inspection, confirmation enforcement, verifier-acquired provenance,
  long source lines, forged inspection, retrieval priority.
- `tests/test_audit_candidates.py`: mixed structural/schema-invalid batches,
  capacity overflow, bounded follow-up merge and historical failure coverage.
- `tests/test_audit_finalization.py`: missing findings, wrong IDs, changed claims,
  rationale/decision inconsistency, compact assembly, confidence updates after
  verification, inspected acceptance, failed repair and deadline preservation.
  Recovery also revalidates old inspection receipts and rebuilds inconsistent
  persisted synthesis from the authoritative verification checkpoint.
- `tests/test_audit_scaling.py`: small/medium/large candidate sets, staged
  verification, full-context/private-state bounds, irreducible requests, explicit
  missing/truncated/filtered finishes, accounting and recoverable tool errors.
- `tests/test_audit_integration.py`: repository to planner/specialist/tool, large
  AST evidence, offset retrieval, candidate/blackboard, verifier-owned inspected
  evidence, verification, compact synthesis, acceptance and final report. Checks
  persisted spans/provenance, cumulative usage, event redaction and seven roles.

Existing tests updated:

- `tests/test_canonical_provider.py`: four real SDK/HTTP finish-reason cases,
  including empty output and retained usage.
- `tests/test_canonical_evaluation.py`: a reproduced paged command-output defect.
- `tests/test_canonical_workflow.py`, `tests/test_iterative_agents.py`,
  `tests/test_runtime_graph_tools.py`: fixture models acknowledge actual evidence.
- `tests/test_finalization_workflow.py`: accepted confirmed fixtures provide
  explicit verifier inspection receipts.
- `tests/test_review_deadline_recovery.py`: explicit scripted finish reason.
- `tests/test_review_retries.py`: interruption targets the intended retry event,
  rather than the newly observable earlier validation failure.
- `frontend/src/__tests__/durable-client.test.ts`: current context-limit fixture.

Scripted providers are test boundaries; production tools, stores, graph, budgets,
evidence gates and report acceptance are exercised directly. No paid/live model
calls were used.

## Verification results

Final results on 2026-10-16:

| Executed check | Result |
|---|---|
| `.venv/Scripts/python.exe -m pytest -q --basetemp=<fresh external temp directory>` | **262 passed**, one existing LangSmith dependency deprecation warning; 364.15 seconds. Log: `output/audit-backend-verified.txt`. |
| Full 60-case offline contract harness, included in that run | **60 completed; 30 true positives, 0 false positives, 0 misses, 0 failed jobs/coverage failures**. Scripted precision/recall 1.0/1.0; live accuracy unmeasured. Evidence: `output/audit-offline-summary.json`. |
| Focused finalization/evidence/retry check after the last changes | **34 passed**. |
| Frontend `npm test` | **49 passed** across 11 files. |
| Frontend `npm run build` | **Passed**: TypeScript and Vite. Existing React plugin / esbuild migration warnings remain. |
| `.venv/Scripts/python.exe scripts/export_review_contracts.py --check` | **Passed**. |
| Scoped `git diff --check` | **Passed** for the touched tracked provider/config/task/client-test files. |

The backend suite grew from 211 to 262 cases: 46 cases in six new audit test
files, plus four SDK finish-reason cases and one paged-output corpus regression.
All final required checks passed; no test was skipped to obtain these results.

Test environment: installed the already-declared runtime/test dependencies into
the workspace virtual environment. No application dependency or lockfile changes
were needed. An intermediate regression run used a temporary root inside this
Git checkout; capture/watch fixtures then exercised Git capture instead of their
intended standalone-directory capture. The final run uses a fresh external
temporary directory. Earlier test failures are retained in output for comparison.

Resolved full-suite failures during implementation included parser availability
(`test_python_intelligence_is_cached_and_unsupported_parsers_are_explicit`,
`test_real_javascript_typescript_tsx_ast_and_parse_failures`); the old paged-output
fixture (`test_canonical_offline_precision_and_recall_gate`); legacy implicit
inspection assumptions (`test_approved_command_is_available_inside_iterative_graph_and_accounted`);
and retry fixture event selection (`test_retry_resume_preserves_schema_repair_phase`).
The in-checkout temporary-root run also failed
`test_directory_catalog_stops_consuming_at_limit_even_for_excluded_entries`,
`test_unreadable_directory_is_reported_without_raw_os_error`,
`test_directory_capture_excludes_sensitive_generated_and_invalid_source`,
`test_directory_deletion_survives_debounce_and_is_reported_once`,
`test_deletion_is_retained_after_an_intermediate_capture_omission`, and
`test_full_omission_list_still_emits_a_truncated_deletion_report`.
The initial incomplete-environment run additionally exposed
`test_killed_service_resumes_saved_verification_snapshot_usage_and_replay` and the
startup-sensitive `test_output_and_deadline_bounds_are_recorded_honestly`.
All of these pass in the final declared-dependency environment and external temp
root. Focused red/green tests also exposed and verified each requested fix.

## Remaining risks and architecture

The seven existing identities and responsibilities are preserved. LangGraph root,
specialist subgraphs, shared blackboard, distributed harness, shared model slots,
durable jobs/checkpoints and store boundaries remain. No new agent, supervisor,
orchestration framework, source mutation feature or legacy execution layer was
added. The tool schema module is contract data/validation within the existing
permission boundary.

Inspection means a model acknowledged content actually delivered to it; code cannot
prove cognitive understanding or causal reasoning quality. Conservative byte-based
admission can stop earlier than a tokenizer-specific budget, and tight configured
budgets or difficult evidence can still produce explicitly partial reports.
Configured context limits must not exceed the selected provider/model capacity.
The existing trusted host command runner remains outside a security sandbox.
Live-model evaluation, sandbox validation, concurrency stress, broader failure
injection and review-quality evaluation remain future work. This change does not
establish production readiness.
