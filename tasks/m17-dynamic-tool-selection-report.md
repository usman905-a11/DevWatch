# M17 - Dynamic Tool Selection

Date: 2026-10-20. Status: **COMPLETE - mechanism and scoped verification; semantic limits retained**.

## A. Existing implementation

All seven roles use custom StateGraph JSON action loops. PermissionedTools already
describes registered role-permitted tools and authorizes every execution. The
runtime separately enforces assigned paths, approved commands, database owner
grants and measurement-artifact ownership. The project has no langchain package
or create_agent runtime. Completed M16 source requirements and private progress
remain in place; its existing dirty-tree changes are preserved.

## B. Problems found

Every model call received its complete registered-role catalogue, including
unconfigured runtime commands, analysis tools before source retrieval, and tool
definitions during synthesis. The action schema did not enumerate the current
tool choices. There was no per-call measurement of visible definitions or
unadvertised selections.

An adversarial measurement test also exposed a preexisting shape error: passing
read_source evidence to write_artifact called .get on source text before checking
the record's tool. It now rejects non-measurement evidence with PermissionError.
Review of the new filter found and reproduced a first-verification paging gap:
candidate pages can be delivered before the verifier has private evidence refs.
Delivered context pages now keep read_evidence available.

## C. Changes implemented

PermissionedTools.for_model derives a visible subset while catalogue retains its
complete registered-role meaning. A small tool_selection module owns phase/source
relevance. Specialists initially receive source retrieval; trusted source receipts
or actual selected source pages unlock analysis. Existing evidence remains
retrievable. Synthesis receives no tool definitions or tool-action choices.

Trusted availability callbacks hide commands without a matching approved command
in the assigned files, databases without an owner grant, and measurement output
without its runtime grant. Existing operator grants remain necessary. The model's
tool enum follows the visible catalogue. No visibility decision grants authority:
execution still applies all role/scope/owner/effect checks. A stale or hidden but
role-permitted tool can execute and is counted as unadvertised.

Private checkpoints retain bounded per-call stage, names, catalogue bytes and
proposed-tool visibility. They survive restart, omit arbitrary unknown tool names,
and do not enter prompts, public events or reports. These measurements use the
existing provider-history bound. No dependency, wire-schema or route change.

