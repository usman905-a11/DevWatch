# M19 Specialist Functional Intelligence

Date: 2026-10-20. Status: **Complete for M19 engineering and scoped live detection/classification verification**.

## A. Existing implementation

The five specialists already used canonical source-scoped action loops, bounded
budgets, immutable evidence and explicit inspection receipts. M18's follow-up
resolved the two observed empty-input/mutation input-domain overclaims in fresh
completed reviews; its partial unverified SQL attempt remains retained.
See [M18 follow-up](m18-claim-quality-followup.md).

The direct specialist evaluator previously exercised autonomous retrieval only.
Its narrow programmed provider recognizes literal empty-list indexing; it is an
integration fixture, never evidence of model intelligence.

## B. Problems found

Reasoning and retrieval needed distinct evaluation modes and diagnostics. Kind
classification was absent from the primary fixture score. Original live mutation
recognition also exposed a structural loss: a candidate missing `impact` was
quarantined without a repair attempt. The raw initial row labels this a reasoning
miss; its checkpoint demonstrates a candidate-schema failure instead.

The original clean deduplicator exposed unsupported memory-saving advice: a set
plus returned list was called redundant relative to `list(dict.fromkeys(items))`,
ignoring that the dictionary and output list coexist during materialization.
Two broad-policy attempts failed this same training control. The final correction
uses explicit allocation/lifetime reasoning in source-stage guidance.

## C. Changes implemented

- `scripts/evaluate_agents.py` accepts `evidence_mode='autonomous'|'provided'`.
  Provided mode creates real source artifacts before the first model request;
  canonical context delivery, paging, acknowledgment and candidate gates remain.
  Prefetch is counted separately from model-selected tool effects. Provided/full
  combinations fail before runtime effects. The CLI exposes `--evidence-mode`.
- All five role policies cover contract witnesses, mutation/aliases, pagination
  boundaries, exit-path cleanup, test effectiveness, SQL propagation and repeated
  work. Test gaps and unmeasured complexity use advisory classification. The
  `performance_cost` skill loads only for performance after actual source arrives.
  Final policy version is `review-prompts-v3.3`; context version remains v2.
- All-invalid candidate batches enter the existing bounded schema-repair path.
  Exhaustion preserves terminal quarantines and `invalid_schema`; valid siblings
  retain existing behavior. No candidate fields, limits or authority checks weaken.
- Evaluation separately records matched finding-kind accuracy, candidate
  quarantines, retrieval failures, model reasoning and local budget refusals.
  Primary facet/location/evidence matching remains unchanged.
- `scripts/specialist_corpus.py` preserves twelve original cases and adds five
  paired held-out families: exception cleanup, slice boundaries, tautological
  assertions, indirect SQL flow and prefix recomputation. Source/contracts/labels
  were frozen before live evaluation. Executable witnesses validate their labels.

These changes use existing graph, provider and evidence infrastructure. No
dependency, public application wire contract or frontend change was needed.

## D. Tests executed

Failing-first receipts cover evidence modes, CLI/kind diagnostics, budget refusal,
held-out witnesses, bounded schema repair and source-stage skill assembly. Final
focused suite: **35 passed in 12.41s**. Additional protocol/runtime/observability
boundary suite: **79 passed in 184.26s**. No instruction-string tests substitute
for consuming-model behavior.

Final full backend result: **596 passed**, zero failures/errors/skips, 788.50s
(`m19-v33-full-backend.xml`), exit 0. This includes 25 new M19 cases. Three
earlier full runs were interrupted after required changes and are not passes.
Generated contract freshness, Python compilation and `git diff --check` pass.
No new frontend verification is claimed because frontend/wire source is unchanged.

Initial and corrected offline campaigns exercise real graph delivery and source
gates. Their programmed misses remain visible and are not live reasoning scores.
All **159 frozen source/fixture files match**. Credential scan finds zero leaks
(exact configured credential values and Google API-key pattern). Closing
receipts are in `tasks/evidence/m19-verification-summary.json`.

## E. Live evaluation

The user approved all 22 exact synthetic payloads in
[m19-live-inputs.json](m19-live-inputs.json), both modes, under US$0.80 within the
unchanged shared US$4 cap. Existing Gemini key, `gemini-3.8-flash`, verified TLS,
one API call at a time and disabled trace export were used. Public inputs contain
files/contracts only; gold labels, split names and repository source were excluded.

