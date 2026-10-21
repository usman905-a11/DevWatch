# M21 Token, Cost, and Latency Optimization

Date: 2026-10-21. Baseline: `a24ce50` (M20). Status: **Complete for engineering and scoped comparable-cost verification**. M22 has not started.

## A. Existing implementation and completed baseline

The canonical graph already enforced cumulative review-wide/per-role token limits,
final-agent reserves, retry/tool/iteration ceilings and at most three concurrent
model calls. Source analysis used an owner/content-addressed parser cache and
duplicate-progress guards. M20 made summaries and finding selection authoritative
runtime output, but still paid for another model call to generate summary prose.

Before optimization, the plan fixed the eight completed verifier executions in
`m20-live-run-04.json` as the live baseline: seven logical challenges, with the SQL
pair evaluated as two singletons. All eight baseline executions passed their
quality gates. Source/contracts, supplied candidates, order/strategies, physical
model (`gemini-3.8-flash`), low reasoning, output limits and timeouts remain fixed
for the final comparison. An early-aborted review is never the efficiency baseline.

## B. Measurements and failures found

The initial final-agent request without evidence pages used 11,570 UTF-8 bytes;
its result schema occupied 3,783 bytes. The summary request repeated already
reviewed evidence while its prose summary was subsequently replaced by runtime
counts. Private observations recorded successful reported tokens but did not
durably describe all pending/unknown calls, source delivery sizes or cache usage.

Two development campaigns failed the quality requirement and remain retained:

- **v4.2:** all eight runtime executions completed, but one SQL overclaim was
  incorrectly confirmed after repair. The initial response correctly rejected
  it and proposed an unavailable follow-up target; repair reversed that decision.
  The model had provenance ids but no explicit runtime-admissible target list.
- **v4.3:** six of eight executions passed. A contradiction response copied
  `action_schema` and exhausted the one-repair allowance. The SQL negative also
  produced malformed JSON, then copied that schema on repair. The schema-first
  prefix experiment had no measured cache benefit and was reverted.

Neither configuration is credited with an efficiency win. The two obsolete full
test runs were interrupted and retained, rather than reported as passing.

## C. Changes implemented

After complete verification, the combined seventh role now assembles its report
without another generation. It revalidates exact candidates, causal reviews,
inspection, source integrity, duplicate/conflict relations and snapshot identity,
including on restore. Coverage, uncertainty, follow-ups and rejection decisions
survive. Final acceptance still stamps authoritative specialist/task provenance.
Repeated acceptance no longer duplicates unresolved-disagreement limitations.

Every admitted model call now has a metadata-only checkpoint record before
dispatch, with reserved tokens, requested model/output, request/source-page bytes
and operation id. Returned or unknown outcomes record duration and actual charged
tokens. Provider prompt/output/reasoning/cache splits remain distinct; thinking
and cached-input subsets are not added to token totals again. Missing cached-token
usage remains `null`, rather than being represented as a reported zero. Unknown
completion still charges its full reservation.

Generated schema display titles are removed while properties, constraints and
data defaults remain intact, including fields named `title`. This saves 926 schema
bytes in the measured request; the necessary follow-up scope guidance offsets
part of that saving. Final request size is 11,038 bytes, with the same 3,072-token
output ceiling. The schema-first reordering is absent from the final code.

Verification receives the actual `followup_task_ids`, including an explicit empty
list when no target is admissible. Invalid targets remain rejected by the same
authority check. Safe repair identifies known copied request keys without echoing
their values or arbitrary keys. Extra fields remain forbidden; repair stays capped
at one. Final policy revision is **`review-prompts-v4.4`**.

Existing cache, duplicate-read, model routing and concurrency mechanisms remain.
No integrity check is cached away, model tier downgraded, limit raised, dependency
added or paid explicit cache resource created. Public browser contracts are unchanged.

## D. Verification

The final full suite passed **655 tests**, zero failures/errors/skips, in 730.40
seconds (native exit 0). There are 19 new M21 cases, including restored assembly refusal,
durable unknown charges, token subsets, safe schema repair, follow-up scope,
schema constraints/defaults and repeated acceptance. The final focused checkpoint
passed 57 cases. Updated integration fixtures retain actual interruption, restart,
repair, immutability and source/coverage assertions; counts now reflect removal
of the paid summary call. Inadmissible follow-ups still fail admission.

Frontend tests: **53 passed**, and production build passed. Generated-contract
freshness, Python compilation and diff whitespace checks passed. All **173 final
frozen inputs** match. Eight authority methods and the budget/contract/orchestrator
ASTs are unchanged from the original baseline. Original v4.2/v4.3 before-images
reconstruct their freezes. Configured-credential/Google-key-pattern scanning found
zero leaks. Existing dependency deprecation warnings are unchanged.

The [exploratory integration run](evidence/m21-integration-all.txt) recorded 23 failures caused by assumptions about
the removed call and obsolete pause/repair fixtures. Subsequent receipts retain
the diagnoses and updates, including the [intermediate compatibility run](evidence/m21-updated-compatibility.txt)
and [corrected follow-up pause check](evidence/m21-pre-freeze-focused.txt).
Its result is not substituted for the final full run.

Receipts: [verification summary](evidence/m21-verification-summary.json),
[final backend log](evidence/m21-v44-full-backend.txt),
[frontend exits](evidence/m21-frontend-exits.json),
[static checks](evidence/m21-static-checks.json),
[source integrity](evidence/m21-v44-source-integrity.json),
[source lineage](evidence/m21-source-lineage.json),
[credential scan](evidence/m21-credential-scan.json).

