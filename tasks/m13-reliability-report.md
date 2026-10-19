# M13 — Planner and Provider Reliability

Current follow-up: [M13 live-quality remediation](m13-live-remediation-report.md)
fixes the downstream failures below and records a complete five-case live rerun.
Status as of 2026-10-19: **COMPLETE for M13 engineering and approved live-fixture
gates**; 490 backend tests and 24 deterministic case-mode runs pass. Conservative
cumulative Gemini charges are US$0.76974150 of US$1. Broader accuracy remains
unmeasured. The original run and its partial status are retained below as history.

Original run, 2026-10-18. Status: **PARTIAL — engineering changes and final serial
regression pass; downstream live reviews remain partial**.

## A. Existing implementation

The seven identities, custom LangGraph action loops, deterministic dispatch,
permissioned tools, immutable evidence, durable checkpoints, cumulative budgets,
independent verification and accepted report rendering already existed. The
OpenAI-compatible Gemini adapter already disabled SDK retries, classified common
HTTP errors, closed transports on cancellation and charged unknown consumption
conservatively. Those mechanisms and the M12 stop contract remain in place.

Installed SDK/framework versions and graph boundaries are in
[architecture-v2.md](architecture-v2.md). No framework, provider, model tier,
production agent or dependency was added or replaced.

## B. Problems found

| Observation | Attribution and evidence |
|---|---|
| Planner instructions requested a bare ReviewPlan while runtime required AgentAction | CONTRACT_VALIDATION, confirmed. The pre-change malformed-envelope regression failed; one bounded repair now identifies kind/payload without echoing inputs. |
| Fixed 8,192 output reservation could reject a later Planner request despite usable remaining capacity | BUDGET_CONFIGURATION, confirmed with realistic registered tool schemas and 12,000 already-consumed tokens. Output now fits remaining capacity; the 25,000 ceiling is unchanged. |
| Empty delegation, unused selected specialists and invented task evidence could pass the planning boundary | CONTRACT_VALIDATION, confirmed by failing regressions. Runtime now rejects these before dispatch. Existing scope, role, duplicate/reserved ID checks remain. |
| All non-stop completions immediately stopped Planner; explicit refusals were not retained | PROVIDER_RESPONSE_HANDLING, confirmed by injected SDK responses. Returned length/unknown completions get at most one shared schema/completion recovery; refusal is a non-success even with stop. |
| Response shape and finish/usage details were insufficient for diagnosis | OBSERVABILITY, confirmed. Safe bounded private observations now survive checkpoints; raw bodies, source, refusal prose and thought text are excluded. |
| Repair guidance could persist after a successful tool action | STATE_MANAGEMENT, confirmed by a new red test during review; successful parsing now clears guidance. |
| New generated limit initially became required for historical frontend job fixtures | WIRE_COMPATIBILITY, caught by 13 frontend failures. The added property is optional on the browser wire; backend supplies its default. Existing required fields remain required. |
| M11 full reviews stopped 7 times with provider_incomplete, 3 invalid_schema, 2 budget_exhausted | Outcome confirmed; exact historical root cause **UNDETERMINED**. M11 did not retain raw provider bodies. Injected pattern reproduction and new observations do not prove the cause of every historical failure. |

The first live full review now planned and dispatched successfully. Its downstream
source error, incomplete specialist output, timeout and truncated verification are
retained as partial coverage. Generic tool errors cannot distinguish bad ranges
from implementation failure without arguments; the precise cause remains
UNDETERMINED. An unexpected finish category is recorded as other rather than
exporting arbitrary provider text. No unsupported claim about missing native
thought signatures is made: the active protocol uses text JSON actions.

## C. Changes implemented

- `providers/base.py` and `openai_adapter.py`: optional JSON mode and Gemini
  reasoning control, retained reasoning-token detail, refusal boolean and original
  finish status; unchanged default options for other providers.
- `review/contracts.py`: explicit Planner action envelope, narrower responsibility,
  configurable bounded output allowance, exact selected-agent/task correspondence.
- `review/budgets.py`: read-only remaining model headroom, including inflight
  reservations and the final-agent reserve. Atomic reservations still enforce it.
- `review/subgraphs.py`: adaptive Planner output admission; plan evidence/scope/
  delegation checks; sanitized validation feedback; persisted bounded recovery and
  structural observations; clear feedback after a valid action.
- `review/workflow.py`: deterministic snapshot/file-count/extension metadata in
  Planner context; existing scoped intelligence and changed files retained.
- `scripts/export_review_contracts.py` and generated frontend schema: optional new
  limit remains readable alongside older saved job views.
- Three M13 regression files exercise the installed SDK over mock HTTP and real
  full graphs, stores, evidence, verification and rendering.

Completion recovery and schema repair share the existing one-repair allowance;
they do not each receive another retry. Transient retries remain bounded by the
existing policy. Authentication, quota, explicit refusal and unknown network
consumption are not automatically replayed. Private observation history is bounded
by iteration/repair/retry limits (27 entries with defaults).

