# M12 — Architecture and Contract Audit

Date: 2026-10-18. Status: **COMPLETE**.
Scope: the first milestone of the supplied remediation plan v2.0.

## A. Existing implementation

The repository already implements the seven intended roles, deterministic parent
orchestration, five isolated specialist loops, a two-phase combined final agent,
bounded follow-up, immutable snapshots, scoped evidence, independent inspection
receipts, durable SQLite checkpoints, transactional events and accepted reporting.
The API/frontend contract, M10 runtime checks and M11 evaluator remain in place.

[Architecture specification v2.0](architecture-v2.md) maps every graph node/edge,
all states, role tools, provider behavior, storage boundaries and M12–M23 changes
to actual modules. Six compiled agent graphs implement seven identities: the
control graph is invoked separately for Planner and the combined final role.

Installed versions: LangGraph 1.2.12, checkpoint 4.2.0, SQLite saver 3.1.1,
langchain-core 1.6.6, OpenAI SDK 3.24.0, Pydantic 2.13.5. No installed `langchain`
or `langchain-google-genai`; no role currently uses `create_agent`.

## B. Problems and evidence-based attribution

| Observation | Classification | Evidence and limit |
|---|---|---|
| Arbitrary specialist stop prose accepted, then marked failed | CONTRACT_VALIDATION, confirmed | `SpecialistResult` allowed any nonempty string; `_stop` and lifecycle accepted only evidence_complete as success; two M11 finding-bearing rows use narrative stops |
| Separate completion explanation rejected | CONTRACT_VALIDATION, confirmed | New regression submits evidence_complete plus stop_explanation; old extra=forbid schema causes repair/failure rather than success |
| Stop vocabulary existed only in telemetry | CONTRACT_VALIDATION, confirmed | jobs.py held the literal union while specialist prompt/result schema advertised a string |
| All 12 original full reviews stopped at Planner | ORCHESTRATION outcome confirmed; originating cause UNDETERMINED | Saved results reproduce 3 invalid_schema, 7 provider_incomplete, 2 budget_exhausted; aggregate outcomes do not establish model vs adapter vs output-budget cause |
| Source retrieval failures lacked actionable diagnostics | TOOL_ARGUMENTS vs TOOL_IMPLEMENTATION vs EVIDENCE_RETRIEVAL UNDETERMINED per failed call | Generic recoverable_tool_error; M11 did not retain arguments; source implementation throws generic range errors |
| Missed defect families, wrong advisory kind | MODEL_REASONING vs retrieval UNDETERMINED for misses; classification mismatch observed | M11 author-reviewed claims and small paired corpus; no live verifier evaluation because dispatch never occurred |

The local command runner is an opt-in trusted-host executor, not a security
sandbox. The new plan's untrusted-repository execution policy must remain a guard
on its use. M12 changes no permissions or execution policy.

No active duplicate/obsolete agent engine was found in the current package.
Historical archives and older plan sections are retained. Evaluation helpers are
test providers, not extra production AI identities.

## C. Changes implemented

- `review/contracts.py`: one controlled `StopReason` definition, model-facing
  completion schema and bounded optional `stop_explanation`; deterministic legacy
  migration to invalid_schema retains valid candidates and quarantined siblings.
- `review/jobs.py`: reuse the same stop-code definition without changing event values.
- `review/subgraphs.py`: preserve explanations in private checkpoints and results;
  clear stale explanations at invocation boundaries; keep runtime coverage authoritative.
- `tests/test_m12_contracts.py`: canonical/partial execution, legacy parsing,
  invalid types/field bounds, persistence, no false inspection, no event text leak,
  candidate quarantine and real complete-graph verification/rendering.
- `tests/test_m8_observability.py`: narrative stop now emits the precise
  invalid_schema code instead of the previous generic other, still without prose.
- Architecture, plan/todo/progress records identify M12 and the following roadmap.

Legacy prose is deliberately **not** upgraded to successful completion. New
providers see valid codes in the schema. Existing finding-bearing legacy results
remain partial and eligible for independent evidence/causal verification.

## D. Tests executed

- Pre-change focused baseline: 86 passed in 40.54s.
- TDD red: 4 expected failures, 3 passes (`evidence/m12-contracts-red.txt`).
- First green: 7 passed in 0.94s (`m12-contracts-green.txt`).
- Complete new regression file: 9 passed in 7.04s (`m12-contracts-final.txt`).
- Focused existing plus initial new tests: 93 passed in 38.78s (`m12-focused.txt`).
  The two subsequently added complete-graph tests passed in the nine-case gate.
