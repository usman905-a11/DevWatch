# M20 Synthesizer/Verifier Correctness

Subsequent work: [M21](m21-cost-latency-report.md) removes the redundant summary
generation and records a completed-review cost comparison. Historical M20 results
and its paired SQL timeout limitation remain unchanged below.

Date: 2026-10-21. Baseline: `98b3cd0`. Status: **Complete for engineering and scoped verification**. M21 has not started.

## A. Existing implementation

The canonical seven-role graph already enforced immutable snapshots, candidate
admission, scoped evidence, inspection, bounded repair, final acceptance and
accepted-report rendering. M19 improved primary detection/classification but
retained three secondary impact overclaims for this milestone. Source integrity
alone did not establish the truth of every assertion in a finding.

## B. Problems found

Verification could justify a valid core while overlooking unsupported consequences
in its impact. Advisories and restored decisions needed the same complete
inspection checks. Duplicate groups lacked a structured causal-equivalence review;
disagreements and all contributing task identities were not preserved in a report
audit. Model-written summaries could overstate coverage.

The first M20 revision exposed two further issues in live use: extra read-only
provenance in a response produced unhelpful schema-repair field paths, and the
verifier accepted an unsupported memory-saving advisory because it lacked the
existing performance specialist guidance. A full offline run also exposed old
programmed providers that did not emit the new review protocol. These failures
are retained, rather than counted as passes.

## C. Changes implemented

- Added `verification.py` as the shared admission boundary for normal execution,
  final acceptance and recovery. Every completed non-rejected decision requires
  a causal basis, an exact candidate digest and four field assessments: title,
  description, impact and remediation. Unsupported assertions require rejection
  of the whole candidate; positive verdicts require support for all four fields.
- Required complete verifier inspection and the existing repository source gate
  for every reviewed non-rejected verdict, including advisory and uncertain ones.
  Candidate hashes follow the actual delivered batch after context bounding.
- Added evidence-backed duplicate explanations and resolved/unresolved
  disagreements. Equivalent reviewed findings can merge without losing either
  contributor. Unresolved positions remain uncertain and visible.
- Stamped the report audit from runtime decisions and blackboard task/specialist
  provenance. Synthesis cannot alter that audit. Markdown and isolated PDF output
  expose decisions, rejection reasons, field reviews and relations.
- Replaced free-form report summaries with runtime counts and recorded coverage.
  Recovery rejects valid bound reviews containing an explicitly unsupported field;
  interrupted or legacy missing review can survive only as explicitly unverified,
  low-confidence uncertainty with failed coverage. Planner failure is attributed
  to the planner.
- Added optional browser report-audit support and regenerated the public schema.
  The updated browser accepts older persisted reports. This does not establish
  compatibility of old strict browser versions with new server fields.
- In v4.1, reused existing `performance_cost` guidance only for source-delivered
  verification of actual performance-origin candidates. Improved safe repair
  paths for known review fields and read-only provenance, without echoing arbitrary
  response values or relaxing extra-field rejection or the one-repair allowance.

Existing offline providers now explicitly supply the required review response as
test fixtures. The independent contract-probe detection algorithm, gold labels,
thresholds and live provider responses were not changed to obtain passing results.
No dependency or agent framework was added.

## D. Tests executed

The final frozen v4.1 tree passed **636 backend tests**, zero failures/errors/skips,
in 1146.93 seconds. This includes **40 new M20 cases**; the final focused run passed
all 40 in 6.15 seconds. Coverage includes missing/stale/partial reviews, unsupported
fields, inspection, final acceptance, duplicate/conflict handling, provenance,
restart/partial recovery, bounded hashes, safe repair and actual prompt assembly.

The updated frontend passed **53 tests**, including three new wire compatibility
checks, and its production build. A two-page PDF preview was rendered and visually
checked; text stayed inside page bounds. This preview establishes layout only.

Generated-contract freshness, Python compilation and `git diff --check` passed.
All **168 frozen source/consumer inputs** match. Original v4.0 before-images also
reconstruct its complete freeze. Eight authority methods have identical ASTs to
the baseline. Credential scanning found zero configured-key or Google-key-pattern
leaks. Existing LangSmith/Vite dependency warnings remain; no dependencies changed.

The interrupted v4.0 full run is retained separately and is not a successful full
run. Its protocol-fixture and old summary assertion failures were corrected before
the fresh v4.1 regression. Native frontend exit receipts disambiguate the earlier
PowerShell stderr-redirection exit from the actual successful test/build commands.

Receipts: [verification summary](evidence/m20-verification-summary.json),
[backend log](evidence/m20-v41-full-backend.txt),
[frontend exits](evidence/m20-frontend-exits.json),
[static checks](evidence/m20-static-checks.json),
[source integrity](evidence/m20-v41-source-integrity.json),
[credential scan](evidence/m20-credential-scan.json).

## E. Live evaluation

