# Milestone 11 - Real Agent Evaluation

Status: **Milestone 11 complete** (2026-10-18). The measured Gemini configuration
**Needs Improvement**: all 12
full-system runs stopped at the Planner and found none of six expected issues.
Stop before M12.

## Scope and implementation

The original seven-agent architecture is unchanged: Planner, five existing
specialists and the combined Synthesizer/Verifier, with deterministic orchestration,
real tools/evidence/blackboard, bounded subgraphs and accepted report rendering.
No runtime contracts, roles, dependencies, services or frontend files changed.

- `scripts/evaluate_agents.py`: versioned 12-sample corpus, allowlisted reviewer
  input, independent gold labels, one-to-one matching, local usage/cost guard,
  individual/full runtime execution, evidence/checkpoint/event metrics, grouped
  summaries, six-category trace triage and offline semantic/tool adjudication.
- `scripts/run_agent_evaluation.py`: explicit fixture/live/rescore modes, required
  live rates/cap, exclusive result creation, per-case durable observations,
  disabled ambient tracing and stop-on-unknown-provider-completion behavior.
- `scripts/evaluate_reviews.py`: fixes the previous 60-case evaluator's
  presence-only scoring. An unrelated claim on a defective case is now FP + FN.
- `tests/evaluation_provider.py`: deliberately narrow scripted test utility;
  recognizes only literal unguarded empty-input indexing, never receives labels.
- `tests/test_m11_evaluation.py`: 42 cases covering scoring, corpus witnesses,
  actual individual/full runtime paths, negative controls, provenance, accounting,
  manual judgments, CLI boundaries, provider exclusion and partial model failures.
- `tasks/m11-pricing.json`, README, plan/todo/progress: reproducibility and usage.

## Dataset and matching

Six paired families, each defective and repaired: empty-input reliability,
in-place mutation, missing test assertion, SQL injection, quadratic list
membership and JavaScript page-offset logic. All five specialists are represented;
the test-gap and unmeasured-complexity labels are advisories. The other labels are
defects. Each pair shares its public behavior contract. Labels specify exact
file/line ranges, required causal facets, severity, kind and an independent
explanation. Pytest witnesses establish that each defect violates its contract
and each repair passes, including a wrong-result mutation of the test target, an
in-memory SQLite injection witness and counted comparisons rather than timing.

Only files and their public contract cross the reviewer-input boundary. Individual
mode invokes the actual assigned specialist subgraph without a fake Planner or
Verifier. Full mode invokes the unchanged canonical workflow, which chooses its
own specialists. The contract is an ordinary snapshot document in full mode.
No gold roles, labels, facets or severity reach the full-system provider.

Automated matching requires all independent text facets, overlapping gold file/line
location and valid snapshot source evidence. Maximum bipartite matching assigns
each claim and label at most once; extra claims are false positives. This fixes
both presence-only scoring and duplicate-inflated recall. The full score covers
reported claims across accepted defect/uncertain/advisory groups; raw specialist
candidate scores are recorded separately. It does not equate an uncertain claim
with a confirmed defect. Human annotations can override semantics, never invalid
provenance/location. Text matching is explicitly a conservative screen, not a
semantic oracle; source-backed text can still contain a wrong causal assertion.

Partial investigations, invalid model schemas and budget exhaustion remain in the
quality denominator. External provider failures and failed job execution are
marked unavailable rather than scored as model reasoning misses. Trace triage
uses model_reasoning, tool_harness, evidence_retrieval, orchestration, verification
and finalization. These are investigation hints; root-cause confirmation requires
inspection, especially when malformed Planner output prevents dispatch.

## Verification and local harness observations

- Scorer red: 14 expected failures before implementation.
- Real-runner red: five expected missing-feature failures; subsequent real-store
  runs exposed/corrected an evaluation-only method-name mismatch.
- Legacy regression red: an unrelated finding incorrectly scored (TP=1, FP=0,
  FN=0); green now records (0, 1, 1).
- Provider-exclusion and incomplete-adjudication regressions: three expected
  failures, then corrected filtering/validation.
- Reasoning/missing-usage red: two expected failures, then the meter includes
  unallocated total tokens as output and keeps unknown usage reserved.
- Partial-review red: catches exclusion of model failures from quality; corrected.
- Final focused check: 42 passed in 16.85s (`evidence/m11-focused-final.txt`).
- Full backend: **413 passed**, one existing LangSmith SDK wrapper deprecation
  warning, in **669.86s**. JUnit confirms zero failures, errors or skips and all
  42 new M11 cases. Evidence: `m11-backend-final.txt`, `m11-backend.xml`.
  Two earlier runs were stopped while correcting the new meter/filter; they are
  retained as aborted logs, not passing evidence. The final full run uses fresh
  system temp outside the repository and includes both final corrections.
- Contract export freshness, Python compilation and whitespace checks: passed;
  repeated after final source changes. No frontend changes required browser/build
  verification for this milestone.

