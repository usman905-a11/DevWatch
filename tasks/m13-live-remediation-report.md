# M13 live-quality remediation

Started: 2026-10-18. Follow-up verification: 2026-10-19.
Status: **COMPLETE for M13 engineering and approved live-fixture gates**.

This addendum resolves the downstream limitations recorded in
[m13-reliability-report.md](m13-reliability-report.md). The user requested these
fixes before any further milestone. Existing M14 orchestration remains intact.

## A. Existing implementation

The seven roles, immutable snapshots, scoped tools, structural evidence gate,
bounded action loops, cumulative budgets, verification checkpoints and final
acceptance already existed. Planner dispatch was working in the original M13
live run. Verification already produced duplicate groups, and runtime assembly
already owned report claims; neither mechanism needed replacement.

## B. Problems found

| Confirmed problem | Evidence and cause |
|---|---|
| Repeated source-tool failures on short files | The diagnostic probe requested lines 1-80 on a two-line source. The tool rejected a bounded end beyond EOF, forcing the model to guess a valid end. |
| Fenced JSON, incomplete specialist envelopes and phase confusion | Visible probe actions included fenced objects and candidate results missing task/role ownership. Only Planner requested JSON mode. Specialist completion instructions were incomplete; final instructions requested report_draft despite the synthesis prose schema. |
| Unused action fields repeatedly sent as null | Baseline full assertion review used its one repair on payload:null, then failed on arguments:null. JSON mode ensures JSON syntax, not the action's field types. |
| Verified duplicates published twice | Empty and mutation reviews each published two claims for one issue even though verification grouped them. Assembly ignored groups and acceptance required every non-rejected decision to appear as a separate finding. |
| Partial recovery compared decision order as authority | The new full-graph regression caught a list-order mismatch after deterministic partial assembly. Its fallback also rebuilt coverage without the existing failed marker. Decisions are now matched by identity and value, and repaired reports retain failure coverage. |
| Facet scores missed unsupported secondary claims and malformed-candidate loss | Prose inspection found broader input-domain assertions attached to an otherwise valid mutation claim. An additional run found all four core issues but quarantined one specialist candidate missing impact. Prompts now explicitly enumerate candidate fields, separate independent failure mechanisms, require contract-supported input domains and prohibit unsupported confirmation/synthesis assertions. The quarantined run remains partial evidence. |
| Fixed response reservation no longer fit the smaller context window | The first completed full regression passed 484 tests but failed the existing 20,000-token oversized-evidence case. It reproduced in isolation: mandatory specialist prompts plus a fixed 8,192-token response reservation exceeded the context window. Five new SDK/full-graph cases reproduced this for all specialists. |

The new observations identify these current failures. They do not recover the
unrecorded exact finish reasons behind every historical M11/M13 incomplete call.
No claim about missing native thought signatures or hidden reasoning is made.

## C. Changes implemented

- `review/repository.py` and `tool_catalogue.py`: clamp a bounded source read to
  actual EOF and return the actual range. Invalid starts, reversed/type-invalid
  ranges and requests exceeding 200 lines still fail before reading.
- `review/contracts.py`: explicit JSON AgentAction, object-valued arguments and
  payload, complete specialist ownership/result fields, and phase-specific final
  results. Require source/contract support for every factual clause; unverified
  domains belong in limitations. List required candidate fields and prevent
  unrelated secondary failures being bundled into a confirmed claim. No fixture
  answers, fixture-specific filters or gold annotations enter production prompts.
- `review/subgraphs.py`: JSON-object mode and low Gemini reasoning effort for all
  roles; advertise only role/phase actions. Feed verified duplicate groups into
  runtime assembly and acceptance. Schema validation remains strict.
  After optional context/evidence pruning is exhausted, fit a non-Planner response
  to remaining context headroom if at least 512 tokens remain. Preserve the
  existing output ceiling, mandatory fields, evidence inspection and all cumulative
  limits. Requests that already fit take the unchanged successful path.
- `review/finalization.py`: optional internal duplicate-group inputs. Merge
  overlapping verified groups; choose confirmation before uncertainty/advisory,
  then highest confidence, then stable finding ID. Retain every original
  candidate and decision. Validate evidence/inspection for all decisions,
  including suppressed duplicates. Unknown, singleton and repeated-ID groups
  fail. Without verified groups, dropping a finding still fails acceptance.
