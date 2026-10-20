# M16 - Specialist Reasoning Loop Reliability

Date: 2026-10-19. Status: **COMPLETE - engineering and deterministic runtime gates**.

Requested live follow-up: **M16 runtime controls verified**, with semantic claim
limitations and one retained local-harness failure. New estimated cost:
US$0.28089150; conservative cumulative total US$1.23684300 of the expanded US$2 cap.

## A. Existing implementation

All five specialists already shared a custom LangGraph model/action loop with
role permissions, immutable evidence, page acknowledgments, bounded tool/model
budgets, one schema repair, durable checkpoints and partial-result recovery.
M15 distinguished actionable tool failures from terminal uncertain effects and
retained failed-request identities. The Planner and final agent use separate
contracts within the same runtime. No framework replacement is needed.

## B. Problems found

An empty result could report evidence_complete without acknowledging any source.
Acknowledged parser or graph evidence could count every path in source_scope as
inspected source. Publication checked structural evidence but did not require the
specialist to acknowledge source covering each candidate location. An invalid
sibling could cause valid findings to be lost during response repair. A later
empty response could erase previously admitted findings. Successful identical
requests lacked a durable progress guard. Terminal candidate rejection during
evidence repair lacked a candidate_rejected event.

## C. Changes implemented

The new private InvestigationProgress records the assigned goal, required files,
stage and eight recent successful action identities. The investigation module
owns source requirements, useful-progress checks and retained candidates. The
repository supplies immutable source/evidence validation. Existing private
checkpoints can omit this progress; new execution initializes it from the bound
task and rejects a changed source assignment. Follow-up updates the goal while
preserving receipts, findings and cumulative accounting.

Required files need at least one fully acknowledged read_source artifact each.
This is window inspection, not a claim that every line in a file was read.
Actual delivered pages carry source_file only for read_source. Acknowledging
parser, search or dependency facts cannot mark their broad source_scope as source
inspection. Completion with missing requirements becomes evidence_incomplete,
with not_inspected coverage for the missing files.

Every newly proposed candidate needs structurally valid, owner/snapshot/scoped
evidence and a fully acknowledged source artifact covering its exact location.
The existing single schema-repair allowance supplies static evidence guidance.
Valid siblings are retained before repair. Later submissions merge prior admitted
claims, retaining conservative confidence and bounded evidence references. A
failed evidence repair records quarantine and an explicit rejection event;
publication retains its existing invalid_evidence coverage classification.

Successful identical requests whose artifact is already fully acknowledged stop
before a second effect. Two identical successful requests without inspection
progress stop before a third effect. The reason is no_progress, distinct from
M15 tool failure. Advancing page offsets and different requests can proceed.
These checks supplement existing ceilings and survive checkpoint restart and
follow-up. No counter resets, additional repairs or timeout increases are added.

The two additive stop reasons are exported into the generated frontend schema.
Offline providers now read every assigned file, including probe scripts, before
claiming completion. Gold labels, detection rules and scoring are unchanged.
Legacy tests now expect incomplete completion when they deliberately supply no
source acknowledgments; their privacy, effect-count and budget checks remain.

## D. Tests executed

Failing-first logs in tasks/evidence include m16-investigation-red.txt (8 cases),
m16-repetition-red.txt (4 cases), m16-resolved-coverage-red.txt,
m16-rejection-event-red.txt and m16-evaluator-red.txt. The latter reproduced only
half of the two assigned source files being inspected. The existing paged-probe
test also reproduced a retained defect with incomplete required-file coverage.
The corrected paged-probe case passes without failed coverage.

The latest focused gate passes 17 cases in 16.19s (m16-sdk-green.txt): thirteen
investigation cases, three SDK-to-report cases and the multiple-file evaluator.
Actual HTTP serialization through the installed SDK exercises source repair,
valid-sibling retention after terminal repair failure and no_progress under a
20,000-token context. These are synthetic HTTP responses, not paid API calls.

The broader consumer gate initially had 79 passes and one overly broad test
expectation: the intentionally narrow evaluator still misses an assertion-family
defect after inspecting both files. Its expected model_reasoning miss remains;
this milestone does not change the detection rule or gold label. An SDK fixture
initially checked the wrong prompt repair key; it now uses the runtime's repair
field. Publication's existing invalid_evidence classification is asserted along
with the specialist's more specific evidence_incomplete completion event.

