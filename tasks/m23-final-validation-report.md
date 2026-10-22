# M23 Comprehensive Evaluation and Final Validation

Date: 2026-10-21. Baseline: clean `dfde689` (M22).
Status: **PARTIAL — release gate not met.** Evaluation and reporting are finished;
engineering passes, but larger-repository coverage/recall and accepted-claim
semantics remain blockers. No production behavior was changed to fit these results.

## A. Existing implementation and preserved baseline

The canonical system has seven identities: Planner, five specialists and the
combined Synthesizer/Verifier. Actual compiled graphs have eleven deterministic
parent nodes, five isolated specialist graphs and a shared control graph invoked
with separate task/private states. They use typed custom LangGraph loops, not
`langchain.create_agent`. Snapshots, owner-scoped evidence, explicit inspection,
permissions, budgets, structured causal review, acceptance, durable outbox and
checkpoint recovery remain authoritative. M23 changes no production module.

All 37 M11 evidence/report artifacts remain byte-identical. The original 12-case
input/gold SHA256 remains
`9b154126d994a70dffbd0d60c3bfe7739dba3b2fcab8b788b7d9d4ed0f027163`.
M11 selected 24 comparisons from 26 retained attempts: full system 0 TP / 0 FP /
6 FN, all twelve blocked at Planner; independent specialist screen 2 TP / 0 FP /
4 FN. Original M11 costs and failed fast latencies are preserved, not treated as
performance wins or added again to the current shared-budget ledger.

## B. Problems and evaluation integrity

Exposed M19 held-out cases are now regressions, not fresh generalization data.
M23 adds 20 newly authored cases in ten defect/repair pairs and a separate 12-file
repository pair. New families cover null/falsy fallback, retry count, cross-file
units, exclusive intervals, sibling-path containment, secret logging, nested copy,
mutable defaults, weak assertions and repeated prefix sums. Two of the ten
positive labels are advisories; eight are behavioral/security defects. Negative
controls share identical public contracts. The larger pair tests a deadline
conversion through a small synthetic order service; it is not a real large-repo
accuracy benchmark.

Executable witnesses establish each defect/repair distinction before provider
calls. Only exact locally authored fixture literals execute in these tests; no
provider-generated or arbitrary reviewed repository command executes on the host.
Gold, roles used for scoring, facets, expected kinds and judgments remain local.
Full-system prompts receive only captured source, the public contract and normal
runtime-derived context. Specialist mode deliberately supplies the assigned role;
autonomous retrieval and evidence-provided reasoning are measured separately.

The 98-review order, thresholds, original strict gate, source/label hashes, model,
prices and cap were frozen before dispatch. All attempts stay in the report.
Unattempted positives are misses; unavailable controls remain unknown. Provider
errors, partial coverage, quarantine, missing inspection and cap refusal cannot
be silently dropped. Primary facet/location/source matching is a screen, not a
whole-claim semantic oracle. Author causal review is separately attributed and
never labelled independent human adjudication.

Author review of all 18 original primary claims supports their detection and
kind. One material secondary claim remains: the full SQL finding says it permits
access to "unauthorized user records", while the fixture establishes predicate
manipulation and changed lookup results without showing an authorization policy.
The model's structurally valid four-field causal review does not establish that
missing fact. The membership advisory also needs ordinary average-case and
unmeasured-risk qualifications; a direct dict replacement needs a list wrapper
to retain the original return representation. Raw outputs and automated primary
scores are retained. No held-out result is used to tune prompts or gold.

Author review inspected all 48 emitted findings across all 98 trials. A second
material limitation is the full nested-copy finding's alternative remediation:
constructing only `{"items": ...}` drops the original order's other fields. An
inert, locally authored counterexample loses `id` and `status`. The primary aliasing
bug remains valid; a valid detection does not make every proposed fix safe.