The 24-run fixture matrix completed with real stores, tools, specialist subgraphs,
full graph and rendering. It detects exactly its one scripted bug family: full
screen TP=1, FP=0, FN=5, recall 1/6; individual roles likewise miss five labels.
This deliberately poor scripted recall proves the evaluator detects misses.
`live_model_accuracy` is null. These numbers never establish actual model quality.
Evidence: `evidence/m11-fixture-results.json`, `m11-fixture-run.txt`.

## Live run configuration and spending

The user authorized live provider use up to USD 2 and then selected the existing
Gemini key. Credentials were loaded only into the child process from local `.env`;
no key, credential file, global settings or persistent environment was changed.
All three evaluation tiers use the already configured `gemini-3.8-flash` model;
the seven agent identities and tier policies remain distinct and unchanged.

Paid text rates used are USD 0.75 input / 3.75 output per million tokens, including
thinking, from [Google's current pricing](https://ai.google.dev/gemini-api/docs/pricing.md)
(checked 2026-10-18; the listed promotional period ends 2026-12-31).
Compatibility follows [Google's OpenAI endpoint documentation](https://ai.google.dev/gemini-api/docs/openai.md).
Google's skills catalog was retrieved and checked; its matching Gemini skills
cover enterprise/Vertex routes, so none applied to this existing Developer API
adapter. Official Developer API documentation was used directly.

Initial OpenAI attempts returned a network failure and then HTTP 429; a minimal
diagnostic confirmed `insufficient_quota`. No OpenAI accuracy or billed cost is
claimed. Preliminary OpenAI model-rate checks used official
[GPT-4.1 Mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini) and
[Nano](https://developers.openai.com/api/docs/models/gpt-4.1-nano) pages.

The first Gemini attempt was stopped after observing total tokens larger than
prompt plus completion: the initial evaluator meter had omitted that difference.
The production runtime already charged the larger total. Added regression tests
and corrected the evaluator to price unallocated reasoning tokens as output.
Its retained token ledger bounds that interrupted attempt at USD 0.2213475 by
pricing every charged/reserved token at the output rate. Two OpenAI request
reservations bound at USD 0.0598944 plus a minimal diagnostic allowance keep all
preliminary attempts under USD 0.30. See `m11-interrupted-accounting.json`.

The corrected batch has a USD 1.65 cap. It saved 13 observations before a provider
timeout on the security specialist and stopped, retaining USD 0.13974525 in the
cost guard, including the unknown call. A remaining-case batch has a USD 1.45 cap:
0.30 + 0.13974525 + 1.45 < 2. Final provider bills remain authoritative; no claim
is made that an unknown completion was free. Cost estimates ignore cache discounts
and may therefore exceed billed cost. Earlier preliminary undercounted estimates
are superseded by this conservative accounting.

## Live results

Completed 24 case/mode evaluations: 12 individual and 12 full-system. Retained 26
attempts because security/performance requests each needed a retry after provider
timeouts. Latest attempts define the 24-row comparison; earlier attempts and
their charged reservations remain in `evidence/m11-live-reviewed.json`. All
selected runs have known provider completion; none is excluded from quality.
Normalization of earlier saved eligibility flags uses the final partial-review
rule, rather than their superseded coverage-failure filter. Results are not
cherry-picked by finding count.

| Evaluated claims | TP | FP | FN | Precision | Recall |
|---|---:|---:|---:|---:|---:|
| Individual specialists together | 2 | 0 | 4 | 2/2 | 2/6 |
| Full system | 0 | 0 | 6 | undefined (no claims) | 0/6 |
| Bug/reliability (2 samples) | 1 | 0 | 0 | 1/1 | 1/1 |
| Logic/correctness (4 samples) | 0 | 0 | 2 | undefined | 0/2 |
| Quality/testability (2 samples) | 1 | 0 | 0 | 1/1 | 1/1 |
| Architecture/security (2 samples) | 0 | 0 | 1 | undefined | 0/1 |
| Performance/scalability (2 samples) | 0 | 0 | 1 | undefined | 0/1 |

The six labels include four behavioral/security defects and two advisories.
Separately, individual behavioral-defect recall is 1/4 and advisory recall is
1/2. These are reported-claim detection metrics, not confirmed-defect precision.
The quality specialist correctly described the missing assertion but emitted
`kind=defect` where the dataset expected an advisory. Causal matching intentionally
does not hide that classification discrepancy. Zero false positives on so few
returned claims is weak evidence of precision, especially with incomplete reviews.

Author inspection confirmed both emitted claims: immutable source establishes
unguarded indexing for the empty-input finding, and a test without an assertion
passes an independently injected wrong return value. Evidence and overlapping
file/line localization are correct for 2/2 emitted findings. Duplicate claims:
zero. Broad ranges (function lines 1-2 / test lines 1-3) overlap the labelled cause;
this measures correct localization, not exact-line minimality. These annotations
are Codex author checks, not independent human judgments. `human_reviewed=false`
and `live_model_accuracy=null` remain explicit; screening/author-check results are
reported separately. See `tasks/m11-adjudications.json`.

| Runtime metric (selected evaluations) | Individual specialists | Full system |
|---|---:|---:|
| Model calls | 40 | 20 |
| Tool calls / successful results | 21 / 9 | 6 / 5 |
| Fully acknowledged source fraction, mean | 41.7% | 0% |
| Latency, total / mean seconds | 220.343 / 18.362 | 97.094 / 8.091 |
| Prompt tokens | 99,509 | 42,552 |
| Output including unallocated thinking tokens | 14,635 | 2,478 |
| Runtime ledger tokens | 114,144 | 45,030 |
| Supplied-rate review cost estimate | $0.129513 | $0.0412065 |
| Repeated identical-evidence calls | 0 | 0 |
| Reviews without a failed coverage entry | 0/12 | 0/12 |

Early failures make full-system latency/cost appear low; these numbers are not
performance wins. Retrieved source is not counted as inspected until fully
delivered and acknowledged. All observed successful tools were source reads.
Author tool review covers 15/27 operations: 14 useful first scoped source reads
and one unnecessary `git_diff` request against a snapshot without captured Git
diffs. Appropriate selection among this judged subset is 14/15; one unnecessary
call is established. Twelve failed source requests remain unjudged for causal
necessity because their arguments are not in saved observations. This selected
subset is not an unbiased estimate of all tool selection. Repeated identical
evidence (zero) is a separate proxy, not proof that no calls were unnecessary.

The four completed live batch guards retain $0.26326275, including earlier timeout
reservations and retries. Adding the $0.30 bound for preliminary attempts gives a
conservative overall bound of **$0.56326275**, below the authorized $2. The selected
24 comparisons alone estimate $0.1707195. Provider invoices were not queried;
these are token/rate estimates, not a claim about actual debits.

The corpus digest is
`9b154126d994a70dffbd0d60c3bfe7739dba3b2fcab8b788b7d9d4ed0f027163`.
Raw batches are `m11-gemini-{final,remaining,tail,performance-retry}-results.json`.
The reviewed result retains every raw attempt plus selection/source filenames;
`m11-reviewed-summary.txt` is its readable summary. The local combination script
`output/m11-combine.py` applies the checked annotations, recomputes eligibility
using final evaluator rules, selects the latest case/mode attempt, asserts all
24 expected keys and the spending bound, and keeps human-review flags false.

## Failure analysis and remaining issues

1. **Planner/model interface and orchestration:** all 12 full reviews stopped
   before specialist dispatch: three `invalid_schema`, seven `provider_incomplete`
   and two `budget_exhausted`. No live full-system Verifier/Synthesizer ran, so
   their reasoning quality is unmeasured, not successful. The M10 and M11 fixture
   paths still exercise those roles. Preserve exact schema/finish classifications
   and reproduce model responses before changing prompts or parsing behavior.
2. **Tool/harness and retrieval:** twelve specialist source requests failed;
   the mutation case made six failed requests before one successful source read.
   A correct tool name alone did not ensure valid arguments or inspected evidence.
   Only five of twelve individual samples achieved complete source acknowledgment.
   Add actionable bounded range feedback and evaluate recovery in a follow-up;
   do not weaken tool permissions or evidence inspection gates.
3. **Stop-reason contract:** two correct specialist claims supplied narrative
   stop reasons. `SpecialistResult.stop_reason` accepts arbitrary nonempty strings,
   while `_stop` treats every reason except `evidence_complete` as failed coverage.
   This schema/runtime mismatch is directly visible in the retained observations;
   it explains failed coverage despite valid candidates. Resolve in a scoped
   follow-up rather than count failed coverage as an exclusion from quality.
4. **Model reasoning:** four expected specialist issues were missed. Failure to
   acknowledge evidence or finish a structured result limits conclusions about
   underlying causal reasoning. The automatic triage category is not proof of
   root cause; failed tools can reflect poor model arguments or harness behavior.
5. **Verification/finalization:** not reached by the full live runs. No finding
   exists to assess live deduplication or verifier rejection quality in this run.
   Zero duplicate outputs is not evidence of good live duplicate resolution.
6. **Provider reliability:** two provider timeouts were retained and retried;
   OpenAI's quota failure is independent of the measured Gemini review quality.

The milestone's evaluation work is complete even though the project fails this
live quality baseline. No runtime bug above was silently patched into this
evaluation-only milestone. Review and prioritize these findings before claiming
strong review accuracy or expanding the test corpus.

Severity accuracy cannot be measured: the production finding contract emits no
severity. Confidence is not severity. Semantic evidence and causal tool usefulness
need explicit manual judgments; successful-tool fraction, inspected-source fraction
and repeated identical-evidence calls are labelled proxies. Small transparent
paired samples give a useful local baseline, not a statistically independent or
repository-scale benchmark. No M12/M13 changes, commits, pushes or deployment.
