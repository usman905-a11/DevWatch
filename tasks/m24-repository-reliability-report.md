# M24 — Repository completion and local refusal diagnostics

Date: 2026-10-21. Status: **COMPLETE for M24 engineering and scoped natural regressions**. Scope: remaining issues 1, 2 and 6.
Extends [the remediation plan](reliability-remediation-plan.md); M23's report,
labels, raw journals and findings remain preserved, not replaced by successful reruns.

## A. Existing behavior and diagnosis

M23's 12-file synthetic pair failed to finish specialist investigations. Each
specialist made repeated single-file reads; at around 25k spent tokens, growing
prompt bytes plus an unconditional 8192-token output reservation could no longer
fit the 50k role ceiling. Only Planner previously fitted output to remaining
allowance. Some files were omitted from all delegated scopes.

A generic RuntimeError from the evaluation cost guard proved no dispatch to the
external meter, but the runtime classified it as unknown and charged the token
reservation anyway. A deterministic reproduction charged 15,906 runtime tokens
for a locally refused call. Untyped errors and timeouts really can be ambiguous
and must remain conservatively charged.

## B. Changes

`read_source` gains optional `additional_files`, at most three extra assigned
paths using the same line range. Every path is normalized and permission-checked
before the handler can run. Each file retains its own immutable, paged evidence
artifact and runtime receipt. A batch counts as one bounded tool call, but does
not mark any page inspected. The model must acknowledge every delivered page;
omitted/partial pages still block completion. Old single-file calls remain valid.

All roles fit output reservations to remaining role/job headroom while preserving
atomic admission and the final-role reserve. Runtime-only cursor/size maps stay
in checkpoints; prompts already carry the actual page offsets and next offsets.
The existing schema compactor removes display labels from tool argument schemas
while preserving validators/fields. No limit, retry allowance or acceptance gate
is raised or relaxed.

The trusted adapter exception `ProviderBudgetRefusedError` means a local budget
guard proved the transport was not invoked. This path records zero charged tokens,
`not_dispatched`, and budget exhaustion. Nested meters release only this proven
undispatched reservation. Generic exception text cannot activate the exemption;
timeouts and other ambiguous exceptions remain charged as unknown. The exception
is an internal provider contract, never a model-supplied action field.

Prompt v4.7 asks Planner to cover all supplied files with feasible delegation and
asks specialists to conclude once source is ready and no concrete question
remains. Natural model responses are never rewritten or auto-acknowledged.

## C. Verification

Red observations: known refusal charged runtime tokens; nested refusal became an
unknown meter charge; specialists/final role retained oversized output ceilings.
Those focused tests now pass. Batch scope denial, normalized duplicate/traversal
and oversize rejection, and partial-page completion controls pass. One authored
test double initially omitted required `latency_ms`; it was corrected, rather
than treating that fixture error as evidence of a product failure.

The first broad run found an oversized mandatory prompt was labelled
`budget_exhausted` rather than `prompt_context_limit`. The failure was reproduced
by `test_irreducible_prompt_is_rejected_before_provider_dispatch`. Context limits
now take precedence when the mandatory prompt itself exceeds the context window.
The superseded broad run was explicitly stopped, native exit 15, and its log is
retained. A subsequent broad run retained two further failures: Planner policy exceeded
its existing 2000-byte bar and local-refusal evaluation attribution was wrong.
Both were reproduced by their named tests and corrected without weakening those
tests. The v4.7 focused set passes 54 tests. The final frozen v4.7 full suite passes **722 tests**, native exit 0; its existing LangSmith wrapper deprecation warning remains assigned to M27.

Fresh frontend 55 tests and build pass. Generated-wire parity, compilation and
whitespace checks pass. Public report/event schemas are unchanged. All 190 final frozen sources and preserved M23 hashes match. The configured-secret scan covers 69 changed/evidence files and finds no matches. Every final claim and all costs were reviewed.

## D. Natural live verification

Only previously approved synthetic payloads are sent to Gemini; no working source,
gold labels, secrets or raw private reasoning are uploaded. Serial model admission,
TLS verification, disabled ambient tracing and durable reservations remain.

Campaign one retains all six trials: five strict passes. Both larger defects were
detected with complete source coverage and one repaired repository completed.
The second repaired control had full file inspection but a specialist emitted a
truncated response after redundant evidence reads left only 270 output tokens.
It remains a failed completion, not a successful clean result. This motivated
the cursor-map compaction and ready-state guidance; no threshold or gold changed.

Campaign two passed all six trials on v4.6. The two subsequent engineering
corrections required a final v4.7 campaign, which also passed all six trials.
Across all three campaigns, 17 of 18 strict primary/completion screens passed;
the earlier truncated control remains in the denominator. Every one of the
final campaign's larger-pair repetitions inspected all captured files and their
complete actual source ranges. All three final positive claims were reviewed
against the source and contract.
These now-exposed synthetic cases are regressions, not independent holdout data.
File coverage is also checked against actual source ranges for these short files;
artifact acknowledgment alone is not a general whole-file coverage proof.

## E. Authority and cost

The user added US$4: shared cap US$9, starting conservative spend US$4.91760450.
All US$0.09968775 earlier unknown holds remain charged. M24 allocation US$0.80.
Campaigns one, two and three settled US$0.21097575, US$0.17667525 and
US$0.17711625, respectively: M24 total **US$0.56476725**, below its allocation.
All journals are quiescent and native exits are zero. New unknown API calls and
local campaign refusals are zero. Conservative cumulative spend is
**US$5.48237175**, leaving **US$3.51762825** within the shared cap. Model/prices remain the same verified M23
Gemini Flash settings; these are conservative estimates, not invoices.

## F. Trust and architecture review

Untrusted model paths enter strict SourceArguments validation and the existing
task/owner snapshot permission boundary. Batching creates no new identity,
filesystem authority, external integration or host execution path. All artifacts
remain snapshot-bound; candidate/verifier inspection and final acceptance remain
unchanged. Budget exceptions come only from trusted local provider adapters.
No exception-message matching or secret-bearing diagnostics is introduced.

The first source version is retained in a local archive. Two changed files were
reconstructed immediately after correction and byte-checked against all 184
preregistered hashes; the archive explicitly records this provenance. Final
frozen sources and all three raw campaign journals remain separate. Source
archives retain 184, 185 and 190 exact hash-matched files for each runtime.

## G. Remaining limits

This proves a bounded synthetic repository regression, not arbitrary repository
scalability. Source/tool/iteration ceilings still apply. Complete primary matches
do not establish every downstream impact: the first campaign's deadline findings
infer early timer execution from the returned deadline; the fixture has no running
scheduler. That semantic qualification belongs to M25 and is retained here.
The final campaign likewise infers deadline expiration/scheduling from returned
timestamps without demonstrating a running scheduler. Its unit mismatch and
returned deadline error are valid primary detections; those external effects
remain unproven. Campaign two's approximately 1000x scheduling claim proves only
a delay-component conversion ratio, not an absolute timestamp ratio. M23's SQL
overclaim, unsafe nested-copy fix, schema failure and ambiguous advisory control
are not solved or rescored by M24.

## H. Status

**COMPLETE for this bounded M24 scope.** Frozen v4.7 backend 722 tests,
frontend 55 tests/build, wire/compilation/diff checks and the final six-trial
live gate pass. Prior failures and semantic qualifications remain visible.
M25 is active; M26/M27 payloads are approved under their existing caps.
No commit, push, PR or deployment.
