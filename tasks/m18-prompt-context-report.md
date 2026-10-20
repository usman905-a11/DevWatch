# M18 - Prompt and Context Engineering

Date: 2026-10-20. Status: **Engineering and scoped verification complete; broader semantic acceptance OPEN**.

Follow-up: [the v2.4 claim-quality fix](m18-claim-quality-followup.md) resolves the
two observed confirmed overclaims in fresh completed reviews. This initial v2.3
report and its raw receipts remain historical; the follow-up retains a partial,
explicitly unverified SQL candidate and documents the remaining limits.

## A. Existing implementation

Seven typed roles use custom StateGraph JSON loops. M16 enforces acknowledged
source-backed findings and investigation progress; M17 filters visible tools
while preserving execution authority. Repeated common instructions and both
final-role phases occupied system policies. Evidence was selected newest-first.
Provider finish/refusal/token/reasoning metadata already persisted privately.
Earlier uncommitted M16/M17 work remains preserved.

## B. Problems found

Stable policy and phase instructions were combined, with no explicit prompt
revision connecting requests to provider observations. Inspected or ancillary
pages could crowd out uninspected source, candidate refs and continuation pages.
Source crowding could also hide a newly processed AST observation before its
first delivery. M17 had already demonstrated that correct primary findings can
contain unsupported secondary input-domain or SQL-impact claims.

## C. Changes implemented

[prompts.py](../devwatch/review/prompts.py) owns one compact common policy, seven
distinct role policies and four curated guidance units. Stable system policy is
separate from dynamic task/evidence data. Specialist completion, verification,
synthesis and partial-artifact paging guidance load only when applicable. These
are application constants; repository content cannot load executable skills.
Existing schemas, M17 catalogue filtering and canonical authorization remain.

Final versions: `review-prompts-v2.3` and `scoped-evidence-priority-v2`. Each
request records version, loaded guidance and a fingerprint of policy/guidance
and context version. Existing bounded private provider history preserves these
alongside finish/refusal/usage/reasoning metadata across restart. The fingerprint
excludes task/source data; it is not a full-prompt hash or exhaustive record of
unknown requests. Public reports/events and wire schemas do not gain these fields.

Context validates immutable scoped pages, then prioritizes the latest processed
undelivered page, incomplete continuation offsets, active candidate/task refs,
and uninspected source/artifacts before inspected or ancillary material. Stable
ties preserve recency. Selection creates no observations or inspection receipts,
changes no offsets or scope and retains the 6,000-byte evidence allowance.