- `review/workflow.py`: use duplicate metadata from verification checkpoints
  bound to the current candidate snapshot and round. Preserve groups through
  normal, partial and deadline paths. Compare decision records without depending
  on list order; preserve failed coverage during deterministic acceptance repair.

No resource ceiling, retry allowance, scoring rule, gold fixture, provider/model,
public report wire format, framework or production role changed. JSON mode and
reasoning controls follow Google's [OpenAI compatibility documentation](https://ai.google.dev/gemini-api/docs/openai).
The local Google documentation discovery found no applicable Gemini Developer API
product package; public official documentation was used directly.

## D. Tests executed

- Initial reproduction: **6 failed, 4 passed** before source/protocol fixes
  (`evidence/m13r-red.txt`); first focused green: **45 passed**, 21.57s.
- Duplicate regressions: **8 failed** before the fix. Intermediate validation:
  **1 failed, 32 passed**, exposing the partial-coverage issue rather than hiding it.
- Corrected focused suite: **43 passed**, 56.26s. Final expanded duplicate suite:
  **9 passed**, 12.75s, including invalid synthesis and inconsistent-draft repair.
- First completed full backend regression: **1 failed, 484 passed**, 789.46s
  (`evidence/m13r-backend-final.txt` and XML). The 20,000-token oversized-evidence
  failure reproduced alone; the five added 20,000-token specialist SDK scenarios
  also failed before the context-headroom fix (`evidence/m13r-context-red.txt`).
  The corrected full regression is recorded below. Python compilation, generated
  wire freshness and diff whitespace checks passed.
- Context fix and related runtime regression: **66 passed**, 243.03s
  (`evidence/m13r-context-green.txt`), including the original oversized-evidence
  case, SDK graphs for every specialist at both context sizes, mandatory-context
  refusal, paging, deadlines, cancellation and recovery. Full regression restarted
  on these corrected source hashes.
- Corrected full backend: **490 passed**, zero failures/errors/skips, **785.64s**
  (`evidence/m13r-backend-verified.txt`, XML and `m13r-verification-summary.json`).
  Source/test hashes remained unchanged through the run. One pre-existing
  LangSmith SDK wrapper deprecation warning remains. The original smaller-context
  paging failure and all 24 new remediation cases passed without changing the
  existing tests' assertions or resource ceilings.
- Deterministic matrix: **24/24** specialist/full case-mode runs completed with
  no failed coverage (`evidence/m13r-fixture-results.json`, `m13r-fixture-run.txt`).
  Scripted full scores remain TP=1, FP=0, FN=5, matching the earlier programmed
  detector; this verifies runtime/scoring continuity, not actual model accuracy.
- An initial full backend run was deliberately interrupted during execution when
  prose review justified the final prompt revision; it is not counted as passing
  (`evidence/m13r-backend-interrupted.txt`). The revised-prompt focused run passed
  **49 tests**, 76.12s; the final guidance passed **49 tests**, 62.66s
  (`evidence/m13r-final-focused.txt`) before restarting full regression.

The 24 new tests exercise actual scoped tools, installed SDK transport, every
specialist role, real graphs/stores, strict acceptance, duplicate selection and
recovery. The external API is replaced only in offline provider tests.

Self-review covered correctness, readability, architecture, security and
performance using the current-request-only `evidence/m13r-fixes.patch`. Selection
is shared by assembly and acceptance; immutable checkpoint metadata supplies
suppression authority. Scoped reads, all-decision evidence checks, bounded loops
and existing retry/admission policies remain enforced. No dependencies, orphaned
helpers or new external production data flows were introduced. This was an
implementing-agent review, not an independent reviewer.

## E. Live evaluation

Final five full reviews used `gemini-3.8-flash` and the existing evaluation
framework on the exact five user-approved synthetic payloads. There were **40
model calls**, all finish identifiers `stop`, **one bounded Planner schema repair**, zero
unknown calls and no failed task coverage. Every case reached verification and
synthesis. Evidence: `evidence/m13r-live-final-supported-matrix.json`.