The full repaired weak-assertion case emitted a broader missing-boundary-tests
advisory. It remains **1 FP under the frozen labels**, with no rescoring. The
observation of absent tests is source-supported, however, and the public contract
does not explicitly exclude broader coverage advice. This is an ambiguous control
for open-ended advisories, not an unequivocally false source claim. The witness
proves that the repaired interior assertion catches 42; it does not prove that all
possible test-gap advisories are invalid. Future benchmark design should make
that scope explicit before any new holdout is evaluated.

## C. Changes implemented

`scripts/release_corpus.py` contains the newly authored gold/public pairs.
`scripts/evaluate_release.py` adds fixed release metrics, honest missing/unavailable
denominators, Wilson intervals, scoped tool recovery, explicit partial completion
and a strict every-case original regression gate. Duplicate or unplanned trial
keys and changed gold are rejected. Scripted responses cannot pass a live gate.

The public data manifest is `tasks/m23-live-inputs.json`; the user explicitly
approved all 22 new payloads. Local evidence contains the preregistered protocol,
frozen sources, actual compiled-architecture audit, baseline preservation hashes,
durable paid meter/journal, raw responses, per-task receipt/outcome extraction and
final report checks. Prompts, agent roles, provider policy, dependencies, source
scope, deadlines, retry/repair limits and acceptance are unchanged. Paid resource
concurrency is restricted to one at the executor semaphore; responses are natural,
without action/acknowledgment/candidate injection.

## D. Engineering verification

**708 backend tests passed**, zero failures/errors/skips, native exit 0, in
1,203.57 seconds. One existing LangSmith wrapper deprecation warning remains.
The full run includes provider/tool failures, budgets, partial specialists,
evidence/permission corruption, deadlines, cancellation and actual process-crash
recovery. It uses the repository `.venv` with the declared native parsers.
All 26 new metric/witness tests passed. The initial metric red stage had twelve
expected failures; the separate strict-gate test also failed before implementation.

**55 frontend tests and production build passed**. UI code is unchanged from M22;
its browser verification remains recorded separately. Original fixture replay
completed all 24 real-runtime trials. That deliberately narrow scripted provider
recognizes only one literal family; its misses on other labels are harness
controls, not live-model results. The actual graph/receipt extractor rehearsal
completed all five specialist tasks with full source acknowledgment.

All 178 frozen source/consumer inputs match, all 37 production-module ASTs match
M22, and all 37 original M11 artifacts are preserved. Postflight compiled-graph
audit, generated-wire parity, Python compilation and whitespace checks pass.
The category matrix maps all 13 requested evaluation categories, plus recovery
failures, to executed JUnit cases; this is runtime-contract evidence, not proof of
model reasoning. Credential/diff closure is recorded in the postflight receipt.

## E. Live evaluation

The original strict regression gate passed in every mode: twelve full-system,
twelve autonomous-specialist and twelve evidence-provided-specialist reviews.
Each mode detected/classified all six labelled findings with zero false positives
on six controls, complete inspection and no failed coverage. These are primary
screening gates; the SQL secondary-impact limitation above remains.

All 98 planned trials have retained results; **95 are normal completions**. The
job status `completed` alone does not mean all review tasks or source inspection
completed. Primary screening counts and normal completion are:

| Split / mode | Reviews | TP / FP / FN | Precision | Recall | Clean FPR | Normal |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Original / full autonomous | 12 | 6 / 0 / 0 | 100% | 100% | 0/6 | 12/12 |
| Original / specialist autonomous | 12 | 6 / 0 / 0 | 100% | 100% | 0/6 | 12/12 |
| Original / specialist provided | 12 | 6 / 0 / 0 | 100% | 100% | 0/6 | 12/12 |
| Fresh / full autonomous | 20 | 10 / 1 / 0 | 90.9% | 100% | 1/10 | 20/20 |
| Fresh / specialist autonomous | 20 | 10 / 0 / 0 | 100% | 100% | 0/10 | 20/20 |
| Fresh / specialist provided | 20 | 9 / 0 / 1 | 100% | 90% | 0/10 | 19/20 |
| Larger synthetic / full autonomous | 2 | 0 / 0 / 1 | N/A | 0% | Unknown (0 evaluable) | 0/2 |