The first full run was stopped at 53% after two legacy-fixture failures:
test_runtime_faults_preserve_verified_siblings_and_honest_coverage[budget] repeated
an acknowledged read, now correctly stopped as no_progress; the budget fixture
now varies permitted read_evidence offsets and retains its exact eight-iteration,
eight-tool-call exhaustion assertions. test_legacy_narrative_stop_preserves_candidates_as_invalid_completion
proposed a candidate without any source receipt; it now acknowledges actual
delivered source while retaining narrative migration, partial finding, quarantine
and event-privacy assertions. The corrected focused run passes both cases in
8.58s. An intermediate budget fixture attempted code_search, correctly denied to
that role; the final fixture uses its existing read_evidence permission. No
production change or permission expansion was needed for these two corrections.
The interrupted full log and initial frozen hashes are retained, and the complete
suite restarts with updated frozen test hashes.

The next full run completed with 536 passed and seven failures in 713.65s. These
were the query-only M15 privacy test, five retry-only cases in test_review_retries,
and test_approved_command_is_available_inside_iterative_graph_and_accounted.
Query/retry fixtures do not read source, so their completion expectations now
require evidence_incomplete while all privacy, retry, reservation and checkpoint
assertions remain. The command fixture now performs one real source read after
the command, acknowledges it and expects two tool calls/three iterations. A
command's source_scope alone cannot certify source inspection. All 19 cases in
these three files pass in 7.04s. Production hashes did not change; the full log,
JUnit and frozen test hashes are retained before the final complete rerun.

Frontend tests: 50 passed across 11 files. TypeScript/Vite build and generated
wire-contract freshness pass. Existing Vite plugin deprecation notices remain.
Final serial backend: **543 passed**, zero failures/errors/skips, **724.73s**
(m16-full-backend.txt/.xml), including all 17 added M16 cases. One existing
LangSmith wrapper deprecation warning remains. The complete run used a fresh
system-temp directory outside the checkout. All 147 frozen source/fixture hashes
match after execution. Generated wire freshness, Python compilation and diff
whitespace checks pass. The existing 15-second job-deadline scenario passes
(17.664s total test time including setup/cleanup); no deadline is relaxed.

Deterministic matrix: **24/24** case/mode runs complete, no failed coverage or
excluded runs, and all assigned source files inspected. Full-system scripted
scores remain **TP=1, FP=0, FN=5**, recall 1/6, matching the deliberately narrow
reviewer. This verifies infrastructure and honest misses, not live model accuracy.
Evidence: [summary](evidence/m16-verification-summary.json),
[backend log](evidence/m16-full-backend.txt), [JUnit](evidence/m16-full-backend.xml),
[matrix](evidence/m16-fixture-results.json), [review](evidence/m16-review.json),
[source integrity](evidence/m16-source-integrity.json).

## E. Live evaluation

The user requested live testing and authorized an additional US$1, expanding the
cumulative authorization to US$2. The existing Gemini key/model is used only with
the five approved synthetic fixtures/contracts in m13-live-inputs.json, agent
policies and fixture-derived results. No working-repository source is sent. TLS
verification is enabled and external tracing disabled. Actual SDK, graph, stores,
source tools, acknowledgment accounting, verification, acceptance and rendering
run throughout. Supported model concurrency is set to one locally; no resource
ceiling is increased. The initial batch cap is US$0.80; targeted rechecks use a
US$0.20 cap with all prior charges included.

All four controls passed offline and live. Original model responses are retained
alongside locally applied fault actions. These controls deliberately inject
premature completion, repeated reads or missing acknowledgments; those injections
are not attributed to model mistakes. Recovery after the missing-acknowledgment
repair is the model's unmodified response.

| Control | Live result |
|---|---|
| Premature completion | One response, no tool dispatch, evidence_incomplete, no fabricated inspection/finding. |
| Repeated acknowledged source read | Two responses, one tool dispatch, no_progress before a second effect. |
| Repeated unacknowledged source read | Three responses, two tool dispatches, no_progress before a third effect; no fabricated inspection. |
| Missing candidate-source acknowledgment | Real source delivered, acknowledgment deliberately removed from first candidate submission, repair guidance received, model acknowledges source and retains the defect on its unmodified repair response. |

Two full-review passes cover all five approved fixtures. Nine of the initial ten
natural reviews have complete source/goal coverage and no failed coverage. The
first assertion attempt stops before any tool effect with permission_denied after
a visible model response; the graph records provider_failure and conservatively
charges its reservation. The separate meter retains the actual known API usage,
with zero unknown API consumption. This attempt remains in the original journal.

The recorded source-read action replays successfully against the real handler.
A Windows reader holding a journal file open reproduces PermissionError when
the writer replaces that file. This is consistent with the first attempt's
post-response failure, but the original exception traceback was not captured, so
the exact attribution remains an inference. A bounded local write retry now
handles this reproduced file-sharing hazard without repeating any API call; a
real read-lock test verifies persistence. Two assertion-only live rechecks both
pass. Production/test source remains unchanged. The recheck journal records zero
write retries; no further error occurred.

