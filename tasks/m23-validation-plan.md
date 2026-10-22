# M23 Comprehensive Evaluation and Final Validation

Started 2026-10-21, after the requested two-minute delay. Baseline: clean
`dfde689` (M22). Final status: **PARTIAL**. Evaluation/reporting finished; the
larger-repository release gate failed and accepted-claim semantic issues remain.
See [the final report](m23-final-validation-report.md).

Preserve all M11 raw results, original 12 public inputs/gold and historical
spending. Separate deterministic engineering, specialist reasoning and full-system
model-quality gates. A failed, incomplete, cap-refused or unavailable run remains
visible with its denominator; no empty result is proof of correctness.

## Ordered verification

1. Freeze original baseline artifacts and current source/environment. Audit the
   seven roles, graph/subgraph routing, budgets, scope/inspection/acceptance,
   checkpoint/outbox recovery, privacy, provider behavior and consumer parity.
2. Add a fresh independently labelled synthetic set, executable label witnesses,
   paired suspicious-but-correct controls, cross-file cases and a larger synthetic
   repository pair. Labels are local only. Existing M19 held-out cases are now
   exposed regressions and cannot be relabelled fresh held-out evidence.
3. Verify evaluation metrics and denominators test-first. Run original fixture
   paths, negative controls, failure injection, budgets, partial tasks and recovery
   through the canonical runtime. Keep programmed responses separate from model
   reasoning claims. Run the full backend and frontend checks on final sources.
4. Preregister live inputs, order, modes, thresholds and prices before dispatch.
   Original 12 cases: full system and each assigned specialist, autonomous and
   evidence-provided. Fresh held-out cases: same three modes. Larger synthetic
   repository pair: full mode. Every trial is retained, including failures.
5. Compare against immutable M11 outcomes, record cost/token/tool/latency and
   causal source review, calculate sample-size uncertainty, and publish the local
   architecture/evaluation report. Do not tune prompts on held-out results.

## Fixed quality gates

Engineering: every deterministic architecture/contract regression passes; no
weakened source, inspection, acceptance, ownership or unknown-cost gate.
Original regression: 12/12 full reviews execute normally, six labelled findings
are detected/classified correctly, six controls have no false positives, and
accepted findings have valid inspected source. Report specialist modes separately.

Fresh held-out screening targets, fixed before provider calls: precision >= 0.90,
recall >= 0.80, clean-case false-positive rate <= 0.10, runtime completion >= 0.95,
finding kind accuracy >= 0.90 and source evidence validity = 1.0. Report counts
and Wilson 95% intervals. Authored paired samples support only scoped evidence,
not population reliability; severity remains unavailable in the public contract.
Unavailable/cap-refused/unattempted cases are explicit and cannot produce a
passing release gate. Causal author review is distinguished from independent
human adjudication. Non-applicable rates are null, never invented zero/perfect.

## Authority and resources

Shared budget starts at US$3.75995325 of US$4, with US$0.24004675 remaining and all
US$0.09968775 earlier unknown holds intact. The user subsequently approved all
22 new payloads in `m23-live-inputs.json` plus US$1, bringing the shared cap to
US$5 and the available amount to US$1.24004675. The frozen 98-review M23 campaign
is capped at US$1.20. Original payloads retain their earlier approval; all labels
remain local. TLS verification, disabled ambient tracing,
serial paid calls and durable reservations before effects remain mandatory.

No working-repository source, secrets, gold labels, raw reasoning or arbitrary
repository commands go to providers. No commit/push/PR/deployment is requested.
If any required gate is not verified or fails, final status is PARTIAL/FAILED,
with the unmet requirement explicit; do not report M23 COMPLETE.

## Recorded outcome

708 backend tests, 55 frontend tests/build and all 24 original fixture trials pass.
All 98 planned live trials are retained; 95 completed normally. All three original
regression modes pass. Fresh screens retain one schema-related miss and one
scope-ambiguous advisory FP. The larger defect is missed after role budget
exhaustion; its repaired control is incomplete after a known pre-dispatch campaign
cap refusal. SQL impact and nested-copy remediation contain material semantic
limitations despite valid primary detections. No production/prompt/gold tuning.

M23 estimated cost US$1.15765125; cumulative conservative US$4.91760450 of US$5;
remaining US$0.08239550. Earlier US$0.09968775 unknown holds remain. No new unknown
API completion or charge. Further remediation must preserve these exposed cases
as regressions and use a fresh preregistered holdout for generalization claims.
