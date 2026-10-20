# M18 secondary-claim follow-up

Date: 2026-10-20. Status: **Live fix verified; full backend pending**.

## A. Existing implementation

M18 v2.3 generated correct primary findings but its final empty-input finding
added KeyError/TypeError alternatives, and its mutation finding added failures
for tuple/non-list inputs. Both were confirmed despite unspecified input domains.
Original journals, annotations, source receipts and scores remain unchanged.

## B. Diagnosis and failing evidence

Verification rationales proved only the valid core, ignoring appended clauses
in description/impact. Shared prohibitions were insufficient. The consuming-model
failures are retained in m18r-red-claims.json; the local known-fixture screen
reproduces both in m18r-red.txt. That screen is not a general semantic oracle.

## C. Fix

Version review-prompts-v2.4 changes only progressively loaded phase guidance.
Specialists choose one documented minimal input witness and describe its direct
expected/actual difference, without adding undocumented types, exception classes
or downstream capabilities. Verification audits every description/impact/remediation
clause, including parentheses, instead of proving only the title/core. Unsupported
text requires rejection or concrete narrower follow-up, preserving the valid core.
No source/evidence permissions, wire types, scoring labels or raw findings change.
This is a prompt fix; M20's runtime semantic-verifier work remains separate.

## D. Verification

Focused graph, SDK, restart and control checks: 33 passed in 7.82s. Fresh full
backend against 155 frozen source/fixture files is pending. Policy prose is
evaluated through the actual consuming model, not string-presence assertions.

## E. Live results

Only the five previously approved synthetic fixtures/contracts, policies and
fixture-derived results were sent to Gemini. Calls were serial, TLS verified,
trace export disabled, with reservation journals before API effects. Additional
allocation US$0.35, unchanged cumulative US$4 cap and prior unknown hold retained.

First batch: all five reviews complete with full source/goal coverage, four true
primary findings, no false positives/misses, and no unsupported secondary clauses
on manual review. A repeat again produced narrow empty-input/mutation findings.
Its SQL review hit the local pre-dispatch cost guard, leaving a partial explicitly
unverified candidate; its added non-string TypeError claim remains flagged.
A fresh SQL-only recheck completes with narrow source/contract-supported text.

All 11 attempts remain: raw 9 TP/0 FP/0 FN; 10/11 with complete source/goal
coverage and no failed coverage. All five fixtures' latest attempts pass. Eight
findings from fully completed reviews have supported clauses. The one partial
finding is not retroactively repaired or counted as fully verified. New unknown
API consumption: zero; one local cap refusal. See m18r-manual-adjudication.json.

## F. Cost

| Batch | Cap US$ | Conservative charge US$ |
|---|---:|---:|
| Five fixtures | 0.25 | 0.11904000 |
| Five-fixture repeat, retained partial SQL | 0.15 | 0.11021925 |
| Fresh SQL recheck | 0.10 | 0.02698350 |

Caps apply serially to each batch and are checked against the US$0.35 follow-up
allocation; they are not simultaneous additive spend. Total new charge:
**US$0.25624275**. Cumulative conservative charge: **US$2.38591575 of US$4**.
Remaining shared budget: **US$1.61408425**. The original US$0.04114425 HTTP 503
unknown reservation remains charged. No new unknown consumption is refunded.

## G. Limits and acceptance

The two originally observed confirmed overclaims are resolved in fresh completed
reviews, without losing the valid defects. Repeated authored fixtures do not
establish universal semantic correctness or held-out improvement. A partial
review can retain unverified candidate text; the failed SQL attempt demonstrates
this and remains explicit. Source-backed provenance alone does not verify every
semantic clause. Manual review is by Codex, not an independent human assessor.
Advice/defect classification and new defect families are M19 evaluation targets.

## H. Delivery

Production change: prompts.py phase guidance/version only. Existing dirty work is
preserved. Initial M18 receipts remain historical; follow-up receipts use m18r
filenames. Full regression/source/credential receipts are pending. M19 follows
this fix; no M20 implementation, commit, push or deployment occurred.
