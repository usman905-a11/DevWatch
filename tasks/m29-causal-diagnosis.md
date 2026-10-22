# Why additional prompt guidance did not resolve the semantic gate

M28 and M29 retain a concrete counterexample to whole-claim reliability. The
Python bitcount defect is real: the XOR update reaches n=1, then stays at n=1.
The recommended AND update fixes that defect on the declared nonnegative domain.
But the generated description also says XOR flips the lowest set bit. For n=3,
3 XOR 2 = 1 leaves bit zero set. A correct input trace coexists with a false
abstract explanation in the same field.

The model returned supported assessments for every field. Its counterexample
pass agreed. Runtime binding, source inspection, candidate digest, confidence,
whole-field completeness and conservative disagreement reconciliation all passed.
There was no disagreement to reconcile. The full review published the incorrect
auxiliary clause. This repeats after v5.1 and v5.2 guidance explicitly requires
derivation and rejection of unsupported clauses. Source and prompt freezes, raw
requests/results and actual arithmetic witnesses distinguish this from a stale
policy, missing contract, harness injection or scoring exclusion.

The mechanism is correlated semantic judgment: the same model accepts a familiar
but incorrect explanation while correctly tracing the witness. A supported string
in a structurally valid assessment is not an independent mathematical proof.
Existing structural validation correctly validates provenance and assessment
shape; adding another check for the same labels cannot resolve this failure.

The failure also runs in the opposite direction. The same critic rejected a
different candidate whose claim was correct: a positive odd input XOR its
predecessor equals 1, and then remains 1 on later iterations. It objected that
3 XOR 2 equals 1 rather than 3, which does not contradict the actual claim.
Above bit zero, a positive odd integer and its predecessor have identical bits;
only bit zero differs. The XOR is exactly 1. Another candidate preserved recall
in this run, masking the rejection in primary scores. Its extra false clause
then survived. The supplemental m29-critic-false-rejection.json retains the exact
candidate, critic assessment and owned arithmetic proof. Stronger skepticism can
therefore reject a supported claim as well as confirm an unsupported one.

Stop further prompt-only patches for this suspected cause. Keep the milestone
partial, retain every trial and finish offline verification. Do not silently
rewrite published descriptions, blacklist these words, relabel a correct core as
whole-claim correctness, add unbounded retries, or spend the remaining budget on
repeated generations until one happens to pass.

A further implementation needs an architectural decision: narrow the claims that
can be independently checked and bind their proof obligations to trusted executable
evidence, or introduce independent adjudication for unsupported free-form clauses.
Either changes the evidence contract and can affect recall, latency, cost and the
meaning of publication. A different model can provide another observation but
does not establish independence or a universal truth guarantee by itself. That
decision should be reviewed explicitly before another policy patch is treated as
a fix. No new tool, provider, production execution or publication rule was added
in M29.
