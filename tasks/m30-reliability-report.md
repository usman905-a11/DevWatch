# M30 independent claim evidence: PARTIAL

2026-10-22. Engineering is implemented and verified for bounded arithmetic and
disagreement preservation. The natural live reliability gate is not met.

## Changes

- A bounded integer predicate checker independently evaluates explicitly declared
  assertions over finite domains. Exact canonical text binds each assertion to a
  candidate field. Unsupported syntax, undefined arithmetic or excess work remain
  unknown. Source/generated code is never executed.
- Real in-domain counterexamples can reject a claim even when both model reviews
  approve it. A proposed point that actually supports the predicate cannot refute
  it. Passing arithmetic cannot approve unrelated prose or establish source relevance.
- Conflicting approvals/rejections remain uncertain, with both model observations
  retained. Rejections receive the bounded challenge pass; uncertain-only batches
  avoid an unnecessary extra call. Historical decisions cannot bypass the new policy.
- Acceptance recomputes mathematical receipts and retains scope in JSON, Markdown
  and PDF reports. Browser contracts accept old reports and validate new evidence.
  Reports explicitly distinguish computed predicates from model-reviewed prose.

## Verification

The complete 792-test collection ran. Eight failures were retained: seven tests
expected the old guidance list and one client test exceeded its five-second worker
coordination window under suite load. The three affected test files were updated
and rerun completely: 31 passed. The reconciled result accounts for exactly all
792 identities, with no omissions, duplicates, errors or skips. Production sources
are identical between the full run and recheck. This is a full run plus focused
rechecks, not a claim that the original full command exited successfully.

Evidence: `tasks/evidence/m30-backend-reconciled.json`,
`tasks/evidence/m30-backend-02/summary.json`,
`tasks/evidence/m30-backend-recheck.xml`. The earlier interrupted run and all focused
attempts are retained. Frontend: 57 tests passed and production build passed.

## Live results and finances

All seven preregistered exposed reviews were attempted, without response injection.
Previously approved source/contracts were checked against the manifest before
dispatch. Static policies and fixture-derived outputs only were sent to Gemini.
TLS remained enabled, ambient tracing disabled, paid concurrency one.

Public regressions: 3/4 strict passes; US$0.07404150 of the US$0.20 phase cap.
Both full reviews passed, including a natural, correctly scoped arithmetic
assertion in the defective bitcount review. The provided-evidence raw specialist
failed schema admission twice because its structured assertions lacked the exact
canonical statement in the referenced field. Its unadmitted explanation also
incorrectly described the sequence as alternating/growing: 2 -> 3 -> 1 -> 1.
The initial raw autonomous description overgeneralizes `n - 1 == 0` from n=1
to positive n; n=3 gives 2. These are retained semantic failures.

Deferred synthetic regressions: 2/3 strict passes; US$0.05485425 of US$0.075.
Both provided-evidence specialist reviews passed. The full iterator review found
the defect but retained `task-logic-correctness: evidence_incomplete`; the task
acknowledged source without completing its required contract evidence. Another
specialist and verifier supplied usable evidence, but that does not erase the
incomplete task. The three reviews skipped in M29 have now actually been run.

The full iterator finding retains prose outside independent arithmetic coverage.
Its zero-sum wording needs qualification: a wrong nonzero-sum witness does not
prove every iterator produces a numerically wrong sum. Its fix offers alternatives
and uses an inline loop sketch, so this report does not certify complete executable
remediation from the positive model judgments alone.

Combined strict result: 5/7. No unknown remote effects or cap refusals occurred.
M30 cost US$0.12889575; shared conservative spend US$7.31597325 of US$9;
remaining US$1.68402675. Historical unknown holds US$0.12293325 remain charged.
Original envelopes: public US$0.62424825 of US$1.40; synthetic US$0.571566 of
US$0.60. The remaining synthetic allowance is only US$0.028434.

Receipts: `m30-public-03-settlement.json`, `m30-semantic-03-settlement.json` in
`tasks/evidence`. No failed trial was replayed or relabeled. Rates were checked
against the [official Gemini pricing page](https://ai.google.dev/gemini-api/docs/pricing)
on 2026-10-22: US$0.75 input and US$3.75 output per million tokens.

## Remaining issues, ordered for the next slice

1. Repair diagnostics should name arithmetic text-binding failures precisely;
   maintain the binding gate and the existing one-repair limit.
2. Recover missing required contract acknowledgment with actionable bounded
   feedback, preserving the incomplete-task record and source permissions.
3. Unencoded explanations and remediation alternatives still depend on model
   judgment. Finite mathematical evidence does not establish whole-claim truth,
   universal program behavior, caller contracts or language overflow semantics.

Keep M27-M29 historically partial. Do not claim full system reliability or treat
the five strict primary passes as seven whole-claim semantic successes. No commit,
push, deployment or further trace export was performed by this work.
