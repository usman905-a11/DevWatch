# M22 Streaming, Observability, and Recovery

Date: 2026-10-21. Baseline: clean `1dac4bc` (M21).
Status: complete for engineering and scoped canonical live recovery verification.

## A. Existing behavior

The canonical runtime already uses owner-scoped durable jobs, a transactional
event outbox, ordered replay through HTTP/SSE/WebSocket/CLI, explicit private
agent checkpoints, root LangGraph checkpoints, and conservative unknown-call
settlement. M8 records tools, model attempts, evidence, candidates and verifier
decisions; M21 persists provider observations before dispatch. Ambient LangSmith
tracing stays disabled. Opt-in metadata export never receives prompts or source.

## B. Gaps reproduced

Root/private node execution lacked explicit entry/exit events. Optional export
created flat event runs, without durable review/agent ancestry. A real tool
timeout emitted `tool_timeout`, which the public event schema rejected, replacing
the intended stop with an event-persistence failure. The initial tests reproduced
these gaps (four failures, one passing control); later coverage checks every
bounded tool diagnostic. Browser rendering initially omitted the new node and
outcome fields; its new component test failed before the presentation change.

## C. Changes

`review/observability.py` wraps actual node invocation with paired
`graph_node_started` / `graph_node_completed` records. Random operation IDs,
bounded node/scope names, elapsed time and execution outcome identify each
invocation. Root graph nodes and nested private agent nodes use the same durable
journal; agent records retain task/role/run/phase/iteration identity. Synchronous
nodes remain off the event loop and their workers drain before cancellation
releases execution ownership. Failed event persistence still fails closed.

