# M29 claim consistency - PARTIAL, experiment withdrawn

The policy experiment did not resolve whole-claim reliability. All four public
live reviews passed primary detection/kind/source coverage, but a full published
finding and one raw specialist finding still contained false bit-operation
explanations. The critic also rejected a separate correct arithmetic claim.
Another candidate preserved recall, hiding that rejection in the primary score.
The three further planned synthetic reviews were not dispatched after this
failure. No repeated generation was used to replace an unfavorable result.

The full defect review correctly traces 2 -> 3 -> 1 -> 1 and proposes the correct
AND repair. Its additional claim that XOR flips the lowest set bit is false:
3 XOR 2 = 1 leaves bit zero set. Both verifier passes nevertheless supported
that description. A different candidate correctly said a positive odd input
becomes 1 and then stays there. The critic objected that 3 XOR 2 equals 1 rather
than 3, which does not contradict that candidate. Source receipt validation and
conservative reconciliation of model statuses cannot independently resolve
shared semantic mistakes. See [the causal diagnosis](m29-causal-diagnosis.md).

v5.2 guidance required derivation from actual arithmetic and consistent
quantifiers across fields. After the live failure, its exact source was archived
and the unsuccessful policy was withdrawn. Final production policy is v5.1;
all 153 runtime/test/script/README files are byte-identical to M28's verified
runtime. The retained bounded caller-context fix is unchanged.

Verification is separated by version:

- M28/v5.1: all 757 default-collected backend tests passed, exact identity match,
  four native zero exits and no skips. Final runtime bytes match that run.
- M29/v5.2 experiment: all 757 default-collected backend tests also passed with
  exact identity match and no skips. This did not make its live semantic gate pass.
- Restored final v5.1: 42 relevant checks freshly passed after restoration;
  generated-wire parity, compilation, diff checks and credential scan passed.

No frontend source changed; the frontend result remains the earlier M24
55-test/build verification, not a new browser run. The previously approved two
LangSmith trace writes/readbacks were not repeated; implementation hashes match
the recorded probe. No commit, push, PR or deployment occurred.

M29 known/conservative estimated usage is US$0.06810675, no new unknown holds or
cap refusals. Shared conservative spend is US$7.18707750 of US$9; remaining
US$1.81292250. All historical unknown holds, US$0.12293325, remain charged.
Original M26 envelope usage is US$0.51671175 / US$0.60; M27 is US$0.55020675 /
US$1.40. Grants were counted once and envelope subtotals were not double-charged.
The unused follow-up ceilings add no budget and incur no charge.

Further prompt-only edits are stopped for this repeated cause. The unresolved
work is independent evidence for free-form explanatory claims, including avoiding
false rejection of valid claims and generalization beyond a witness. A supported
model-produced status is insufficient proof. Publication semantics, admissible
proof obligations and the resulting recall/cost tradeoff need architecture
review before the next implementation. Human adjudication, broader fresh
production benchmarks, alternate-provider independence and production SLAs are
also not established by these exposed small regressions.

Evidence: tasks/evidence/m29-closing-review.json;
m29-whole-claim-review.json; m29-critic-false-rejection.json;
m29-public-settlement.json; m29-policy-withdrawal.json;
m29-backend-01/summary.json; m29-restored-focused.xml;
m29-experimental-source-archive.json; m29-final-source-archive.json;
reliability-budget-audit.json. All original M28/M29 failures remain preserved.