The adapter uses **JSON-object mode**, not native schema-constrained generation.
Pydantic and runtime checks validate the action and ReviewPlan before dispatch.
Google documents [OpenAI compatibility and reasoning controls](https://ai.google.dev/gemini-api/docs/openai)
and [structured output](https://ai.google.dev/gemini-api/docs/structured-output).
The [Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
distinguishes JSON mode from schema constraints and defines finish/usage metadata.
The existing custom loops fit documented [LangGraph workflow patterns](https://docs.langchain.com/oss/python/langgraph/workflows-agents);
no native message/tool integration migration is inferred from these references.

## D. Tests executed

- Initial focused baseline: 39 passed. Initial M13 red gate: 13 expected failures,
  one pass (`evidence/m13-red.txt`).
- Intermediate checks exposed an insufficient repair prefix and a None retry-state
  regression; both were corrected before the 72-pass focused gate. No known
  failing test was hidden or weakened.
- Full-graph/config red gate: five expected failures, 16 passes; green: 21 passes.
  Observation-history red gate: two expected failures. Later focused gate:
  **87 passed**, 49.09s (`m13-focused-final.txt`).
- Review found stale repair guidance: the new regression failed first, then
  **38 recovery/resume checks passed**, 42.87s (`m13-recovery-final.txt`).
- Frontend after backward-compatible export correction: **50 tests passed** in
  11 files (`m13-frontend.txt`); TypeScript and production build passed
  (`m13-frontend-build-final.txt`). Existing Vite/plugin warnings remain.
- Contract export freshness, changed Python compilation and whitespace checks
  passed (`m13-boundaries.json`). Source and test hashes remained unchanged during
  final verification; the M11 baseline hash is unchanged.
- An earlier full run passed **449 tests**, 797.26s, before the last stale-guidance
  regression/fix (`m13-backend.txt`, `m13-backend.xml`). The first full run on the
  delivered source ran **450 tests: 449 passed, one failed**, 804.77s. All **28 M13
  tests passed**. Logs/JUnit: `m13-backend-final.txt`, `m13-backend-final.xml`.
  One existing LangSmith wrapper deprecation warning remains.
- The failing existing M10 real-deadline test passed unchanged in isolation:
  **one passed**, 19.64s (`m13-deadline-isolated.txt`). In the failed full run,
  the job completed with review_time_exhausted at 15.656s during specialist work,
  before the test's intended synthesis pause. Its assertion that synthesis had
  started therefore failed. Persisted coverage records the deadline and no
  reservations remain. The specific cause of the extra pre-synthesis elapsed
  time is **UNDETERMINED**; an isolated pass does not resolve this full-suite
  timing sensitivity. Evidence: `m13-verification-summary.json`.
  Saved event timelines show synthesis starting at 4.276s in the earlier full
  run and 6.648s in isolation; the failed run had only reached the first three
  specialists' second calls at 13.748–13.918s. These locate the delay before
  synthesis without attributing it to a model or changing any deadline threshold
  (`m13-deadline-timelines.json`).
- Final serial full recheck on unchanged source: **450 passed**, zero failures,
  errors or skips, **678.11s**, including all 28 new M13 tests and the existing
  deadline test (17.85s total test duration). One existing SDK warning remains.
  Evidence: [full log](evidence/m13-backend-serial.txt),
  [JUnit](evidence/m13-backend-serial.xml),
  [verification summary](evidence/m13-verification-summary.json). This closes the
  local regression gate; the earlier intermittent deadline failure remains a
  documented risk rather than a claimed fix.

The 12 SDK/full-graph scenarios cover normal dispatch, repaired bare plan,
incomplete response recovery, temporary HTTP 503, empty/invalid scope/invalid
role/duplicate plans, exhausted completion recovery, refusal, quota and
authentication. They verify honest failure coverage, no unwanted dispatch,
closed transports, released reservations and bounded token consumption. Additional
tests exercise cumulative headroom, checkpoint diagnostics and useful safe repair.

The 24-run scripted evaluator completed every case/mode
(`evidence/m13-fixture-results.json`). Its programmed empty-input detector retains
full-system TP=1, FP=0, FN=5 (recall 1/6), matching the earlier scripted baseline.
These scores measure the harness, not model intelligence or improved live recall.
The matrix used 181 scripted model calls, 73 tools and 2,715 synthetic tokens,
with 84.876s summed job latency and no failed coverage.

Implementation review covered correctness, readability, architecture, privacy and
resource use. The stale guidance and wire-compatibility findings were corrected;
the final serial full-suite gate passed, with timing sensitivity retained as
a limitation. This was self-review; no independent
reviewer or security-audit claim is made. The existing large subgraph module and
duplicated headroom/reservation arithmetic are maintenance considerations; no
unrelated graph rewrite was bundled into this repair.

## E. Live evaluation

The user authorized the existing Gemini key with a US$1 total cap, then explicitly
approved the five synthetic fixture payloads/contracts plus policies and derived
results in `evidence/m13-live-inputs.json` for Google's Gemini Developer API.
Automatic approval initially rejected the call because payload-transfer approval
was missing; the run proceeded only after that explicit authorization. No working
repository source, key, raw provider body or thought text was exported to evidence
logs. Ambient tracing was disabled.

All live tiers reuse the M11 `gemini-3.8-flash` selection. The first batch stopped
after one timeout with its unknown reservation retained. A separate follow-up
uses at most US$0.90, so its cap plus the first US$0.07251675 conservative charge
stays below US$1. The timed-out action is not replayed. Live observations and rows
are saved after every completed evaluation in `m13-live-results.json` and
`m13-live-followup.json`. The follow-up stopped after its third case with a second
downstream timeout: combined charge US$0.17737275. The final two specialist cases
use a separate US$0.80 cap, bounding the combined three batches to US$0.97737275.
A rendered completed job can still contain failed review coverage and must not
be called a complete investigation.

| Full-system case | Planner | Downstream outcome |
|---|---|---|
| empty-defect | Valid first response; two specialists dispatched | Source-tool error, specialist incomplete/timeout; verification truncated |
| empty-clean | Valid first response; two specialists dispatched | One specialist incomplete, one finished without result; final incomplete |
| mutation-defect | Valid first response; one specialist dispatched | Specialist and final incomplete |
| query-defect | Valid first response; one specialist dispatched | Source-tool error, specialist timeout; verification truncated |

All four reached the combined final agent's verification phase. None established
successful live synthesis or a complete investigation. Planner used JSON mode,
low reasoning and a 4,096-token output allowance in every case, with no schema or
completion repair needed. The first Planner response reported 2,131 input and
444 completion tokens, 2,575 total, in 4.767s. All four emitted JSON objects with
finish stop. This demonstrates the current text-action planning/delegation path;
it does not prove native function-call or specialist result reliability.

Both specialist-only cases also completed as partial jobs: empty-defect made a
successful source retrieval plus a failed source call, then finished without a
result; assertion-defect ended invalid_schema. All six planned evaluations ran,
with no accepted findings or candidates. Three defective full cases and two
defective individual cases therefore remain missed observations; the clean case
produced no false positive. Two full cases had external timeouts and are marked
unavailable by the existing evaluator. No comparable 12-case accuracy claim is
made from this selected sample. See `evidence/m13-live-summary.json` for all rows.

No held-out quality, statistically stable reliability, native function calling,
streaming or successful native thought-signature exchange is established by this
small text-action sample.

## F. Resource usage

Planner output defaults to 4,096 per call, clipped to remaining headroom; Planner
cumulative ceiling remains 25,000 and overall job ceiling remains 250,000. Budget
and recovery counters persist across attempts/resume. Live cost is an estimate
using input US$0.75/M and output including thinking US$3.75/M, checked against
[Google pricing](https://ai.google.dev/gemini-api/docs/pricing) on 2026-10-18.
Unallocated total tokens are priced as output; unknown completions keep the full
conservative reservation. This is not a provider invoice or a billing guarantee.

Across all six live evaluations: **US$0.20180175 conservatively charged**, including
both unknown calls; 34 model calls, 15 tool calls (11 successful), 83,398 reported
input and 15,384 output-priced tokens (including unallocated totals). The job
ledgers retained 140,973 tokens including unknown reservations. Summed job latency
was 249.001s. The four Planner calls used 9,938 reported tokens and 16.652s of
summed provider latency. No further paid calls were made after these cases.

Detailed usage, calls, tools and latency are retained in the evidence summary.
Scripted token/cost values are synthetic and cannot measure savings.
Successful completed-review cost/latency improvement remains unmeasured because
downstream reviews are partial and the live sample differs from M11.

## G. Remaining limitations

Downstream source retrieval, specialist finish/result behavior and verification
reliability remain M15/M16/M20 work. M13 does not bypass evidence gates, upgrade
partial work to success or widen provider retries to conceal those failures.
One full run exposed intermittent deadline timing sensitivity; the unchanged
isolated test and final serial full suite passed. Its cause is not claimed fixed,
and the failure remains available alongside the successful checks.
JSON mode is enabled only for Planner; other roles keep their existing protocol.
Selected-role headroom validation does not predict the cost of a full
investigation; atomic call admission remains authoritative.

M11 response bodies cannot be reconstructed, and arbitrary finish values are
intentionally reduced to a safe category. Native function/message metadata and
model streaming are absent from the active integration and unverified. The five
approved fixtures are a small convenience sample, not held-out evaluation. Full
live quality and dependable multi-turn completion are not established.

## H. Milestone status

**PARTIAL.** The Planner/provider engineering changes are implemented and have
28 passing new regressions. Final backend: **450 passed**; frontend: **50 passed**;
TypeScript/production build and boundary checks passed. An earlier intermittent
deadline failure remains documented. Live Planner dispatch is observed in 4/4 cases, while downstream
provider/tool/result failures prevent a claim of reliable complete live reviews.
Preserve these limits before advancing dependent work. No
commit, push, deployment or M14 implementation is included.