| Campaign | Reviews | TP | FP | FN | Kind correct/matched |
| --- | ---: | ---: | ---: | ---: | ---: |
| Retained v2.4 baseline | 44 | 22 | 1 | 0 | 18/22 |
| Initial v3.0 candidate | 44 | 21 | 0 | 1 | 21/21 |
| v3.1 bounded repair | 44 | 22 | 1 | 0 | 22/22 |
| v3.2 performance recheck | 8 | 4 | 2 | 0 | 4/4 |
| v3.3 source-stage cost skill | 8 | 4 | 0 | 0 | 4/4 |

Every attempt is retained: **148 reviews, 73 TP / 4 FP / 1 FN**. The initial
candidate-schema miss and all memory-advice false positives remain in those
totals. All source requirements were inspected; 147 reviews also complete runtime
and quarantine gates. There were zero failed tool effects or unknown API calls.
Derived diagnosis separates one schema failure and four reasoning false positives;
historical raw failure labels are not rewritten.

The final selection takes the **latest attempted** candidate for every case/mode,
without filtering outcomes: 36 v3.1 reviews for unchanged roles and eight v3.3
performance reviews. The initial comparison interleaved controls/candidates;
corrections use fresh candidates against retained controls. Only the final eight
use an accurately recorded 3072 output ceiling; earlier reviews use 8192. This is
not a fresh randomized 44-review full-v3.3 comparison.

| Final subset | Reviews | TP / FP / FN | Kind correct/matched |
| --- | ---: | ---: | ---: |
| Original, provided | 12 | 6 / 0 / 0 | 6/6 |
| Original, autonomous | 12 | 6 / 0 / 0 | 6/6 |
| Held-out, provided | 10 | 5 / 0 / 0 | 5/5 |
| Held-out, autonomous | 10 | 5 / 0 / 0 | 5/5 |

All five specialists execute successfully. Final selection: **22 TP / 0 FP / 0 FN**,
zero duplicates, all 44 source/goal/runtime/quarantine gates pass, and all 22
matched kinds are correct. The 22 negative reviews emit no findings. Held-out
primary detection was already perfect in the retained baseline; the demonstrated
held-out improvement is kind accuracy **8/10 to 10/10**, not a recall gain.

Manual source/contract review supports all 22 primary findings but flags **three
secondary impact extensions**: an abstract handle called a file handle, and two
indirect-SQL impacts claiming disclosure/authorization consequences or arbitrary
execution beyond the shown SELECT manipulation. Pagination consequences are
contract-based inferences; complexity claims are unmeasured operation analysis.
These judgments are Codex author self-review, not independent human adjudication.
See `m19-manual-adjudication.json`; no raw finding or gold label was changed.

## F. Resource usage

| Journal | Conservative charge, USD |
| --- | ---: |
| `m19-live-run-01.json` | 0.44098125 |
| `m19-live-run-02.json` | 0.23087475 |
| `m19-live-run-03.json` | 0.04896150 |
| `m19-live-run-04.json` | 0.04146975 |
| **M19 total** | **0.76228725** |

All 247 API responses finish with `stop`; zero unknown consumption or local cap
refusals. Total metered tokens: 727,393 prompt and 57,798 output including any
unallocated usage. Supplied rates are US$0.75/M input and US$3.75/M output;
thinking/unallocated total tokens are conservatively priced as output. Durable
reservations precede API effects. These are rate-based charges, not an invoice.

Cumulative conservative usage is **US$3.14820300** of US$4, leaving
**US$0.85179700**. The earlier **US$0.04114425 unknown HTTP 503 hold remains
charged**. This allocation is not an additional budget grant. Different steps,
revisions and final output ceilings preclude causal cost-improvement claims.

## G. Remaining limitations and acceptance

M19's scoped detection/classification and execution gates pass on this authored
corpus. Small paired cases and repeated modes are not independent population
samples. No held-out outcomes selected corrective prompts: schema repair and
performance changes were chosen from original training regressions. No broad
real-repository recall, severity accuracy or every-clause semantic correctness is
established. Direct specialist results do not prove final synthesis correctness.
The three flagged secondary extensions remain explicit M20 follow-up; M20 is not
implemented by this change.

The v3.2 postflight checker detected a test-file addition after its paid campaign.
Its raw mismatch receipt is retained. Exact archived prompt/test before-images
match the v3.2 freeze, as recorded in `m19-v32-close-source-proof.json`; this does
not hide the mismatch or imply a different test ran then. Final v3.3 has its own
fresh freeze and full regression.

## H. Review and delivery

The M19-only nine-file patch is `tasks/evidence/m19-production.patch`; five-axis
author review is `m19-review.json`. Eight authority/evidence methods are unchanged
by AST or entire-file hash. Source, test, live and credential closing evidence is
consolidated in `m19-verification-summary.json`. Preserve original journals,
interrupted runs and prior milestone work. No commit, push, deployment or M20 work.
