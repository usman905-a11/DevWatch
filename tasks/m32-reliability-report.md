# M32 previous-milestone reliability closure

2026-10-24. Status: COMPLETE for the three reproduced conservative-policy gaps.
The original automatic-confirmation quality gate remains unmet. This report does not supersede the
historical partial M23/M27/M28/M29/M30 quality results.

The user's request is to fix previous-milestone issues, then stop before changing
folder upload or live-stream presentation. The M31 report already completed its
selected engineering scope. Its remaining automatic-proof and broad-accuracy
limits are capability/evaluation boundaries, not evidence of a broken seven-agent
orchestration. The current work closes three newly reproduced gaps in that policy.

## Reproduced issues and fixes

1. An already-uncertain model decision could retain confidence 0.79, including at
   final acceptance, despite the M31 publication ceiling of 0.5. All canonical
   uncertain decisions now receive the ceiling. Acceptance independently rejects
   an inflated persisted decision, and recovery applies the same normalization.
2. Finding identity excluded remediation. A follow-up could overwrite an earlier
   proposed remedy while retaining the same identity. Identity now includes that
   claim field; distinct remedies remain separate candidates. Repeated identical
   submissions still merge bounded evidence without losing previous failures.
3. Downgrading model votes discarded duplicate relations, while already-uncertain
   votes could still suppress different claims through model equivalence alone.
   Canonical duplicate groups are now rebuilt by comparing complete identical
   fields, immutable location, verdict and evidence-gap statuses. Only exact
   copies merge; all decisions and contributor provenance remain in the audit.
   Different prose, remedies, locations or gaps remain separate. Acceptance
   rechecks exact equality so old relations cannot suppress a different claim.

The verification policy version changes from `independent-claims-v3` to `v4`;
pending old verification must be adjudicated under the current policy. Previously
published reports remain historical immutable reports. No model vote or passing
arithmetic predicate is promoted to independent whole-claim proof.

## Verification evidence

- Red: seven expected failures in `evidence/m32-red.xml` reproduced the above gaps.
- Initial green: 46 focused regressions passed (`m32-focused-01.xml`).
- Additional recovery/idempotence/negative cases: 10 passed
  (`m32-focused-03.xml`). The preceding added recovery test had one incorrect test
  fixture type, retained in `m32-focused-02.xml`; it was corrected before freezing.
- Frontend: all 57 tests and TypeScript/Vite production build passed. Existing
  Vite plugin deprecation warnings remain. Wire schema freshness passed.
- The initial serial baseline was deliberately stopped before production edits;
  it is not counted as a passing suite. The full suite ran in four isolated
  processes against frozen source hashes: 811 distinct identities, five failures,
  no errors/skips. Two M14 assertions expected duplicate report copies and now
  require one finding plus all two/five contributor decisions and provenance.
  Three other failures hit 8/25-second client waits under parallel test load.
  A concurrent diagnostic also hit the normal runtime test's 20-second wait.
  The complete four affected files were rechecked without competing workers:
  all 43 tests passed, with no deadline/retry increases or production edits.
  Every one of the 811 original identities is accounted for with a final pass,
  no omitted/duplicated identities, errors or skips. This is a full run plus
  rechecks, not a claim that the first complete suite command exited zero.
  Timing sensitivity under heavy test load remains explicit, not an established
  production latency SLA. See `m32-backend-reconciled.json`,
  `m32-backend-01/summary.json` and `m32-backend-recheck-01.xml`.

Self-review found no remaining required change in this three-item scope. The
source freeze confirms identical production code across full regression, live
verification and rechecks; only the two M14 test expectations changed. Credential
scan found zero literal configured-credential leaks in changed files and new
campaign artifacts. No new dependency, model policy prompt, tool permission,
runtime budget, retry limit, or public transport field was introduced.

## Live regression and finances

The original approved public bitcount defect/clean payloads were rechecked with
Gemini under a preregistered US$0.16 cap in the existing public envelope and shared
US$9 total. No additional payloads, working-repository source, gold labels, trace
exports or reasoning text were sent. No responses were injected. Source/contract
payloads and local source hashes were checked before dispatch.

Both reviews completed normally with complete source coverage and passed the
conservative policy check. The defect report contains one uncertain finding at
confidence 0.5; the clean report contains none. Original screening: TP1/FP0/FN0,
zero duplicates. Original strict classification: 1/2 passes because the defect
remains uncertain. That strict failure is retained, not reclassified as success.

Eleven model calls cost an estimated US$0.04930275. Shared conservative usage is
US$7.57389975, with US$1.42610025 remaining. Original public envelope usage is
US$0.84043050 of US$1.40. No new unknown effects or cap refusals occurred. All
historical US$0.12293325 unknown holds remain charged. Pricing was checked against
the [official pricing page](https://ai.google.dev/gemini-api/docs/pricing) on
2026-10-24; provider billing remains authoritative.

Evidence: `m32-public-protocol.json`, `m32-public-preflight.json`,
`m32-public-live-run-01.json`, `m32-public-settlement.json`. A copied harness's
incorrect approval-file path failed an offline preflight before any call and is
retained in `m32-live-preflight-failure-01.json`.

## Limits that remain explicit

No trusted general whole-claim proof adapter exists. Free-form explanations,
remedies and semantic equivalence remain model judgments and are not published as
confirmed facts. The original automatic-confirmation release gate remains unmet.
Fresh representative model-quality evaluation has not been established by two
already-exposed fixtures or offline scripted tests. Nonidentical uncertain
alternatives are retained, so semantic duplicates can still appear. These are
not claims of full model accuracy or universal program correctness.

Full-folder upload, a new file-tree UI, expanded event streaming, coding/editing
agents and local-model work are outside this change. Stop after verification and
reporting; no commit, push or deployment is authorized.