Across **16 attempts** (four controls and twelve full reviews), **89 actual API
responses all finish with stop**. Unknown API consumption and cost-guard refusals
are zero. **11/12 full-review attempts** have complete acknowledged source/goal
coverage without failed coverage. The raw score over every full attempt is
**9 core TP / 0 FP / 1 FN**, with zero duplicates; this includes the unavailable
assertion attempt as a miss. Its two explicit rechecks both find the defect.
Controls are excluded from detection scores. Every retained specialist candidate
has acknowledged source covering its location (ten checks, including the repair
control). No unavailable attempt is silently replaced in the raw score.

These are core facet/location/evidence screens, not independent human semantic
adjudication. Agent inspection flags three accepted findings: both mutation
reports add non-list/immutable iterable failure outside the supplied input
contract, and one assertion report adds float coverage beyond its integer
contract. The two targeted assertion rechecks produce narrower supported claims.
The two query reports stay within the SQL data/syntax-separation issue; M15's
unauthorized-data-extraction clause is not reproduced here, which does not prove
a general semantic fix.

Evidence: [live summary](evidence/m16-live-summary.json),
[initial fourteen attempts](evidence/m16-live-run-01.json),
[assertion rechecks](evidence/m16-live-run-02.json),
[local diagnosis](evidence/m16-local-permission-diagnosis.json),
[journal retry check](evidence/m16-journal-retry-check.json).

## F. Resource usage

The initial engineering pass used no paid calls. The requested live follow-up
uses **US$0.28089150**: US$0.21967500 for the initial batch and US$0.06121650 for
the two targeted rechecks. Prior conservative charges of US$0.95595150 remain,
giving **US$1.23684300 of the expanded US$2 cap**. US$0.76315700 remains under
that cap; US$0.71910850 remains of this follow-up's additional US$1. The entire
allowance need not be spent to complete these checks. Reservations are persisted
before dispatch and unknown charges are never reset.

Current rates were checked on 2026-10-19 against
[Google's official Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing):
Gemini 3.8 Flash standard input US$0.75/million and output including thinking
US$3.75/million through December 2026. Usage is 284,137 input and 18,077 output
tokens, with unallocated total usage conservatively priced as output. These are
local cost estimates, not an invoice reconciliation. The 89 model admissions use
34 tool dispatches and 437.861s summed job latency. No unknown API consumption.

Successful-action history is capped at eight; goals/progress stay private. The
model receives only required/remaining files and stage; it does not receive a
duplicate goal or successful-action hashes. Existing tool, model, iteration,
context, retry, repair and review ceilings remain authoritative. Guarded repeats
consume no extra tool dispatch. Corrective model requests retain normal charges.

The matrix used **193 scripted model calls**, **85 tool calls**, **2,895 synthetic
tokens** and **68.175s summed job latency**. The added reads of previously omitted
assigned files account for 12 extra model/tool calls versus M15. These counters
are fixture measurements, not billed model tokens or live latency estimates.

## G. Remaining limitations

Acknowledgments prove which source pages a response acknowledged, not semantic
understanding. Reading one source window per assigned file is a minimum completion
requirement, not exhaustive source coverage. Eight retained successful identities
and consecutive stagnation detection do not detect every possible alternating
cycle; global budgets bound the remaining cases. Already completed historical
jobs and trusted persisted findings are not retroactively re-reviewed.

The deliberately narrow offline evaluator still misses five defect families;
no model-quality improvement is inferred from successful infrastructure checks.
The live batch's three flagged secondary clauses remain unsupported despite
correct core defects and complete source receipts. Broader repeated-run quality,
causal correctness and confidence calibration remain unmeasured. One initial
local-harness failure remains in raw results, with its precise cause inferred
from the reproduced journal hazard rather than a captured traceback. M16 does
not solve claim-level semantic verification; M20 remains planned. Dynamic tool
filtering and broader prompt refactoring remain M17 and M18.

## H. Review and delivery

Review covers correctness, readability, architecture, scoped evidence security
and bounded resource behavior. Source requirements derive from the assigned task;
receipts derive from actual delivered runtime pages; candidate claims cannot
self-certify inspection through model-reported coverage. Existing owner/snapshot,
hash, path, capability, command-effect and telemetry boundaries remain in force.
Only controlled metadata is added to rejection events. No dependencies, framework,
graph topology, public route or resource ceilings change.

No remaining required review finding. Full backend, frontend, wire, compilation,
matrix and final integrity gates pass against unchanged frozen source/fixture
hashes. No commit, push or deployment is performed. M17 has not started.

The live follow-up changes only local evidence/harness and milestone documents;
all 147 production/fixture hashes still match the 543-test backend and 50-test
frontend verification snapshot. The original harness version and every paid
journal are retained. Local evidence is scanned for the configured credential;
no credential value is found. No additional production regression run is claimed.