The three fresh groups meet the preregistered numeric screening thresholds,
including the full mode's 10% control FPR and provided mode's 95% completion rate.
These tolerances do not erase either failure. The provided sibling-path specialist
omitted required `impact` in both bounded candidate attempts; quarantine/failed
coverage and its FN remain. The larger group fails its gate: the defective case
exhausted both assigned specialist budgets, inspected 8/12 source files and emitted
no finding. Its repaired control inspected 7/12 files, had one role budget failure,
then the campaign's conservative admission guard refused a model call. A subsequent
adapter request stopped without dispatch. That control is unknown, not a clean pass.

The cap refusal happened at settled US$1.15765125 because admission must cover
the next call's full possible reservation, not only its expected actual usage.
There was **one cap refusal, zero unknown API completions and zero new unknown
charges**. The runtime's generic "provider completion unknown" limitation is
retained verbatim in raw evidence but overstates uncertainty for this known local
refusal. Two runtime model requests never reached Gemini.

Wilson 95% precision/recall intervals illustrate small-sample uncertainty:

| Group | Precision interval | Recall interval |
| --- | --- | --- |
| Each original mode | 61.0–100% | 61.0–100% |
| Fresh full | 62.3–98.4% | 72.2–100% |
| Fresh specialist autonomous | 72.2–100% | 72.2–100% |
| Fresh specialist provided | 70.1–100% | 59.6–98.2% |
| Larger full | N/A | 0–79.3% |

These are descriptive binomial intervals for each authored group; pairing and
repeated modes violate an independent population-sample interpretation. Pooled
bookkeeping is 47 TP / 1 FP / 2 FN, with one unknown control. Pooled defect recall
is 35/37 and advisory recall is 12/12; neither is a broad accuracy claim. Finding
kind matching is 47/47 matched findings, source-span validity is 48/48 emitted
findings, and labelled file/line matching is 47/48. All are primary screens;
whole-claim semantics still have the two material flags above.

Stage evidence: Planner 34/34 completed; specialists 109/114 completed; full
reviews 32/34 completed normally. All 163 live tool outcomes succeeded, so live
recovery is **N/A (0 eligible failures)**, not 100%. Regression failure injection
and recovery remain separate engineering evidence. All 233 delivered source spans
were acknowledged; this does not imply all repository files were inspected.
Operation-level author review correlated 159 successful source reads with the
prior prompt pages, owner/task and validated arguments. All were appropriate for
their assigned source scope, four repeated already available full source, and four
other tool operations remain unjudged. Causal tool-necessity accuracy is unmeasured.

## F. Resource usage and authority

The user added US$1 to the earlier shared grant: cap **US$5**, starting conservative
spend **US$3.75995325**, available **US$1.24004675**. M23's approved campaign cap is
**US$1.20**. Earlier **US$0.09968775** unknown holds remain fully charged. Source
payload approval is exact; no working-repository source, secrets, gold labels or
raw private reasoning are sent to Gemini or LangSmith. Ambient tracing is disabled
and TLS verified. Dollar reservations are durably saved before provider effects;
unknown completion or cap refusal stops further dispatch.