| Fixture | TP | FP | FN | Duplicate findings | Failed coverage |
|---|---:|---:|---:|---:|---|
| Empty-input defect | 1 | 0 | 0 | 0 | None |
| Empty-input clean control | 0 | 0 | 0 | 0 | None |
| Input mutation | 1 | 0 | 0 | 0 | None |
| Missing assertion | 1 | 0 | 0 | 0 | None |
| SQL query construction | 1 | 0 | 0 | 0 | None |

Aggregate fixture-screen precision/recall are 1.0 (4 TP, 0 FP, 0 FN). This is the
existing facet/location/evidence screen, not an independent semantic judgment.
The implementing agent inspected the four emitted claims and synthesis against the visible
sources/contracts: empty indexing, in-place sorting, missing assertion and direct
SQL concatenation. The final mutation claim/synthesis omit the earlier unrelated
type failures, and the SQL claim omits unestablished data-modification effects.
No independent human review is claimed. Source evidence and
file/line screen correctness are 1.0 for each reported finding.

The earlier complete matrix (`evidence/m13r-live-final-matrix.json`) passed the
same screen but prose inspection found overbroad secondary assertions. The next
policy probe (`evidence/m13r-live-supported-claims.json`) found all four expected
issues but had one task with invalid_evidence because its malformed candidate
omitted impact; that batch is partial, despite the screen scores. The final
revision enumerates required fields and narrows unsupported/bundled claims.
These intermediate runs remain recorded and charged; they are not excluded to
claim repeated-run stability. The final live batch covers successful finalization;
offline tests exercise the injected partial/recovery paths.
The subsequent smaller-context admission fix only changes requests that would
previously have failed before dispatch. The successful live request path remains
unchanged; smaller-context execution is checked offline rather than charged for
another paid matrix.

## F. Resource usage

| Batch | Conservative charged US$ | Unknown calls |
|---|---:|---:|
| Original M13 runs, carried forward | 0.20180175 | 2 |
| Diagnostic probe | 0.04075875 | 0 |
| First fixes | 0.03812475 | 0 |
| Quality baseline | 0.10707975 | 0 |
| Initial complete full matrix | 0.14055975 | 0 |
| Supported-claims policy probe (one partial task) | 0.11244600 | 0 |
| Final supported-claims full matrix | 0.12897075 | 0 |
| **Cumulative** | **0.76974150** | **2 historical** |

The original US$1 cap has US$0.23025850 remaining. No timeout reservation was
refunded or silently replayed. Final matrix: 125,711 prompt and 9,250 completion
tokens; 16/16 successful tool calls; total case wall time 139.923s, per-case range
17.828-45.297s. Rates used for these live calls were US$0.75/M input and US$3.75/M output, verified against
[Google's Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing).

The local diagnostic harness checks fixture payload equality, carries all prior
charges, journals reservations before API effects and stops on unknown
consumption. Only approved synthetic code/contracts, policies and fixture-derived
results went to Gemini. Tracing was disabled. Visible synthetic responses are
local diagnostic evidence; production observations remain structural and bounded.
Credentials, provider headers and hidden thoughts are not recorded.

## G. Remaining limitations

These five small, reused Python fixtures are a regression sample, not held-out
or statistically representative evidence of general review accuracy. Live
performance-specialist quality, large repositories and repeated-run stability
are unmeasured here. Semantic evidence correctness and severity accuracy remain
unscored; no human adjudication is available. All final cases have no skipped or
failed paths, but coverage is not a proof that every worker inspected every file.
The final narrow claims and synthesis were inspected by the implementing agent;
the fixture screen itself does not validate every phrase. Prompt guidance and
verifier judgment cannot provide a mechanical guarantee of semantic accuracy.

Duplicate identity remains a verifier judgment; deterministic selection cannot
prove two claims describe the same underlying issue. JSON-object mode does not
guarantee schema compliance. Invalid responses, refusals, timeouts and unknown
consumption still produce bounded, honest partial outcomes. The historical two
timeouts remain unknown-consumption charges; this work does not establish their
exact cause or guarantee they cannot recur.

## H. Milestone status

**COMPLETE for M13 engineering and the approved five-case live regression.**
The previously demonstrated live completion and duplicate-publication failures
pass the rerun. All 490 backend tests, 66 focused checks, 24 deterministic
case-mode runs and boundary checks pass. The broader accuracy and measurement
limits in section G remain; no general model-quality guarantee is claimed.
No next milestone, commit, push or deployment is included.