[LangChain's middleware](https://docs.langchain.com/oss/python/langchain/middleware/custom#dynamically-selecting-tools)
filters tools on create_agent ModelRequest. This repository applies the same
presentation concept at its existing custom catalogue/model-call boundary; adding
that middleware would require replacing its agent loop.

## D. Tests executed

Failing-first evidence: m17-selection-red.txt, m17-capabilities-red.txt,
m17-recovery-and-authority.txt and m17-verifier-paging-red.txt. The last exercises
the installed OpenAI-compatible SDK and real graph, rather than a direct selector
call. The guard fix and authorization gate pass 35 cases. The final focused
selection/recovery/catalogue/SDK gate passes 33 cases in 8.07s.

Fourteen new cases cover all five specialist roles, source-to-analysis progress,
synthesis, hidden/unknown actions, checkpoint restart, scope/owner/measurement
grants and revocation, and actual SDK-to-accepted-report serialization under the
existing 20,000-token context. The catalogue audit retains all strict argument
checks and now expects role/stage visibility in prompts. The existing negative
page-fit test measures the real analysis catalogue; it still requires zero
fabricated delivery/inspection and unchanged response/context bounds.

The initial full-suite process was interrupted for the verifier paging correction
before completion. Its redirected partial output was not flushed; it is not a
passing verification result. The final serial backend run passes **557 tests**,
zero failures/errors/skips, in 950.87s. One existing LangSmith wrapper deprecation
warning remains. The deterministic matrix completes 24/24 reviews with no failed
coverage; its programmed full score remains 1 TP / 0 FP / 5 FN, unchanged from M16.
Generated-contract freshness and compilation pass. Frontend source and public
contracts are unchanged; no additional frontend implementation is part of M17.

## E. Live evaluation

Standing authorization adds US$2 to the shared cap, making US$4 total.
Prior conservative charges are US$1.23684300. M17 allocates at most US$0.60:
US$0.50 initial batch cap, followed by targeted checks using its unspent allocation.
The total M17 allocation never exceeds US$0.60. Exact approved fixtures
and contracts, existing agent/tool policies and fixture-derived results only go
to Gemini; working-repository source and secrets are excluded.

The offline full A/B rehearsal completes ten reviews with all source inspected,
no failed coverage and identical programmed scores in both arms: 1 TP / 0 FP /
3 FN. These are known narrow evaluator misses, not live-model accuracy. The
comparison holds runtime, policies and action binding constant and disables only
catalogue filtering in the static arm; it is not an exact historical M16 binary.
Reservations persist before dispatch, unknown consumption remains charged, model
calls are serial, TLS is verified, and ambient trace export is disabled.

The initial live batch completes all ten paired reviews with full source/goal
coverage and no failed coverage. Both arms score **4 TP / 0 FP / 0 FN**, with zero
duplicates. All 29 tool effects are successful read_source calls on approved
fixture/contract paths. No unadvertised selection or permission denial occurs.

| Initial five-fixture comparison | Full catalogue | Filtered catalogue |
|---|---:|---:|
| Model responses | 34 | 39 |
| Tool effects | 13 | 16 |
| Summed catalogue JSON text tokens | 33,135 | 23,335 |
| Actual input tokens | 109,293 | 111,227 |
| Output including unallocated reported tokens | 6,712 | 8,025 |
| Estimated generation cost | US$0.10713975 | US$0.11351400 |

Across actual calls, catalogue text tokens fall **29.58%**, while generation cost
rises **5.95%** because the filtered arm takes more steps. Actual input usage
rises 1.77%; total provider latency is 121.43s versus 188.23s. This small comparison
does not establish a general cost or latency effect. For 33 dynamic calls whose
roles also appear in the static arm, the same-call full-catalogue counterfactual
is 32,104 versus 19,917 text tokens (37.96% reduction); the other six dynamic calls
are outside that token-counterfactual denominator. Private byte measurements
cover all 39 initial dynamic calls: 170,601 versus 103,323 bytes (39.44% reduction).

Primary claims are source-supported, but both mutation reports add an unsupported
non-list/tuple input-domain clause. The dynamic SQL report adds database compromise
beyond the fixture's demonstrated syntax/predicate manipulation. Both assertion
reports stay within the normal-integer contract; M16's float clause is absent.
These three initial secondary flags are retained separately from core scores.
Broader semantic non-regression is **not established** by the paired comparison.

A targeted SQL pair's static report passes with narrow impact wording. Its
dynamic review hits the local conservative reservation cap before another API
dispatch. The partial review remains a missed defect with failed source/goal
coverage. Generic provider-failure/unknown-completion graph text reflects that
local refusal; the meter has zero unknown API consumption. A fresh dynamic SQL
review, with US$0.15 reservation headroom inside the unchanged M17 allocation,
passes all checks and stays within syntax/query-manipulation impact. No code or
prompt change was made between attempts, so this is not a semantic-verifier fix.

All attempts retained: **13 reviews**, 12 with complete source/goal coverage and
no failed coverage; raw score **10 TP / 0 FP / 1 FN**. All **91 generation responses
stop**, with zero unknown consumption and one local pre-dispatch cap refusal.
All 37 actual tools are successful approved source reads; zero unadvertised
proposals, failed tool effects or permission denials. Evidence: three
m17-live-run-*.json journals, m17-live-summary.json and m17-live-adjudication.json.
Claim inspection is Codex review, not independent human adjudication.

## F. Resource usage

The local inventory covers all 24 tools and 16 role/phase/source profiles.
Specialist first-call catalogue bytes fall 59.18-78.27%, with one definition
instead of three to seven registered builtins, depending on role. These byte
counts are deterministic conservative input-token bounds, not actual tokenizer
counts. Live measurement separately records standalone catalogue JSON text
tokens, actual input/output usage, selections and cost. Seventeen countTokens
requests successfully measure all 12 unique catalogues used in the live reviews.

[Gemini countTokens](https://ai.google.dev/api/tokens) tokenizes input text without
generating a completion. Counting calls retain their byte-plus-framing reserve
at the input rate; the harness does not assume they are free. Current verified
[Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) is US$0.75/1M input
and US$3.75/1M output including thinking through 2026-12-31. Unallocated reported
tokens remain charged at the more expensive output rate.

M17 generation charges: **US$0.28202325**. Retained conservative counting charges:
**US$0.05128350**. New conservative total: **US$0.33330675**, including the partial
attempt. Historical charges US$1.23684300 bring the shared total to
**US$1.57014975 of US$4**, leaving **US$2.42985025** for later milestones.
These are supplied-rate conservative accounting figures, not billing guarantees.

## G. Remaining limitations

The five approved fixtures are a small fixed comparison, not a general accuracy
benchmark. Unadvertised selections and failed effects are measurable protocol
signals; they do not alone establish semantic tool appropriateness. Standalone
catalogue token counts are not the marginal count of a complete prompt. Smaller
catalogues do not guarantee lower total cost if the model chooses more steps.
The three secondary flags observed in this initial live batch remain in the raw
reports. The narrow SQL recheck does not prove that broader consequences cannot
reappear. M18 broader prompts and M20 semantic verification remain separate
milestones. The known narrow programmed evaluator still misses five full-system
defects despite complete source coverage; its rules and gold labels are unchanged.

## H. Review and delivery

The five-axis review compares M17 production changes against captured working-file
snapshots rather than HEAD, preserving completed M16 work. Both required findings
(measurement-shape rejection and first-call verifier paging) are addressed with
reproducing tests. Evidence: m17-review.json, m17-production.patch,
m17-tool-inventory.json, m17-start.json and m17-frozen-sources.json.
All 151 frozen source/fixture hashes match after live testing. Final source
integrity, credential-boundary scan, wire freshness and diff checks are recorded
in m17-live-boundaries.json and m17-verification-summary.json. No execution grant
method changed; the measurement-shape guard is a rejection/error correction,
not a claim of a demonstrated cross-principal vulnerability.
No commit, push, deployment or later milestone was performed.