Used the existing Gemini key with `gemini-3.8-flash`, approved synthetic
source/contracts and fixture-derived supplied candidates. Labels never entered
provider requests. The real verifier/synthesis subgraph, inspection receipts,
checkpoints and final acceptance gate executed. Source artifacts were supplied;
Planner/specialist generation, full-system recall and autonomous retrieval were
not evaluated. Runtime provenance identifies supplied task origins, not newly
executed specialists.

Final v4.1 selection covers **nine logical challenges in ten verifier executions**.
All selected runtime and expected-verdict gates pass. Sixteen candidate decisions
contain eight confirmed verdicts, seven rejections and one advisory. One verified
duplicate pair yields **eight published findings** with both contributors retained.
Manual author review read every published field, decision rationale, causal review
and relation against source/contracts, finding no additional material semantic
issue in the selected outputs. This is not independent human adjudication.

| Challenge | Final observed behavior |
| --- | --- |
| Unspecified handle type | Reject file-handle impact; preserve missing-close defect |
| SQL privileges/disclosure | Reject extended impact; preserve SELECT predicate manipulation |
| Arbitrary SQL execution | Reject arbitrary execution; preserve narrow source-backed defect in separate reviews |
| Empty-input domain extension | Reject added dict/non-sequence consequences; preserve empty-list defect |
| Mutation domain extension | Reject added tuple assertion; preserve mutable-list mutation |
| Unproved memory saving | Reject unsupported list/dict allocation recommendation |
| Equivalent contributors | Publish one finding and retain both decisions/origins |
| Contradicting positions | Confirm the exception behavior; reject the false safe-return position |
| Valid complexity advisory | Preserve quadratic list-membership advice with no measured latency claim |

All **20 paid review attempts** remain in four journals: 17 completed runtime,
16 passed every expected gate. Earlier failures comprise two SQL pair timeouts,
one exhausted empty-case schema repair and one false memory advisory. The final
selection uses the latest attempted journal/strategy, irrespective of success.
After two unchanged 30-second timeouts, the arbitrary-SQL pair was evaluated as
two single candidates. Both passed with unchanged source and acceptance gates.
**This does not establish paired SQL completion within that timeout.** No timeout,
budget, output ceiling or permission was increased to obtain these results.

The valid complexity control was added after observing the memory false positive
to check that guidance did not suppress legitimate performance advice. This is an
authored regression sample, not held-out accuracy or an improvement benchmark.

Receipts: [live summary](evidence/m20-live-summary.json),
[final selection](evidence/m20-final-live-selection.json),
[manual adjudication](evidence/m20-manual-adjudication.json),
[data/authority boundaries](evidence/m20-live-boundaries.json),
[retained unknown holds](evidence/m20-unknown-holds-02.json).

## F. Resource usage

Reserved M20 allocation: at most US$0.55 within the existing shared US$4 grant.
No extra grant was assumed. Serial TLS-verified calls used durable reservations
before dispatch; batches stopped on unknown usage. Both unknown reservations
remain fully held and fresh campaigns acknowledged them before proceeding.

There were 43 API attempts: 41 returned `stop`, two timed out with unknown usage;
six responses were schema-repair requests. No controlled action injection or local
cap refusal occurred. Known usage was 155,320 prompt and 39,234 output/thinking
tokens. Using the [official pricing](https://ai.google.dev/gemini-api/docs/pricing)
checked on 2026-10-21 (US$0.75/M input, US$3.75/M output including thinking):

| Accounting | US$ |
| --- | ---: |
| Known M20 usage estimate | 0.26361750 |
| Retained M20 unknown reservations | 0.05854350 |
| Conservative M20 total | **0.32216100** |
| Cumulative conservative total | **3.47036400** |
| Remaining shared budget | **0.52963600** |

The earlier M18 US$0.04114425 hold also remains included. Combined unknown holds
are US$0.09968775. These are conservative estimates, not reconciled provider bills.
No cost or latency improvement is claimed from comparing different review sizes.

## G. Remaining limitations and acceptance

M20 is complete for the specified mechanisms and observed scoped cases. Explicit
model judgments plus structural checks improve accountability but do not create a
semantic oracle. A model can still mark an unjustified assertion supported.
Hash-table performance advice assumes conventional expected lookup behavior;
there is no worst-case guarantee or measured speedup.

Raw interrupted reports can retain unsupported original text only as unverified
low-confidence candidates with failed coverage. They are not confirmed findings or
successful semantic evaluations. Historical journals and the M19 report are not
rewritten to hide such text. Paired SQL latency remains a known limitation.
Broader real-project accuracy, independent adjudication, M21 cost optimization and
M22 infrastructure remain outside this milestone.

## H. Review and delivery

Author review covered correctness, readability, architecture, source/credential
boundaries and performance. Shared admission removes divergent semantic rules
from normal/final/recovery paths. Changes retain the existing canonical graph,
seven identities, scope, budgets, literal rendering and isolated PDF worker.
No blocking finding remains for this scoped change; the limitations above remain
explicit. [Review receipt](evidence/m20-review.json) and
[review patch](evidence/m20-production.patch) record the inspected scope.

No commit, push, PR, deployment or M21 work was performed. Implementation and
evidence are left in the shared workspace for review.
