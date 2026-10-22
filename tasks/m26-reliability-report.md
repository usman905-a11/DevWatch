# M26 - Targeted schema recovery and fresh controls

Complete for scoped engineering and live verification, 2026-10-21.

Issues 5, 7 and 9. A rejected candidate's actual validation paths and error
types now identify the missing field within the existing single schema repair.
Field names come from the known schema; arbitrary keys and all values are omitted.
The model must provide impact itself. Invalid candidates are never filled with
fabricated text, and an unsuccessful repair still stops/quarantines the output.

Two fresh regression tests first failed on generic repair guidance, then passed;
20 focused checks passed. Eight new authored defect/clean fixtures were frozen
before model calls: one-shot iterators, closure capture, unequal zip lengths and
the specifically scoped test_inside assertion. Owned witnesses validate all eight.
The assertion contract includes boundary controls and excludes broader test-input
advice. Exposed M23 labels and their ambiguous case remain unchanged.

## Frozen live verification

| Cohort | Strict passes / planned |
| --- | ---: |
| controlled-parser-fault | 1 / 1 |
| exposed-regression | 2 / 2 |
| fresh-authored | 24 / 24 |

| Mode | Passes / planned |
| --- | ---: |
| full, autonomous | 8 / 8 |
| specialist, autonomous | 8 / 8 |
| specialist, provided | 10 / 10 |

Every planned case is retained. A strict pass requires normal completion,
acknowledged complete source-line ranges, no primary FP/FN and correct finding
kinds. Primary matches use facets/location/evidence; they are not independent
whole-claim accuracy. Entire emitted findings also received separate author
review, with its exact journal hash and denominator recorded locally.

### Retained raw specialist findings

These are unverified specialist outputs; the complete review did not publish
the stated unsupported clauses. Primary screening passes do not erase them.

- Trial 9, m26-iterator-summary-defect: Impact overgeneralizes incorrect zero sums to every nonempty one-shot iterator; nonempty inputs summing to zero still have the correct total. The supplied nonzero-sum witness and one-pass fix are valid.
- Trial 11, m26-closure-binding-defect: Description adds NameError for empty input, but an empty list creates no callable to invoke. The distinct-integer late-binding witness and default-argument repair are valid.
- Trial 17, m26-iterator-summary-defect: Same nonempty-versus-nonzero-sum impact qualification as trial 9; core witness and single-pass fix valid.

Raw specialist generation therefore does not pass a universal whole-claim
truth gate. The scoped engineering/verified-production checkpoint is distinct.

The controlled parser fault removes only impact from the first real candidate
response on an exposed sibling-path fixture. Its original response remains
available; a subsequent unmodified model response supplies the repaired field.
The single injection, targeted guidance, normal recovery and source-backed
defect retention are checked separately. It is not a natural model-error rate
or part of fresh-holdout quality denominators.

M26 retains the pre-M27 SDK absence/zero ambiguity. A campaign-harness filter
also produced no thinking-counter denominator; those zeros are not published
as availability measurements. M27 corrects the SDK and counter extraction.

## Checks, cost and remaining limits

Complete default backend collection: **745 passed**, all native
workers zero; exact collected test identities matched with no skips/omissions.
Wire parity, compilation, diff checks, source hashes and credential scan passed.
Frontend code is unchanged from M24; its earlier 55-test/build result is not
presented as a newly executed check.

M26 cost **US$0.30157800**. Conservative shared spend **US$6.42173700 / US$9**; remaining **US$2.57826300**.
No new unknown effects or campaign cap refusals; historical US$0.09968775
unknown holds remain charged. All usage is reconciled from raw token counts.

Small paired cases are correlated. Public algorithms can occur in model
training; these are not broad production repositories. Fresh authored cases
were not retuned after results. Author review is not independent human review.
Alternate-provider independence, arbitrary semantic correctness, severity
accuracy, causal tool necessity and production SLAs remain unproven. The
engineering checkpoints do not establish universal reliability.

Evidence: `evidence/m26-closing-review.json`, `m26-protocol.json`,
`m26-frozen-sources.json`, `m26-source-archive.json`, `m26-live-run-01.json`,
`m26-live-exits.json`, `m26-backend-01/summary.json`, and `m26-whole-claim-review.json`.
No commit, push, pull request or deployment was performed.


The first backend run retained one five-second test coordination timeout.
The same test passed three isolated checks, then its entire worker group was
rerun on unchanged sources. `reconciled-summary.json` combines that full group
with the other passing groups and verifies the exact complete collection.
The original failed receipt/log is preserved. This is not a first-attempt
all-green claim. The coordination guard is addressed in M27.
