# M21 Token, Cost, and Latency Optimization

Date: 2026-10-21. Baseline: clean commit `a24ce50` (M20). Status: in progress.

Objective: reduce cost per comparable successfully completed review while
preserving source scope, causal review, inspection, classification and coverage.
Existing seven roles, authority, deadlines and budget ceilings remain unchanged.
No M22 work, commits, publishing or additional spending grant is authorized.

## Baseline and acceptance

The initial final-agent request is 11,570 UTF-8 bytes without evidence pages:
3,783 bytes result schema and 3,246 tool catalogue. M20 also makes a second model
call for a summary already replaced by runtime counts at final acceptance. Its
remaining useful limitations can be retained from verifier conflicts, unresolved
disagreements and authoritative coverage rather than another generation.

Use the eight completed supplied-candidate reviews in immutable
`evidence/m20-live-run-04.json` as the declared live baseline, including both SQL
singletons. Repeat exactly those inputs/strategies and expected gates with the
same physical model, reasoning level, output ceilings and timeout. Do not replace
failures or compare incomplete reviews as efficiency wins. Record all attempts,
known usage, unknown reservations, cost per completed comparable review and
wall-clock distribution. This is verifier-stage cost evidence, not full-system
specialist recall or production-level latency evidence.

All model calls, provider-reported prompt/output/thinking/cache tokens, admission
charges, durations, tool counts and delivered source sizes must be inspectable.
Unknown usage retains its full reservation. Existing final-agent reserve,
cumulative per-role/job budgets and concurrency ceilings remain effective.

## Ordered slices

1. **Remove redundant summary generation** (subgraphs and focused tests).
   After complete validated verification, deterministically assemble and validate
   the report, retaining conflicts, unresolved uncertainty, follow-ups, coverage
   and rejected findings. Revalidate restored verification and inspection before
   finishing. Test that no second model call occurs, including after restoration;
   invalid/stale evidence must still fail. Preserve the combined seventh role.
2. **Account for actual work** (budget ledger, provider adapter, subgraphs and
   focused tests). Persist metadata-only model-call records for admitted,
   completed and unknown calls, including provider splits and source delivery
   bytes. Preserve backward reading of old state and wire fixtures. Do not double
   charge thinking/cache subsets. Verify global/per-role reserves and unknown
   usage through real graph integration and existing budget tests.
3. **Reduce schema/prefix overhead** (prompt preparation and focused tests).
   Measure generated annotation overhead before removing redundant schema titles;
   retain every field and validation constraint, including properties named title.
   Put stable policy/schema data before task-specific state to permit provider
   prefix caching. Preserve source bytes/digests and all M20 checks. Keep only
   changes with measured savings. Existing content-addressed owner-scoped parser
   cache stays intact; do not cache authority or bypass integrity rereads.
4. **Measure and close** (evaluation artifacts, report and task records).
   Compare completed offline jobs, source/cache retrieval, and allowed concurrency
   configurations under identical work. Inspect provider caching documentation and
   actual reported cache tokens; do not assume a discount. Keep the tested model
   configuration unless a comparable quality-preserving alternative is demonstrated.
   Run targeted then full backend tests; updated wire tests/build if needed;
   review the diff, freeze exact sources and perform bounded live comparisons.

Each implementation slice starts with failing behavior tests. Checkpoint after
slices 1-2 and after slice 3 before live calls. Public schema changes must retain
updated-browser compatibility with historical reports/jobs. No gold tuning,
required evidence removal, relaxed timeouts, provider response injection or
increased call limits may produce an apparent improvement.

## Budget and data boundary

Shared prior conservative total: US$3.47036400 of US$4; remaining US$0.52963600.
Allocate at most US$0.40 to M21 within that remainder, initially at most US$0.30
for the eight-repeat campaign. Keep all earlier unknown holds (US$0.09968775).
Reuse only already approved synthetic source/contracts, static policies and
fixture-derived candidates. No working-repository source, secrets or labels enter
requests. Journal reservations before effects and stop a campaign on unknown
usage/cap refusal. Evaluate implicit caching without creating paid cache resources.

Risks: provider variability may outweigh small prompt savings; use removed call
counts and deterministic input measurements alongside billed estimates. Semantic
reviews remain model judgments. Paired SQL completion is not established by this
singleton comparison. Broader model-family comparison may remain unverified under
the current shared cap; do not claim cross-model optimization without evidence.