The optional LangSmith exporter reconstructs ancestry from persisted random
`job_queued` and `agent_started` event IDs. It supplies `trace_id`, `parent_run_id`
and chronological `dotted_order` to the existing SDK and marks failures with
bounded error codes. Restarted exporters reconstruct the same ancestry across
batches and review resumes. Job/task/source/evidence identifiers remain local;
export inputs/outputs are empty. Historical journals without a root retain flat
export. These are instantaneous **event runs**; actual operation durations remain
in metadata, rather than fabricated execution spans. The field contract follows
the [LangSmith SDK reference](https://reference.langchain.com/python/langsmith/client/Client/create_run)
and is checked through the installed SDK's intercepted HTTP serialization.

The additive event schema accepts the existing bounded tool diagnostics; arbitrary
exception text remains excluded. Updated browser wire accepts both historical
payloads and new metadata, and the existing activity disclosure displays node and
outcome text. No dependencies, agent roles, model policies, source permissions,
acceptance gates, retry ceilings or checkpoint formats change.

Existing names remain authoritative: `job_running/completed` describe review
lifecycle, `agent_started/completed` identify Planner/specialist/verifier work,
`tool_called/result` describe tool requests and outcomes, `evidence_inspected`
acknowledges inspected pages, `finding_created` records publication and
`verification_completed` carries accepted/rejected/uncertain/advisory verdicts.
Existing finalization/acceptance/rendering events continue to expose those phases.
No duplicate alias events are added.

## D. Offline and browser verification

Targeted checks: 77 passed initially; all 27 new M22 backend cases and the
JavaScript command-probe regression pass in the repository `.venv` (28 passed).
Coverage includes live-before-completion nested delivery, cancellation/drain,
every controlled tool diagnostic, failed root nodes, exporter restart ancestry,
actual SDK serialization, resumed checkpoint observations and zero repeated paid
work. Existing crash/unknown-call/partial-failure/deadline tests are included in
full regression; new graceful recovery does not replace those cases.

Frontend: 55 tests and production build passed. Real Chromium rendered the real
Vite-compiled `JobActivity` with 82 events from an actual offline canonical job;
node/outcome text is visible, the native disclosure works by keyboard, and
screenshots cover widths 320/768/1024/1440 with no console errors. This is component
browser verification; service stream/reconnect behavior is separately verified
through actual ASGI WebSocket/SSE tests. Two failed development harness attempts
are retained; fixing Vite preamble/module imports and selecting the installed
compatible browser required no product changes.

The first broad run used the shell's Hermes Python, which lacks the three declared
tree-sitter dependencies. JavaScript parser failures reproduce without the new
instrumentation. That offline run was stopped and retained; no quality gates,
fixtures or product fallbacks were changed. Full regression uses the existing
repository `.venv`, where all three required parsers are installed: **682 passed**,
zero failures/errors/skips, native exit 0, in 1,067.19 seconds. One existing
LangSmith deprecation warning remains. All **174** frozen source/consumer files
match; static compilation, generated wire parity and diff checks pass.

## E. Live verification

One natural full canonical review used the previously approved `empty-defect`
Python source and contract from `m19-live-inputs.json`, static policies and derived
artifacts. Gemini chose the work; no responses, acknowledgements or labels were
injected. Runtime admission and final acceptance remained active. The single
confirmed finding matches the source/contract: `first([])` indexes an empty list
and raises `IndexError` instead of returning `None`. Coverage records both source
and contract inspected, with no failed/skipped files. This is an author-reviewed
single sample, not an accuracy benchmark.

The harness paused at the real saved post-verification assembly checkpoint,
closed the manager, constructed a fresh executor/manager, and explicitly resumed
the interrupted job. It completed with **five API calls before and after resume**
and **17,758 runtime-charged tokens before and after**. All 24 node invocations
have correlated ends, including cancellation; 24 nested node events are retained.
Events across resume reconstruct one trace root. Raw paid observations, source
freeze, journal-before-dispatch reservations, local stores and full event timeline
are retained in `evidence/m22-live-run-01.json` and `m22-live-runtime-01`.

No live LangSmith upload was made. The optional exporter was checked locally,
including real installed SDK serialization, privacy and failure behavior. A hosted
LangSmith UI or remote ingestion success is not claimed. Abrupt process death
during a paid request is not live-tested; existing offline crash/unknown-hold
regressions cover its accounting/recovery contract.

## F. Budget

M22 allocated at most US$0.15 within the unchanged shared US$4 grant. Its one
campaign cost **US$0.01919550** using current reported usage and Google's
[published rates](https://ai.google.dev/gemini-api/docs/pricing), verified on
2026-10-21. There were no unknown completions or cap refusals. Cumulative
conservative spend is **US$3.75995325**, leaving **US$0.24004675**. Earlier
US$0.09968775 unknown holds remain fully included. TLS was verified and ambient
tracing disabled. No working-repository source, secrets or gold labels were sent.

## G. Limits

This proves scoped local observability and recovery on the tested paths. It does
not establish population accuracy, production latency, alternate-model behavior,
remote LangSmith ingestion, or live abrupt-crash recovery. M20/M21 semantic and
protocol limitations remain recorded in their reports. Optional telemetry remains
at most once: unavailable/unknown parent exports can leave incomplete remote
trees, while the durable local timeline remains authoritative. A process crash
can leave a node start without an end; recovery never fabricates its outcome.

## H. Review and delivery

Author review covers correctness, readability, architecture, security and
performance. Source/task/iteration/node metadata is allowlisted; root/agent
ancestry uses random event IDs rather than private identities. Completion events
still settle model reservations transactionally before external visibility.
Authority, budget and acceptance methods are compared against the fixed baseline.
Source freeze, credential scan and diff/contract checks are recorded locally.
All 682 backend tests, 55 frontend tests, production build and scoped browser/live
checks pass. Fixed-baseline checks preserve 14 authority/accounting methods and
unchanged budgets, acceptance, prompts and dependency files. Author review found
no unresolved required finding; this is not independent human adjudication.
The local closure receipt is `evidence/m22-verification-summary.json`. No commit,
push, PR or deployment was requested or performed. M23 is not started.