The physical model is `gemini-3.8-flash` for all configured tiers, with unchanged
low reasoning policy. [Google's published pricing](https://ai.google.dev/gemini-api/docs/pricing)
was verified on 2026-10-21: US$0.75/M input and US$3.75/M output including thinking.
Unallocated total usage is conservatively priced as output, cache discounts are
not presumed, and SDK default zero is not proof of absent thinking. Estimates are
not invoices. Final M23 estimate is **US$1.15765125**, entirely reconciled to known
usage: **1,076,190 prompt tokens + 93,469 output/unallocated tokens** across
**347 actual provider calls**. Runtime accounting records 349 model requests,
including the two requests stopped before dispatch; these are distinct counters.
Thinking cannot be distinguished from the SDK's absent/default-zero field, so it
remains unmeasured separately and is not asserted to be zero.

Conservative shared spend is **US$4.91760450 of US$5**, leaving **US$0.08239550**.
All earlier US$0.09968775 unknown holds remain included; none were refunded.
The campaign is drained and no further paid calls are running or planned here.

| Split / mode | Estimated cost (US$) | Normal-review latency p50 / p95 (s) |
| --- | ---: | ---: |
| Original / full autonomous | 0.25065900 | 29.977 / 61.230 |
| Original / specialist autonomous | 0.07095450 | 10.664 / 20.551 |
| Original / specialist provided | 0.04678350 | 7.031 / 10.878 |
| Fresh / full autonomous | 0.48149700 | 36.188 / 74.325 |
| Fresh / specialist autonomous | 0.12446700 | 11.390 / 24.370 |
| Fresh / specialist provided | 0.09422250 | 7.282 / 16.559 |
| Larger synthetic / full autonomous | 0.08906775 | N/A (0 normal completions) |

Costs include unsuccessful attempts. All 98 attempt durations sum to 2,031.278 s;
the 95 normal-review durations sum to 1,894.717 s. The larger failed attempts took
61.718 and 50.890 s. These are measured review durations, not wall-clock campaign
duration, isolated inference benchmarks or a production SLA.

## G. Remaining limits and interpretation

Authored paired samples and repeated modes are correlated. Report intervals per
split/mode, not 98 independent repository samples. The held-out source is Python;
the original corpus includes JavaScript. This is not broad cross-language,
real-repository, alternate-provider or population reliability evidence. Source
validity and schema completeness do not prove every causal sentence. The SQL
authorization extension and unsafe nested-copy alternative demonstrate that
distinction despite passing runtime and primary matching gates. The weak-assertion
control also exposes ambiguity between a repaired targeted assertion and broader
test-coverage advice. Severity is absent from the finding contract and
remains unmeasured. Successful tool execution does not establish tool necessity.

Do not compare M11's cheap/fast failed Planner runs to completed M23 work as an
efficiency improvement. Completed-review latency includes actual local/runtime
work under this session's conditions and is not a production SLA or causal
latency benchmark. Unmeasured performance claims remain advisories. Optional
LangSmith remote ingestion remains outside live verification; local metadata/SDK
and recovery contracts are covered by the regression suite.

## H. Milestone and release status

**PARTIAL.** The requested evaluation/report work is finished; the release is not
validated. Engineering and original primary regression gates pass, while the
larger-repository gate fails and whole-claim semantic issues remain. Priorities:

1. Resolve larger-repository investigation/coverage under explicit unchanged or
   newly justified budgets; demonstrate detection and a fully evaluated control.
2. Prevent unsupported impact extensions and unsafe alternative remediations from
   being accepted as fully supported; test both semantic failure classes.
3. Improve bounded required-field recovery without silently fabricating `impact`.
4. Distinguish known pre-dispatch budget refusal from unknown remote completion
   in diagnostics without weakening conservative reservation accounting.
5. Preregister unambiguous advisory controls for future generalization tests.
   These now-exposed cases are regressions; a fresh holdout is required after fixes.

No thresholds were moved, attempts replaced, gold overridden or prompts tuned to
claim success. Any new paid verification needs sufficient remaining authority;
the remaining shared amount cannot support a replay of this campaign.
No commit, push, PR, deployment or next implementation work was requested or done.

Local machine-readable evidence: `tasks/evidence/m23-evaluation-summary.json`,
`m23-category-matrix.json`, `m23-architecture-audit.json`,
`m23-author-review-{original,heldout-first,final}.json`,
`m23-tool-availability-review.json`, `m23-live-run-01.json` and
`m23-postflight.json`. Evidence files follow this repository's existing ignored
local-evidence convention; preserve them when transferring the tracked report.