## E. Comparable results

The final **whole eight-execution v4.4 campaign** passed every predeclared runtime,
verdict, source-inspection, finding-count, relation and provenance gate. It retains
six published findings from twelve decisions. Author review read each published
field, rationale, causal basis and relation, with no additional material semantic
flag in this sample. This is not independent human adjudication or full-system
specialist recall: candidates and immutable source artifacts were supplied.

| Live verifier comparison | Completed M20 baseline | Final v4.4 |
| --- | ---: | ---: |
| Executions passing all gates | 8/8 | 8/8 |
| API calls, including repair | 18 | 9 |
| Schema repairs | 2 | 1 |
| Provider prompt tokens | 63,658 | 38,577 |
| Output tokens including unallocated totals | 14,388 | 12,316 |
| Estimated known cost | US$0.10169850 | US$0.07511775 |
| Estimated cost per completed execution | US$0.01271231 | US$0.00938972 |
| Sum of review elapsed time | 146.280s | 122.845s |
| Median review elapsed time | 16.5075s | 14.6725s |

The final sample costs **26.1% less** per comparable completed execution. The
elapsed sample is lower by 16.0% in total, but eight observations without controlled
server load do not establish a production latency improvement or SLA. Generation
and network variability are not attributed to prompt caching.

Separately, six completed seven-role jobs per configuration exercised real stores,
tools, acceptance and rendering with programmed model responses and fixed 50ms
response delay. All five files remained inspected and the same defect remained
confirmed with no failed coverage. Model calls fell **15 to 14**; total prompt bytes
fell **173,720 to 156,670 (9.8%)**. Both used seven required tool calls. Source-page
delivery bytes fell 3,953 to 3,540 because the redundant summary request disappeared;
verification evidence was retained. Offline timing ranges overlap, so no stable
offline latency improvement is claimed.

Allowed concurrency 1/3 was measured; default 3 remains unchanged. Existing-cache
characterization found three cold parser calls and zero on a fresh context over
the same cached snapshot, with equal facts. This is existing behavior, not an M21
cache speedup. No decrease in source-tool calls is demonstrated in these samples;
the existing guards still prevent acknowledged duplicate work.

[Measurements and experiment ledger](evidence/m21-performance-measurements.json),
[live comparison](evidence/m21-live-summary.json),
[manual adjudication](evidence/m21-manual-adjudication.json),
[data/authority boundary](evidence/m21-live-boundaries.json).

## F. Resource accounting

All 24 M21 review attempts remain: **21 passed every gate**, 22 completed runtime.
The earlier false confirmation and two protocol failures remain visible, with
their full charges. No new unknown provider usage, cap refusal or controlled action
injection occurred. The final campaign is selected as a whole; cases are not
picked from different successful attempts.

Cost uses the [official Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing)
checked on 2026-10-21: US$0.75/M input and US$3.75/M output including thinking.
All 1,252 unallocated final-campaign total tokens are priced as output. Reported
reasoning details were unavailable/zero; that is not evidence of zero thinking.
Cache usage was absent in the compatibility responses. No discount is assumed.
[Google documents implicit caching](https://ai.google.dev/gemini-api/docs/caching)
as automatic and recommends common prompt prefixes; that eligibility does not
establish a cache hit here.

| Accounting | US$ |
| --- | ---: |
| v4.2 development campaign | 0.09245550 |
| v4.3 development campaign | 0.10282050 |
| Final v4.4 campaign | 0.07511775 |
| **All M21 live usage** | **0.27039375** |
| **Cumulative conservative usage** | **3.74075775** |
| **Remaining shared budget** | **0.25924225** |

M21 stayed within its US$0.40 allocation and the unchanged shared US$4 grant.
Earlier unknown holds of US$0.09968775 remain included; none were refunded.
Development experiments cost more than one baseline batch and are disclosed
separately from final-configuration efficiency. These estimates are not reconciled
provider bills. No further paid M21 calls are planned.

## G. Remaining limitations and acceptance

The scoped cost objective is demonstrated with comparable successful reviews and
retained quality gates. The model remains fallible; digest/inspection checks do
not prove semantic truth. The small authored sample is not held-out population
accuracy, independent adjudication or broad production-readiness evidence.

The comparison holds the physical model fixed. Alternative models were not
validated live, so no cross-model quality or model-choice recommendation is made.
Provider cache benefit and a source-tool-count reduction were not demonstrated.
The SQL singletons do not establish paired completion within the unchanged
30-second timeout. Partial reports can still retain explicitly unverified candidate
text after failed completion, as documented in M20.

The final configuration retains evidence, budget enforcement and existing source
caching. Extra concurrency and unverified cache/model changes were not used to
produce apparent gains. M22 remains outside this milestone.

## H. Review and delivery

Five-axis author review covers correctness, readability, architecture, security
and performance. The runtime owns deterministic assembly and durable accounting;
models still perform causal judgment. Source/permission boundaries and all seven
identities remain intact. No critical finding remains in the final tested scope;
limitations above remain explicit.

HEAD advanced to `0852674` during the shared session. Review uses fixed baseline
`a24ce50`, preserving that intervening commit. This agent did not commit, push,
open a PR or deploy. [Review receipt](evidence/m21-review.json) and
[complete M21 patch](evidence/m21-production.patch) describe the original-baseline
scope. Work remains in the shared workspace for inspection.