Live regressions required restoring useful explicit constraints: Planner's
selected-agent/task consistency and the complete required candidate field list.
Schema information alone proved insufficient. Common policy also specifies
output files, preserving Planner source-file selection, and supplied contracts.
No new framework, dependency, public contract or authority boundary was added.
[Google's guidance](https://ai.google.dev/gemini-api/docs/prompting-strategies)
informed concise instructions, explicit structure and essential system constraints.

## D. Tests executed

Failing-first receipts retain eight initial prompt failures, three context
failures and the later pending-tool-delivery failure. Fourteen new cases exercise
all seven roles, conditional phase/paging selection, actual SDK-to-report
assembly, private metadata/restart, source/candidate/continuation priority,
pending AST delivery, foreign-reference denial and truthful inspection receipts.

The final focused gate passes 32 cases in 7.02s. A preceding integration gate
passes 73 in 26s; the final common-policy qualifiers were checked by the focused
gate afterward. Earlier 105-case integration evidence is retained, not presented
as the final full run. Wire-schema freshness and compilation passed.

Fresh full backend: **571 passed**, zero failures/errors/skips, 705.75s.
Serial deterministic matrix: **24/24 completed**, no failed coverage. The matrix
uses a programmed provider and does not measure model reasoning accuracy. Three
earlier full runs against obsolete revisions were interrupted for corrections;
one v2.3 run ended at 88% without completion evidence. None counts as a pass.
Frontend code is unchanged; no M18 frontend test/build claim is made.

## E. Live evaluation

Standing authorization permits the shared US$4 cap and the five exact synthetic
fixtures/contracts in m13-live-inputs.json, agent/tool policies and fixture-derived
results. Prior charges: US$1.57014975; M18 allocation: at most US$0.60. No working
repository source or secrets were sent. Captured M17 system policies, assembler
and context order form the control; execution/schema/tool enforcement is held
constant. No model action is injected. Reservations persist before serial API
effects; TLS verification is enabled and ambient tracing disabled. Unknown
consumption stops its batch and remains charged.

| Batch | Revision/scope | Result | Conservative US$ |
|---|---|---|---:|
| 01 | M17 controls + v2, 10 reviews | Controls 4 TP/0 FP/0 FN; candidate Planner invalid schema and HTTP 503 partial review retained | 0.25683675 |
| 02 | v2.1, five fresh candidates | 4 TP/0 FP/0 FN; complete coverage | 0.10447725 |
| 03 | v2.2, five fresh candidates | 4 TP/0 FP/0 FN; query logic candidate missing impact quarantined, valid sibling retained; 4/5 without failed coverage | 0.09839025 |
| 04 | Final v2.3, five fresh candidates | 4 TP/0 FP/0 FN; all five complete source/goal coverage, no failed coverage | 0.09518550 |
| 05 | Final performance-role clean-fixture control | Zero findings; complete source/goal coverage | 0.00463350 |

Later revisions use the retained M17 control batch, not fresh interleaved controls.
All 26 attempts remain: raw 18 TP/0 FP/2 FN, 23 with complete source/goal coverage
and no failed coverage. There are 177 known generation responses, all stop, and
one HTTP 503 with unknown consumption. All 70 actual tool effects are successful
read_source operations; none was unadvertised. Later batches preserve the unknown
reservation; no uncertain tool effect is replayed. No paid batch has a local cap
refusal. One offline oversized-allocation attempt was refused before effects.

All seven current role policies are structurally exercised offline. Live role
coverage spans revisions; architecture and bug/reliability ran in earlier
revisions, while the performance control uses final v2.3. Final live requests
cover five role identities. This does not prove every final role's live reasoning
independently.

The original scripted rehearsal completed ten reviews; it validates harness
assembly, not model reasoning. Raw journals, revision snapshots, diagnosis and
manual clause review remain separate in tasks/evidence/m18-*.

## F. Resource usage

| Stable system text, UTF8 bytes | M17 | Final M18 |
|---|---:|---:|
| Planner | 2,143 | 1,775 |
| Bug/reliability | 2,823 | 1,464 |
| Logic/correctness | 2,814 | 1,455 |
| Quality/testability | 2,826 | 1,472 |
| Architecture/security | 2,825 | 1,477 |
| Performance/scalability | 2,948 | 1,497 |
| Synthesizer/verifier | 2,590 | 1,492 |

Guidance and revision metadata add dynamic text. Sixteen fixed-state role/phase
profiles reduce complete system-plus-user bytes by 1.48-13.89%; those byte counts
are neither tokenizer measurements nor quality evidence.

| Actual five-fixture comparison | M17 controls | Final v2.3 |
|---|---:|---:|
| Summed system + user bytes | 459,836 | 348,709 |
| Actual input tokens | 117,757 | 90,834 |
| Output including unallocated tokens | 11,110 | 7,216 |
| Known generation responses | 40 | 33 |
| Actual source tool calls | 17 | 12 |
| Known generation cost, US$ | 0.12998025 | 0.09518550 |

Observed complete bytes fall 24.17%, input tokens 22.86% and known generation
cost 26.77%. Different delegation/step counts contribute; this small sample does
not establish causal or general savings. Verified [Gemini rates](https://ai.google.dev/gemini-api/docs/pricing)
are US$0.75/1M input and US$3.75/1M output including thinking through 2026-12-31.
Unallocated tokens are priced at the higher output rate.

All M18 known usage: US$0.51837900. The HTTP 503's entire US$0.04114425 unknown
reservation remains charged. Total M18: **US$0.55952325**; cumulative conservative
charges: **US$2.12967300 of US$4**; remaining shared budget: **US$1.87032700**.
No further paid calls are needed for this implementation.

## G. Remaining limitations

Manual Codex source/contract review supports all 18 accepted primary findings,
but flags secondary clauses in nine findings across revisions. Final v2.3 has
two such findings out of four: KeyError/TypeError extensions and tuple/non-list
AttributeError claims assume undocumented input domains. The retained M17
control batch has no flagged secondary clauses. **Broader semantic non-regression
is not established.** Correct primary scores do not validate every clause.
This review is not independent human adjudication, and raw findings/gold were
not rewritten. Strict schema quarantine remains visible as failed coverage.

No detector or scoring change is part of M18. The five fixtures cannot establish
general accuracy. M19 functional intelligence and M20 semantic verification remain
unimplemented. Completion of prompt/context engineering does not close these
semantic quality limitations or establish exhaustive source inspection.

## H. Review and delivery

The M18 diff changes four runtime files and adds three test files, preserving
the other 148 baseline files. Eight authorization/evidence methods are AST-equal
to the captured working M17 baseline. The current patch and five-axis source
review are in m18-production.patch and m18-review.json. Required structural
findings were resolved; semantic limits remain explicit above.

Full/matrix, all 155 frozen source/fixture hashes, wire freshness, compilation and
credential-boundary receipts pass. See m18-verification-summary.json and
m18-live-boundaries.json. Broader semantic non-regression remains unproven.
No commit, push, deployment or later milestone was performed.