- Full backend: **422 passed**, zero failures/errors/skips, in 660.93s; log
  `evidence/m12-backend.txt`, JUnit `m12-backend.xml`. JUnit confirms all nine M12
  regressions ran. One existing LangSmith SDK wrapper deprecation warning remains
  in `test_canonical_provider.py::test_real_sdk_uses_unwrapped_transport_and_closes_it`.
  Tests used a fresh system-temp root outside the checkout to avoid inherited Git
  scope, as established during M10.
- Transport export freshness, changed Python compilation and diff whitespace checks
  passed (`evidence/m12-boundaries.json`). The whitespace gate also covers the
  M12 source/tests included in the shared external commit. No frontend source
  or wire schema change was required.

The focused implementation review covered correctness, simplicity, architecture,
privacy and bounded resource use. It checked that migration cannot promote prose
to success, explanations remain bounded/private, task identity and evidence gates
still run, old canonical envelopes retain defaults, and checkpoint/result output
preserves explanations. No critical or required implementation finding remained.
Broader known system limitations are listed in section G rather than hidden by
this contract fix.

Both new complete-graph cases use real snapshot/artifact/job/event/checkpoint/cache
stores, specialist execution, blackboard, verifier, acceptance and rendering.
Only the model provider is scripted. Canonical explanation succeeds; narrative
completion preserves the finding as partial; both reach the existing final agent.

## E. Live evaluation

No new paid-provider calls. M12's change is deterministic; it does not claim a
live Planner repair or improvement in model accuracy. The M11 baseline remains
2/6 individual detections and 0/6 full-system detections.

Offline contract replay of the 12 saved specialist rows retained both original
candidate findings; both narrative completions migrated to invalid_schema with
their text preserved separately. This reconstructs envelopes from saved observations,
not raw model responses. The baseline file SHA-256 remained
`5924cca90da765028d37053cbccd934120fa09811002644697f0ae6b04dec0b0`.
Evidence: `evidence/m12-m11-contract-replay.json`. No baseline metrics were rewritten.

The current 24-case/mode scripted matrix completed all 24 runs with completed jobs
(`evidence/m12-fixture-results.json`, `m12-fixture-run.txt`). Its deliberately
narrow test provider still detects only its programmed empty-input family: full
TP=1, FP=0, FN=5. This matches the M11 scripted baseline and demonstrates that
misses are counted. It cannot establish live model quality; live_model_accuracy
remains null.

## F. Resource usage

Each new complete-graph scenario used five scripted model calls, one source tool
call and 75 scripted tokens across Planner, specialist, verification and synthesis.
The 24-run matrix used 181 scripted calls, 73 tools and 2,715 scripted tokens,
with 77.346s summed job latency. These synthetic token values do not measure
production cost. There were no paid calls or billed costs for this milestone.
Real token/cost and latency improvement are unmeasured. Regression durations
above measure local tests.

## G. Remaining limitations and M13 handoff

M12 does not fix the Planner's provider/schema/budget failures, tool range recovery,
unseen defect reasoning, stage-based tool filtering or semantic deduplication.
The detailed follow-on module map is in architecture-v2.md. The current result
contract still derives execution success from stop_reason; a separate status and
more expressive evidence-completion policy belong to the specialist-loop milestone.

M13 must capture sanitized provider response/finish/usage envelopes, reproduce the
observed Planner failures and distinguish schema shape, adapter and budget causes.
The existing adapter sends text JSON schemas, not native response_format or tool
messages. Test equivalent structured/multi-turn calls before selecting any native
integration, and retain conservative unknown-completion accounting. M11 raw
provider bodies and failed tool arguments are unavailable in the saved result files;
do not assign a confident root cause from the coarse triage labels alone.

The Google skill catalog was fetched and inspected. Its matching Gemini entries
cover Enterprise/Agent Platform rather than this Developer API compatibility path;
none applies. Official LangGraph, Pydantic, Google compatibility and OpenAI Docs
sources are linked next to the corresponding architecture decisions.

## H. Milestone status

**COMPLETE** for M12: architecture audit, versioned module/specification map,
completion-contract correction, candidate-preserving compatibility, backend
regression, actual local execution and relevant offline evaluation all passed.
M13 is next; its Planner/provider reliability and live quality gates remain open.
I issued no commit, push, deployment, provider migration, new agent or user-data
cleanup. The shared repository advanced externally to `e8d7d03` during execution;
that commit includes the M12 source/tests as well as the pre-existing M10/M11 work.
Its M12 changes were inspected against the prior revision; the commit is preserved.
