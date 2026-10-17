# Execution ledger — plan: tasks/seven-agent-design.md

Spec authority: the user's agreed seven-agent design and two final fixes, recorded
in tasks/seven-agent-design.md. Started 2026-10-11.

Pre-flight: M0 contracts feed M1 jobs and M3 graph; current four-role schemas are
incompatible, so migration consumers must use the new contracts.
Pre-flight: M1 persisted events feed M4 transports; client disconnect must never
own or cancel job execution. Job state/outbox must commit together.
Pre-flight: M3 draft feeds M4 renderer; completion must finalize before acceptance
or rendering. Same final-agent identity operates both phases.

Ruling: retain the dirty shared workspace on a local feature branch rather than
create a clean checkout — existing user work is part of the migration baseline —
cost if wrong: less isolation; no existing changes may be reset or committed.
Ruling: use this tracked ledger instead of Bash-only skill helper scripts — Windows
and no authorized commits make git-only ledgers unsuitable — cost if wrong:
bookkeeping is manual, with test commands and results retained here.

Baseline: branch feature/seven-agent-remediation, extensive staged/unstaged and
untracked prior work. Historical tasks/plan.md and tasks/todo.md preserved verbatim
under tasks/history/ before replacing the active plan. No source edits yet.

M0: contract slice complete — 12 contract tests RED → GREEN. Exactly seven
identities, scoped role tools, structured planner/candidate schemas and sibling
usage/private-state fields. Environment/dependency inventory remains open.
M1: durable job/outbox slice complete — 8 SQLite/async tests RED → GREEN. Atomic
owner-scoped idempotency, state/outbox rollback, separate ordered Event Store,
client-independent wait, explicit cancellation and graceful interruption/resume.
Crash leases, snapshots, SSE/WebSocket and service wiring remain open.
M3: cumulative budget slice complete — 6 budget tests RED → GREEN. Final-agent
reserve, 3 in-flight reservations, cumulative role/task limits, persisted pending
consumption, schema/retry/time accounting and provider-overrun accounting.
M3: specialist subgraph slice complete — 6 tests RED → GREEN. Five iterative
LangGraph subgraphs, role permissions before execution, tool evidence refs,
schema repair, restored limits and task/role output binding. New paths explicitly
disable ambient LangSmith tracing; the privacy regression failed before the fix.
The initial new-subgraph test run attempted external tracing due to inherited
configuration; networking was blocked. No live model calls were made.

Latest focused gate: `python -m pytest tests/test_seven_agent_contracts.py
tests/test_review_budgets.py tests/test_durable_jobs.py tests/test_iterative_agents.py -q`
with tracing environment disabled: 32 passed, one upstream SDK deprecation warning.

M1: snapshot/cache slice complete — 5 real-disk tests RED → GREEN. Distinct paths
for all five stores, snapshot hashes/owners, scratch isolation, integrity checks,
sensitive/traversal exclusions and version/owner-partitioned Repo Cache.
M3: finalization tail slice complete — 4 tests RED → GREEN. One bounded targeted
follow-up through existing tasks, completion/finalize before draft acceptance and
rendering, known-candidate/verified-reference/confidence checks, separate finding
groups and deterministic JSON/escaped Markdown. Planner and combined final-agent
execution and structural gate are still open; the tail takes those dependencies.
Hardening: 3 further tests RED → GREEN for cumulative wall-clock accounting,
avoiding double-counted job/agent elapsed time and failing executor conflicts rather
than leaving a job indefinitely running.
M0: declared test extra and aligned Python minimum with existing tomllib use;
dependency and legacy replacement map recorded in migration-inventory.md.

Pre-review focused gate: 44 passed. Full backend regression: 269 passed, 3 skipped,
one upstream LangSmith deprecation warning, 37.56s. Frontend: 40 tests passed;
TypeScript/production build passed. Existing Vite/plugin deprecation notices remain.
Evidence logs: tasks/evidence/seven-agent-{backend-regression,frontend-regression,
frontend-build}.txt. Backend artifacts isolated via DEVWATCH_RUNS_DIR in temp;
tracing disabled for test processes. Fresh clean dependency installation was not run.

Final review: one independent reviewer performed source-only review of the new
foundation modules/tests. All six required findings reproduced before fixes:
unknown/total-only provider usage, omitted verified findings, Windows path aliases,
unclaimed worker cancellation, reset follow-up admission and lost failed coverage.
The Markdown description omission was upgraded to required because a causal
defect explanation must survive human-readable export. No further reviewer pass.

Final fixes: 13 new regression cases RED → GREEN, plus one additional timeout
accounting regression RED → GREEN. Unknown provider completion is charged in both
private state and the job ledger. Admission is persisted before follow-up and
cannot decrease; verified decisions must cover all candidates and outputs; failed
and skipped coverage are merged deterministically. Windows aliases fail before
snapshot writes; only a locally claimed worker can interrupt execution on shutdown.

Final review validation boundaries: live providers and quality remain unmeasured
(scripted-provider tests); dependency vulnerability status and fresh install remain
unverified (no dependency upgrade/release); deployment/transport enforcement,
crash leases and the documented later slices remain open. None is treated as a
complete or production-ready capability. No deferred cosmetic findings remain.

Final regression after the fix pass: `python -m pytest -q -rs` passed with
283 passed, 3 skipped, one upstream LangSmith deprecation warning, 23.89s.
The suite includes 58 new foundation tests. The three skipped tests require file
or directory symlinks unavailable with this Windows process's privileges.
The backend evidence log now contains this final run. Frontend validation remains
40 tests passed and TypeScript/production build passed; no frontend changes were
made by this foundation slice or its review fixes.

Foundation slice verified. Service/CLI/frontend cutover, the full root graph and
agent execution, transport integration, crash recovery, PDF rendering and legacy
removal remain pending. Overall milestones remain unchecked until their complete
acceptance gates pass. No commit, push or deployment was performed.

Continuation 2026-10-11: M3 control-agent execution tests RED (8 failures for
missing execution paths) to GREEN (18 control/specialist tests). Planner scope is
validated before dispatch; combined final identity records verification before
synthesis and cannot alter decisions. Deterministic policy-bounded model selection
supports complexity/confidence escalation. Next: blackboard, structural evidence,
selective source context and the canonical root graph.

M2 context/intelligence slice: 5 tests RED to GREEN using real disk/cache. Python
AST facts and immutable evidence are cached and owner-bound; source/tool retrieval
is scoped and bounded. JS/TS parser absence is explicit, not a fabricated AST.
M3 root integration: 4 end-to-end tests RED to GREEN through DurableJobManager,
LangGraph, all five stores, selective tools, blackboard, structural gate and the
completion-first tail. Events contain metadata rather than source or raw payloads.
Database diagnosis: synchronous checkpoint writer-lock reads blocked the async
saver; WAL reads now avoid writer locks and private writes use a worker thread.
Nested graphs now disable implicit inherited checkpoints: acceptance capabilities
are process-local, while structured agent progress is persisted explicitly.
M1/M3 recovery: 2 tests RED to GREEN. Resume preserves completed Verification and
continues Synthesis; follow-up request and round admission commit atomically in
Job Store, then resume executes an admitted but unfinished follow-up once.
Canonical graph is callable by the durable manager; current transports still use
the legacy engine until M4 migration. No CLI/REST/frontend cutover is claimed.
Current task: independent core review and full backend regression. Optional
integrations, live-provider quality, process-kill leases, JS/TS parsers, command
and measurement adapters, PDF and transport migration remain open.

Independent core review: seven Required findings, no Critical or cosmetic findings.
Eight regression cases failed before the single fix pass and then passed. Initial
specialist cancellation resumes with cumulative state; dispatch failure cancels
and drains siblings; task IDs are safe for persisted events. Aggregate evidence
records complete source scope and enforces it on reads, context and candidate
validation. Planner summaries fit the selective-context bound. Final context
contains task IDs and candidate provenance, and follow-up targets are validated.
Inspection coverage is exclusively runtime-derived. Final-agent budget exhaustion
produces a deterministic partial draft with uncertainty, never new confirmed
defects, through the same Completion Assessment/acceptance/renderer order.
Focused post-review gate: 35 passed, one upstream SDK deprecation warning.
No reviewer rerun; covering regressions and the full suite are the verification.

Core review boundaries: live-provider accuracy, transport/client migration, JS/TS
parser and trusted command/measurement adapters, PDF, process-kill leases,
dependency security and legacy removal were not assessed as finished. They remain
explicit milestone work rather than production claims. The partial-outcome fix
covers final-agent budget exhaustion; other mandatory-agent failure recovery and
classified transient retry wiring remain open before M3's complete gate.
Final core regression after the fix pass: `python -m pytest -q -rs` with tracing
disabled and DEVWATCH_RUNS_DIR isolated in temp: 310 passed, 3 skipped, one upstream
SDK deprecation warning, 44.94s. The three skips require unavailable Windows
symlink privileges. Evidence: tasks/evidence/canonical-core-backend-regression.txt.
This continuation added 27 tests, all observed RED before their implementation
or review fixes. Focused core/recovery coverage is scripted-provider integration;
no live model calls or external integrations were exercised. Source compilation,
whitespace and targeted diff checks passed. No frontend files or dependencies
changed in this continuation, and no commit/push/deployment occurred.

Core integration slice verified. Next milestone work includes the remaining
M2/M3 runtime adapters/recovery/retries and M4 service/client migration before
cutover or legacy removal. Overall milestone gates remain open as listed in todo.

Continuation: canonical retry/recovery and service transport slice (2026-10-11).
M3: classified throttling/server errors get at most two persisted retries per
operation, within the same iteration and cumulative token/time limits. Quota,
authentication, timeouts and unknown completion are not replayed. All unknown
usage is charged conservatively, and the reused provider adapter now disables
SDK retries so there is no hidden second retry budget. Retry events contain only
metadata. Six initial failures observed RED; 25 core/retry/recovery tests GREEN.

M3: failed Planner and combined final agent produce explicit partial outcomes,
with authoritative failed/skipped coverage and no confirmed candidates. Planner
failure does not silently invent specialist work or make another model call.
Hard deadline recovery drains execution first, reads persisted private/root
checkpoints, revalidates evidence, then uses the existing Completion Assessment,
acceptance and renderer. Recovery performs no model/tool investigation and never
runs on explicit cancellation. Its administrative finalization is capped at five
seconds, recorded as elapsed time, and cannot replenish any review budget.
Three deadline-recovery tests observed RED then GREEN.

M1/M4: runnable canonical FastAPI factory at review/service.py owns the durable
manager, executor and five stores. Snapshot capture is separate from idempotent
job submission; source/claims never enter the Job Store request. Owner identity
is consistent across HTTP/SSE/WS and stores only a credential hash. Production
requires configured credentials; unauthenticated development access is loopback
only. HTTP body/JSON/source/cursor bounds and generic errors prevent accidental
source/credential echo. Reports are served from finalized deterministic results.
WS supports headers or a bounded first authentication message, never URL secrets;
explicit origins are enforced. SSE/WS replay the same ordered persisted events.
Client disconnect drains viewer tasks without cancelling the review. Shutdown
interrupts active jobs, and explicit resume retains identity/accounting.
Eight initial transport tests observed RED before implementation; two additional
regressions exposed non-ASCII authentication errors and idle WS viewer leakage,
then GREEN after fixes. Current focused job/deadline/service gate: 24 passed.

This is an independently runnable service migration slice; existing CLI/frontend
consumers remain on the old API until their migration checks pass. No default
cutover, compatibility shim or premature legacy deletion was introduced.
Full regression and one fresh source review of this continuation are next.

Fresh source review: five Required findings (unknown-completion transport retry,
retry budget on resume, recovery losing initial findings/mislabeling finished
tasks, timeout provenance, oversized replay cursors), plus binary WS auth rejection
graded Minor. All five Required enter the one fix pass. Reproducing regressions
recorded in tasks/evidence/service-fix-pass-red.txt (6 failed, 21 passed).
Full regression before fixes: 333 passed, 1 deadline-path failure, 3 platform skips.
Systematic debugging reproduced timer/accounting divergence using a controlled
accounting clock; the real deadline fires without the accounting clock reaching
600. A separate executor TimeoutError must remain an ordinary failure.

Final: Ruling: regrade binary first-message WS authentication as Required — the
implemented authentication boundary must reject malformed unauthenticated frames
without an unhandled ASGI exception; the reproducer demonstrates that broken
boundary — cost if wrong: a small protocol validation change beyond polish.
This is part of the same fix pass; there are no deferred Minor findings.

Review exclusions remain milestone work explicitly listed above and in todo,
not deviations from the final architecture or claims of migration readiness.
Reviewer performed source inspection only; no code, external systems or edits.

Final fix pass: all six findings fixed, with reproducing RED tests and 41 focused
tests GREEN (one existing upstream SDK warning). Adapter-originated transient
retries require an explicit safe HTTP status; connection reset/unknown transport
completion is never replayed. Pending retry operation and schema-repair phase are
versioned graph/private-checkpoint control state; resume retains the original
iteration/counter, while unknown dispatched calls lose safe-retry admission.
Recovery rebuilds root initial results before merging scoped private follow-up
progress; successfully completed tasks retain their status/coverage. Deadline
provenance comes from asyncio.timeout.expired(), with an exhausted ledger even
when the accounting clock lags. Executor-originated timeouts do not invoke it.
HTTP/SSE/WS and Event Store enforce one SQLite-safe replay cursor maximum.
First-message WS authentication explicitly rejects binary frames with policy
close 1008. No second reviewer pass; fresh full regression verifies the fixes.

Final: fixed unknown-completion replay —
test_adapter_transport_error_with_unknown_completion_is_not_replayed RED→GREEN.
Final: fixed retry/repair resume allowance —
test_resume_during_retry_backoff_preserves_operation_and_iteration and
test_retry_resume_preserves_schema_repair_phase RED→GREEN.
Final: fixed lost initial candidates and false timed-out coverage —
test_deadline_after_empty_followup_retains_initial_candidate_and_completed_coverage
and test_canonical_timeout_recovery_preserves_inspection_without_new_model_calls
RED→GREEN.
Final: fixed timer/accounting mismatch —
test_manager_deadline_calls_recovery_only_after_executor_is_drained[True]
RED→GREEN; test_executor_timeout_error_is_not_a_job_deadline verifies provenance.
Final: fixed cursor overflow —
test_invalid_requests_and_paths_have_safe_bounded_errors and
test_event_store_rejects_oversized_cursor_before_sqlite_binding RED→GREEN.
Final: fixed malformed WS authentication —
test_websocket_auth_is_header_or_first_message_never_url RED→GREEN.

Fresh full backend regression after this single fix pass: 343 passed, 3 skipped,
one upstream SDK deprecation warning, 70.89s. Command: python -m pytest -q -rs,
tracing disabled, DEVWATCH_RUNS_DIR isolated in temp. Evidence retained at
tasks/evidence/service-backend-regression.txt. Skips require unavailable Windows
file/directory symlink privileges. Source compilation and targeted whitespace/diff
checks passed. No frontend/dependency changes, external provider calls,
commit/push/deployment, clean-install or production/proxy validation occurred.
Runnability verified through FastAPI lifespan and ASGI/TestClient transports with
scripted providers; live model accuracy is not inferred from these tests.

This continuation's service/retry/deadline slice is verified. The complete
remediation remains open: process-kill leases, JS/TS intelligence, trusted runtime
adapters, CLI/frontend/watch/PDF migration, evaluation/integrations and final
legacy removal still need their milestone gates. Existing consumers retain their
behavior until successful migration and cutover; no milestone was prematurely
marked complete.

## CLI and source capture continuation (2026-10-11)

Pre-flight: local capture produces files plus selected change paths and omission
metadata; SnapshotRequest accepts only skipped/failed/limitations (never inspection).
Metadata gets an independent manifest hash; old source-content hashes keep their
meaning. Shared Blackboard coverage combines omissions with authoritative runtime
inspection. Client consumes the same public JobView and finalized report schemas.
CLI consumes the job API, never the old pipeline. Empty scope uses existing
completion/acceptance/render nodes without inventing an AI response.

Capture coverage: two service tests RED (metadata unsupported) -> GREEN, with ten
store tests passing. Local source capture: six tests RED (collector absent) ->
GREEN, covering staged/unstaged/untracked/renamed/deleted paths, clean/nested Git
scope, exact bytes, bounded selection and explicit Git fallback. Windows Git
ownership was handled with a per-invocation selected-repository safe.directory;
global trust was not changed. Preserve system core.autocrlf for correct status,
disable all configured execution filters instead of disabling all system config.

Job client: eight tests RED (module absent) -> GREEN, real FastAPI/graph/stores
behind an injected HTTP transport and scripted provider; invalid response bounds,
owner errors, unknown submit outcome, idempotent retry, reports and polling verified.
CLI/empty-scope: five expected RED failures -> all six tests GREEN (one existing
output-refusal behavior also passed). Captures/submits once, leaves no-wait jobs
running, retrieves finalized reports, rejects source output/overwrites, replays
exact submission intent and exposes explicit controls. Empty scope makes zero
model calls while reporting no source inspection through the existing final tail.

Migration: cut over CLI after these integration checks; remove legacy CLI pipeline
import and obsolete pipeline-mocked test. Keep legacy engine/server/web behavior
until their own consumer gates pass. No commit, deployment or dependency changes.
Full regression and final independent source review follow below.

Fresh full regression before independent review: 365 passed, three Windows symlink
privilege skips, one existing SDK deprecation warning. CLI help and source
compilation verified; no legacy pipeline reference remains in CLI/client.

Final source review: one fresh reviewer identified four Important capture issues.
One RED->GREEN fix pass:
- Non-Git eager enumeration/skipped-directory counting: replaced os.walk with
  streaming scandir, charging every entry, bounding pending paths/catalog and
  ten-second enumeration time; regression stops consumption at five fixture entries.
- Git changed paths reintroduced after catalog truncation: cap the combined
  prioritized candidates; ten changed fixtures now admit only the configured three.
- Generated directory inconsistency: apply the same component policy before
  opening Git/non-Git candidate source; tracked dist/build/coverage/venv omitted.
- Unreadable directory lost from coverage: catch per-directory enumeration errors,
  record unavailable_directory, continue readable source, suppress raw OS details.
- Submodule-only filter execution: a controlled temp fixture reproduced a harmless
  marker-writing clean filter. Status now uses --ignore-submodules=all; gitlink
  entries are identified without traversal and recorded as skipped. Marker is no
  longer written. No repository hooks/filters run during successful capture.

Final: fixed true catalog bounds —
test_directory_catalog_stops_consuming_at_limit_even_for_excluded_entries and
test_git_changed_candidates_cannot_reenter_truncated_catalog RED->GREEN.
Final: fixed generated-directory capture —
test_tracked_generated_directories_use_same_policy_as_directory_capture RED->GREEN.
Final: fixed unreadable-directory coverage —
test_unreadable_directory_is_reported_without_raw_os_error RED->GREEN (fixture
asserts exact CRLF bytes separately to avoid a Windows newline false failure).
Final: fixed submodule execution —
test_parent_git_capture_does_not_execute_submodule_only_filter RED->GREEN.
Combined focused verification: 27 passed, one upstream SDK deprecation warning.
No second reviewer was dispatched; full regression follows this fix pass.

Final: minor (deferred): client validates uploaded source hashes but does not
compare echoed capture metadata/hash; an incompatible service could lose omissions.
Final: minor (deferred): default metadata fields keep pre-metadata canonical
manifests readable; stripping both fields on local disk cannot be detected by the
metadata hash. Host operators remain trusted; this is an integrity limitation,
not evidence of a remote bypass. Neither is part of this fix pass.

Final fresh backend regression after the single fix pass: python -m pytest -q -rs
-> 370 passed, three Windows symlink-privilege skips, one upstream LangSmith SDK
deprecation warning, 58.07s. Evidence: tasks/evidence/cli-backend-regression.txt.
Tracing disabled and DEVWATCH_RUNS_DIR isolated in temp. Source compilation,
CLI help and targeted git diff --check passed. Initial CLI RED still entered the
legacy tracing path and its ambient LangSmith network attempt was blocked; the
canonical CLI no longer imports that engine. Scripted-provider ASGI integration
does not establish live model accuracy, proxy deployment or a clean dependency
install. No frontend tests were rerun because this slice changed no frontend code.

CLI/capture slice verified. Exactly seven AI identities, existing permissions,
Balanced budgets, stores, streaming and completion-first gates remain unchanged.
Frontend/watch clients, process-kill recovery leases, JS/TS intelligence, trusted
command/profiling adapters, PDF/evaluation/integrations and final legacy removal
remain open behind their existing migration gates. No unrelated changes discarded,
dependencies added, commits, pushes or deployment performed.

## Browser durable transport continuation (2026-10-11)

Pre-flight: frontend still expects legacy ReviewReport/AgentStepUpdate and owns
reviews through WebSocket lifetime. Canonical transport must be built/tested before
hook/components can cut over. New browser client consumes canonical JobView,
SnapshotManifest, ReportDraft, owned source excerpts and PersistedEvent, without
converting back to obsolete schemas. Existing UI stays until consumer parity.
Generated schemas derive from backend models (scripts/export_review_contracts.py);
serialized response fields, including defaults/nulls, are required. --check detects
wire-schema drift. No new schema dependency or runtime AI identity was introduced.

Baseline frontend: 40 passed in 13 files. Browser client: eight RED (module absent)
-> GREEN; capture method: one additional RED (missing method) -> GREEN. Tests
cover exact submission intent/key replay without hidden retries, header credentials
and refused redirects, safe errors, job/version/budget identity, completed-only
reports, snapshot/range/bucket/confidence validation, bounded immutable source,
explicit cancel/resume and byte limits. Capture compares exact source/manifest/
omission hashes, with Python Unicode key ordering and newline semantics.

Event observation: five RED (module absent) -> GREEN. Fetch-based SSE carries auth
headers and Last-Event-ID, decodes split UTF-8 and CR/LF frames, validates canonical
metadata and job identity, suppresses duplicate replay, reconnects only GETs at the
last accepted cursor (two reconnects), caps frame/total bytes and transport time,
and aborts observation without cancelling execution. Protocol violations do not
retry. Persistent stores/server streaming and Balanced job budgets are unchanged.

Wire parity: generated offline fixtures from real FastAPI lifespan, canonical graph
and stores with a scripted provider (scripts/export_browser_fixture.py). Actual
reports/events/source/manifests are accepted; Unicode backend task IDs exposed JS
UTF-16/ASCII-word mismatches. That case RED -> GREEN with scalar character counts
and Rust-compatible Unicode word matching. No live model accuracy inferred.
Two build errors were test fixture type narrowing and Array.at with ES2020; kept
the existing target and fixed the caller/types instead of changing dependencies.

Fresh pre-review frontend regression: 58 passed in 16 files; TypeScript/Vite build
passes with existing plugin/esbuild deprecation warnings. Backend regression and
one final independent source review follow. App/hooks/components are not migrated
yet; no frontend cutover or legacy deletion claimed for this transport slice.

Final browser review: one independent source reviewer; two Important findings and
two Minor findings. Important grades retained. No second review dispatched.
Final: fixed observer shutdown blocked by pending consumer callbacks — stop tests
for onEvent/onJob/onReport and deadline/late rejection test RED -> GREEN. Callback
waits race lifecycle cancellation, retain rejection handlers, and check cancellation
before accepting cursor advancement or invoking later callbacks. Existing replay
test now correctly expects the last accepted cursor, excluding the event that stops
observation. Transport shutdown never cancels the durable job.
Final: fixed partial reports rejected for valid failed task IDs — backend-validated
security./con task identities preserved in an actual report fixture, RED -> GREEN.
Only coverage fields guaranteed to contain source paths receive path validation;
failed entries remain validated report data, never navigation/tool targets.
Focused fix gate: 14 passed. Whole frontend regression: 63 passed in 16 files;
TypeScript/Vite build and generated schema drift check pass. Existing Vite/plugin
deprecation warnings remain. Evidence: browser-review-{red,focused}.txt,
browser-frontend-regression.txt and browser-client-build.txt in tasks/evidence/.

Final: minor (deferred): expected manifest uses a plain object, so a valid __proto__
source filename makes capture reject the response. Use a null-prototype dictionary
in a later focused capture fix; source/hash mismatch fails closed today.
Final: minor (deferred): JS end-anchor accepts a trailing newline in some generated
schema patterns unlike backend Rust regex. Add true end-of-input matching in a
later schema parity fix. Browser metadata is display-only; backend validates all
submitted inputs and tool permissions. No authorization bypass established.
The earlier update anticipated fixing these minors too; the loaded execution
workflow limits this final pass to required findings and records minors explicitly.

Final review boundaries: UI consumer migration, real-browser UX, live-provider
accuracy and deployment remain outside this transport slice. Old UI remains usable
with its existing server; this new client is not imported into the UI until cutover.
Exactly seven identities, LangGraph orchestration, Balanced limits, tool grants,
five stores, completion-first gates and legacy-removal sequence remain unchanged.

Final fresh backend regression after this fix pass: python -m pytest -q -rs ->
370 passed, three Windows symlink-privilege skips, one upstream LangSmith SDK
deprecation warning, 64.00s. Tracing disabled and artifacts isolated in temp.
Evidence: tasks/evidence/browser-backend-regression.txt. Source compilation,
schema drift check, git diff --check and new-file whitespace checks pass. No
runtime dependency, existing UI source, reviewed repository source, unrelated
dirty work, Git staging, commit, push or deployment changed in this slice.
M4 browser transport foundation marked complete; hook/component/watch migration,
PDF, consumer cutover and legacy deletion remain open under the migration gates.

## Canonical frontend migration continuation (2026-10-12)

Using the existing execution/TDD/frontend engineering/API/migration/security skills.
Binding design and migration rule unchanged. Implemented owner-checked job snapshot
catalog for reopening jobs; catalog contains immutable hashes/line counts/omissions,
not source text. Backend catalog regression RED (404) -> GREEN; owner tests pass.
Browser SDK catalog/hash validation and __proto__ capture regression RED -> GREEN.
The earlier trailing-newline Minor did not reproduce: actual Node RegExp and
Pydantic both reject it. Characterization test passes without a production change;
the unsupported finding is closed rather than patched speculatively.

New React-independent ReviewSession owns viewer lifecycle and exposes canonical
state through useSyncExternalStore. Five integration tests RED -> GREEN: exact
intent retained before POST, explicit same-intent retry after unknown completion,
owned reopening/source reads, stale capture invalidation and explicit cancellation.
Disposal never cancels execution. Folder collector tests RED -> GREEN: per-file/
total/file-count/catalog caps, source byte preservation, UTF-8 validation, sensitive/
generated exclusions, omission coverage. Additional duplicate-start and service
account exclusion regressions RED -> GREEN. Native browser fetch rejected the
client receiver with Illegal invocation before any network request; real-browser
RED plus receiver probe -> default fetch closure fix -> browser GREEN.

Canonical UI: separate confirmed/uncertain/advisory groups, causal rationale,
evidence refs/remediation and explicit inspected/skipped/failed/limited coverage.
Seven-role event activity, job identity/status/reconnect/resume/cancel, memory-only
credentials and retry intent; immutable bounded excerpts with actual line numbers;
JSON/Markdown exports are deterministic code, never model publication actions.
Three presentation tests and one workspace test RED -> GREEN. App entry cutover
test RED (old interface) -> GREEN. Existing source-entry/access/remediation tests
ported to the actual canonical interface; no old report-format adapter retained.

Ruling: browser Git repository reviews are reopened from CLI-created jobs rather
than retaining the old arbitrary server-path API — canonical snapshots only accept
uploaded bounded source, and the CLI already supplies Git selection/omissions —
cost if wrong: users start Git reviews in the CLI until a dedicated trusted capture
integration is built. Local folder capture remains available directly in the UI.

Migration gate: canonical transport/session/presentation tests, build and real
Chrome flow passed before removal. Fifteen obsolete frontend files archived in
tasks/history/frontend-legacy-2026-10-12.zip, then removed from executable source:
old socket/API/types/hook, three-role AgentPanel, CodeEditor, source helper and
schema-specific tests. New excerpt/coverage/lifetime tests cover retained behavior;
virtual full-file editor and obsolete severity/replacement schemas do not define
the new contract. No unrelated backend legacy removed before its consumer gates.

Fresh post-removal frontend: 44 tests in 11 files pass (74 before obsolete-test
removal); TypeScript/Vite build passes. Backend: 371 passed, three existing Windows
symlink skips, upstream LangSmith warning. Actual Chrome/ASGI scripted integration
passed capture, client detach/reopen, separate report groups, immutable source,
JSON/Markdown downloads, four widths including 320x640, no legacy/cancel requests
or credential storage. Existing remote Google Fonts request is network-blocked;
no application exception occurred. Screenshots in tasks/evidence/durable-ui-*.png.
Playwright installed only into ignored .tools/browser with automatic network
approval after the sandbox blocked PyPI; no runtime dependency/lockfile changes.
One independent final source review follows; no commit/push/deployment authorized.

Final independent frontend review: no Critical findings; three Important findings
accepted into one fix pass: protect unresolved submission intent at every input/
connection transition, clear local folder selection when attaching another job,
and preserve usable workspace space with expanded controls on short viewports.
Session regression observed RED: reset/attach/start replaces the original key
after an accepted POST loses its response. Browser regressions use an actual
accepted-and-lost POST, completed job attachment and expanded 320x480 controls.
Final: minor (deferred): streamed history advances, but aggregate job status,
tokens and duration remain the latest fetched JobView until refresh/stream end.
Final: minor (deferred): on mobile Files/Source tabs, the skip link does not switch
to the Review pane before focusing its target.
Final: Ruling: unaffected backend algorithms, live provider quality, deployment,
watch/PDF and unresolved tool adapters were outside this frontend source review;
their milestone gates remain open, rather than inferred from scripted UI parity
-- cost if wrong: frontend parity alone does not establish full release readiness.

Final: fixed unknown submission intent loss -- durable-session accepted/lost POST
test RED (changed key after reset/attach/start) -> GREEN; browser RED (Connect,
Open job and both explorer folder controls enabled) -> GREEN. Session guards
retain the original intent; UI disables and guards destructive transitions,
including a folder selection dialog that returns after submission has started.
The explicit retry is the only submission recovery operation; disposal still
does not cancel a job and no automatic POST retry was added.
Final: fixed stale folder after job attachment -- real browser completed job
attachment RED (Run review enabled for the retained folder) -> GREEN. Attaching
a job clears the local capture selection and invalidates any pending selection;
Run review requires a new explicit folder selection.
Final: fixed collapsed workspace with expanded controls -- real browser 320x480
RED (body height zero) -> GREEN (reserved usable workspace and document scroll).
The test leaves connection controls expanded and checks recovery intent guards,
workspace geometry and successful explicit retry; full-page screenshot inspected.

Final fresh verification after this one fix pass: npm test -> 44/44 tests across
11 files; npm run build -> TypeScript and production Vite build pass. Chrome +
actual canonical service/graph/stores and scripted provider passes all three
regressions and the capture/reopen/source/export/responsive flow. Backend full
post-removal regression -> 371 passed, three existing Windows symlink skips,
one upstream LangSmith SDK warning (85.72s). Generated contracts drift check,
test-script compilation, scoped diff and new-file whitespace checks pass.
Evidence: ui-review-red.txt, ui-review-browser-red.txt,
ui-review-frontend-green.txt, ui-review-build-green.txt,
ui-review-browser-green.txt, ui-backend-regression.txt in tasks/evidence/.
The intentional lost POST and viewer detachment produce expected network errors;
blocked Google Fonts is unchanged. No application exception/live quality claim.

Canonical frontend cutover slice complete, with two deferred Minor findings above.
The overall remediation plan is not complete: watch/PDF/full consumer cutover,
JS/TS and deeper intelligence/tool adapters, abrupt-process recovery, remaining
backend legacy removal, the 60-case evaluation, IDE clients and optional adapters
retain their existing milestone gates. No unrelated user work, index changes,
commit, push or deployment was performed. The dirty workspace and evidence are
retained because no commit/history-preserving cleanup was authorized.

## Deterministic PDF continuation (2026-10-12)

Resumed existing execution/TDD/API/security/frontend/migration/verification workflow;
PDF skill added for deterministic document production and visual page inspection.
Working branch/shared dirty tree preserved, no staging/commit/publication authorized.
Next M4 slice: accepted-only PDF renderer, generated Artifact Store files, owned
download, bounded binary clients and explicit CLI/web exports. Architecture/agent
identities/common tools/private state/budgets/completion order remain unchanged.
Pre-flight: final renderer returned strings -> persist only a PDF digest in the
same result mapping; binary bytes stay in the separate Artifact Store. Both normal
and deadline recovery finalization use the same accepted-only runtime renderer.

Ruling: use ReportLab's bundled Vera font and visible Unicode escapes for unsupported
glyphs/invisible controls, rather than depending on host fonts or network font
fetches -- cost if wrong: some non-Latin text is readable only as escaped codepoints.
Ruling: already finalized jobs without a PDF artifact return explicit unavailable;
do not rerun a model or fabricate an acceptance capability from stored JSON -- cost
if wrong: older canonical jobs retain JSON/Markdown exports but have no PDF export.
ReportLab 5.0.1 and PyMuPDF 1.28.2 were already installed; declared ReportLab runtime
and PyMuPDF test extras with constraints, no install/upgrade or runtime PyMuPDF use.
Official ReportLab Paragraph docs confirm XML markup support, so every model field
is escaped before Paragraph construction; no images, hyperlinks or model markup run.
Reference: https://docs.reportlab.com/reportlab/userguide/ch6_paragraphs/.

Tests observed RED for missing PDF renderer, service format and CLI binary output;
store tests RED for missing artifact API; stronger tenant substitution test RED
before owner-hashed report directories; all targeted tests GREEN. Browser client
tests RED (missing PDF method) -> GREEN: finalized JSON first, MIME/signature/EOF
checks, exact non-UTF-8 bytes, maximum size and unfinished-job refusal. Common
bounded fetch now collects bytes; text remains strict UTF-8. UI button browser
RED (missing Download PDF) -> implementation. Initial browser validation then found
child PATH chose another interpreter without PyMuPDF; explicit same interpreter
resolved that test environment mismatch, not a product fallback.

Visual sample: actual graph/service accepted report and six-page long coverage
fixture generated in output/pdf/; all pages rasterized with installed PyMuPDF
(Poppler unavailable) and inspected, with geometry/text regression checks.
First visual inspection found a footer-only blank page from a trailing Spacer:
real accepted report test RED -> remove trailing Spacer -> GREEN, samples rendered
again; canonical sample now one page with complete report and no blank page.
First full backend run: 377 passed, three existing Windows symlink skips, one
upstream LangSmith warning, 75.84s; final rerun after layout fix follows below.
Frontend: 46 tests in 11 files and production build pass. Real Chrome/service
flow passes PDF download/text/name plus prior capture/reopen/excerpt/report groups,
lost-response recovery and four viewport widths. Final source review follows.

Final independent PDF source review: two Important findings accepted into one
fix pass: a cancelled to_thread render could still write artifacts, and concurrent
documents shared ReportLab TTFont's mutable face reader. Both were verified RED
before fixes (pdf-final-review-red.txt). Replaced detached rendering with a fixed
child process carrying bounded accepted JSON in and bounded PDF bytes out. The
child imports only the private document formatter, cannot access a store or select
a destination, and is killed/reaped on cancellation, including shielded spawn/
pipe cleanup. Publication occurs in the owner runtime only after successful render
and a cancellation check; no generated file can be written by a detached worker.
Normal and deadline recovery paths share this mechanism. Direct synchronous
document builds serialize font use; concurrent runtime documents have separate
process-local fonts. Mixed-glyph concurrency and real held-worker cancellation/
deadline tests now pass, with no model call during deadline recovery.

Final: Ruling: repeated-space loss was reported Minor but is regraded Important
because an accepted finding's string literal can change meaning ("a  b" becomes
"a b") -- fixed in this same pass rather than deferred; cost if wrong: preserving
spaces can make pathological runs of whitespace consume more document space.
Real PDF text extraction observed RED for the changed literal -> nonbreaking
space encoding for repeated runs -> GREEN; single spaces and literal XML remain
ordinary text. No additional feature or review round was added.
Final: Ruling: reviewer declined runtime/test/layout results, fresh dependency
installation/advisory status, live quality, tagged accessibility and unrelated/
previous UI work -- local runtime/build/layout checks are verified here; fresh
installation, dependency advisory audit, live accuracy and tagged accessibility
are not inferred from them -- cost if wrong: this slice is not release readiness.
The execution skill's referenced requesting-code-review template was absent from
both global roots; the installed review checklist and explicit review package
supplied the source review focus without inventing a template or requiring approval.
Final target after required fixes: 13 passed, including actual process reaping,
deadline recovery, shared-font exclusion, spaces, integrity and pagination.

Final: fixed detached PDF cancellation/publication -- real held child cancellation
and deadline recovery tests RED -> GREEN; cancelled worker is reaped before recovery
or cancellation returns, cancelled rendering writes no artifact, recovery writes
one partial PDF without calling a model. Full suite 381 passed / three existing skips.
Final: fixed unsafe shared font reader -- actual mixed-glyph document build overlap
RED (peak four simultaneous shared builds) -> GREEN (peak one); runtime processes
isolate fonts, direct synchronous calls lock complete builds. Full suite green.
Final: fixed meaningful repeated-space loss -- literal "a  b" PDF extraction RED
(rendered "a b") -> GREEN after encoded whitespace preservation. Full suite green.

Final fresh regression after the one required fix pass: python -m pytest -q -rs ->
381 passed, three Windows symlink-privilege skips, one upstream LangSmith SDK
deprecation warning, 84.46s. npm test -> 46 passed in 11 files; TypeScript/Vite build
passes. Real Chrome + actual service/graph/stores and scripted provider passes
JSON/Markdown/PDF download, source, capture, reopen, separate groups, four viewport
widths and unknown-response retry recovery. Expected lost-response/detach network
errors and sandbox-blocked external Google Fonts are recorded, with no application
exception. Generated contract check, compilation, scoped diff and new-file
whitespace checks pass. Latest accepted one-page and six-page long/Unicode/literal
samples rendered again after fixes; PNG inspection and text/geometry tests pass.
Evidence: tasks/evidence/pdf-{backend-final,browser-final,frontend-green,build-green,
final-review-red,final-review-green,whitespace-red}.txt plus rendered page PNGs.
M4 PDF slice complete. Exactly seven AI identities and agreed budgets/permissions/
stores/completion ordering remain unchanged. Watch, deeper intelligence/adapters,
abrupt-process recovery, backend legacy removal, evaluation and IDE work remain
open as previously recorded; this slice does not claim the whole plan complete.
No unrelated changes discarded; no stage/commit/push/deployment or new dependency
installation performed. Shared workspace and evidence retained as authorized.

## Canonical watch continuation (2026-10-12)

Resumed plan/ledger after an interrupted user turn; no prior watch implementation
or running watch work was present. Shared dirty branch feature/seven-agent-remediation
and unrelated/staged work preserved. Existing execution/TDD/API/migration/security/
review/verification workflows apply; no extra AI identity, runtime orchestration,
tool grant, schema, budget, store or streaming change. No commit/push/deploy authorized.
Pre-flight: watcher is a CLI client of capture/snapshot/job/status APIs; no service
watch endpoint, local engine or model loop. Pending source stays bounded by existing
capture limits; one active service job and one latest pending source version.

Ruling: implement deterministic polling of bounded captures with hashes/scope/
coverage, rather than add a filesystem observer dependency -- cost if wrong:
transient edits between scans are not observed and repeated capture has local I/O cost.
Ruling: submit eligible initial scope after debounce, skip clean Git scope unless
deletion/failure coverage needs reporting, and stop on interrupted/unknown outcomes
for explicit recovery -- cost if wrong: restart requires operator action rather
than automatic resume; --max-reviews limits intentional submissions, not completion.
Directory deletion history is capped at 1000 paths and omissions persist across
debounce; source is never resurrected or written. Disappearing selected targets
stop capture; watch a directory to observe file deletion/recreation.

Seven tests observed RED (missing canonical watcher / CLI command) -> GREEN:
stable latest bytes, running-job coalescing and immutable old source, exact accepted/
lost POST recovery intent with no automatic retry, clean Git/deleted-only scope
without model calls, persistent directory deletion coverage and excluded content,
CLI submission limit without cancellation. Additional Ctrl+C and real graceful
service-interruption characterizations pass. NaN interval regression RED (Typer
range comparisons admitted NaN and a job was submitted) -> explicit finite check
before capture/submission -> GREEN. Nineteen watcher/CLI tests pass against actual
service/stores/graph with scripted providers; no live provider invoked.
Migration: no legacy watcher exists in working tree or HEAD to archive; new watch
consumer uses only canonical APIs. Other backend removal remains under M5 gates.
Final fresh full regression and independent source review follow below.

### Watch final review and resumed fix pass (2026-10-13)

The one independent source review found no Critical issues, two Important
deletion-coverage issues and one Minor callback-isolation issue. Both Important
grades stand: silently losing a deletion makes coverage misleading. No second
review or delegated implementation is needed; the required fix pass is verified
by the original failing cases and the regression suite.

The previous patch was not executed because automatic approval review reached
its usage limit. After the user resumed, source inspection confirmed the old
implementation; the same native apply_patch path accepted the two fixes. No
alternate path bypassed approval review.

Final: fixed deletion forgotten after an intermediate capture omission --
test_deletion_is_retained_after_an_intermediate_capture_omission RED -> GREEN.
Known path names now persist independently of the latest captured contents,
bounded to 1000 paths. Source contents are neither retained nor resurrected.
Final: fixed deletion report suppressed when omission coverage is full --
test_full_omission_list_still_emits_a_truncated_deletion_report RED -> GREEN.
Known deletion/truncation state makes the version reviewable even when no more
omission keys fit; the report includes the explicit unlisted-path limitation.
Twenty-one focused watcher/CLI tests pass, including both final regressions.
Evidence: tasks/evidence/watch-review-{red,green}.txt.

Final: minor (deferred): library notification callbacks receive a shallow intent
copy and a mutable job view. A custom mutating callback can alter watcher state;
the current CLI callbacks only print. Isolate callback payloads in a later slice.

Final: Ruling: source review did not execute the application -- retain the local
real-service/API/store/graph tests as runtime evidence -- cost if wrong: scripted
providers cannot establish live-model finding quality.
Final: Ruling: filesystem race guarantees were not independently assessed --
keep existing bounded capture and polling limitations explicit, without claiming
race-proof watching -- cost if wrong: transient changes can be missed.
Final: Ruling: dependency vulnerabilities and fresh installation were not assessed
in this slice -- no dependency was introduced and existing tooling is reused --
cost if wrong: the current installed environment does not establish reproducibility
or package security in a fresh installation.
Final: Ruling: unrelated staged/dirty work and previous slices were outside the
watch source review -- preserve them and keep their previous evidence separate --
cost if wrong: watch verification is not a whole-project release approval.

Final fresh regression after the required fix pass: python -m pytest -q -rs ->
393 passed, three existing Windows symlink-privilege skips, one upstream LangSmith
SDK deprecation warning, 112.55s. Generated wire-contract freshness, compilation,
CLI watch help, scoped diff and new-file whitespace checks pass. Evidence:
tasks/evidence/watch-backend-final.txt. No frontend or wire schema changed in this
slice, so prior frontend/browser verification was not repeated or relabeled fresh.

M4 canonical CLI watch slice complete, including both Important final review
regressions. Exactly seven AI identities, agreed permissions, budgets, stores,
streaming and completion-before-acceptance ordering remain unchanged. Full M4
parity, M2 intelligence/trusted tools, M1 abrupt-process recovery, M5 backend
legacy removal, M6 evaluation and IDE/optional adapters remain open. No unrelated
changes discarded; no stage/commit/push/deployment or dependency installation.
Shared workspace, test evidence and migration history are retained.

## Two-milestone continuation: M0 and M1 (2026-10-13)

The user requested two milestones rather than another single slice. Earliest
unchecked milestones are M0 and M1. Their completed contract/store/transport
slices remain verified; this continuation closes their missing complete gates.
Plan acceptance checks are recorded in tasks/plan.md. Shared dirty/staged work
is preserved and no commit/push/deploy is authorized.
Pre-flight: lease claims and recovery use the Job Store/outbox transaction;
existing owner-scoped transports remain unchanged. Process locks cover the whole
execution/drain interval so root/private checkpoints and artifacts never have two
live writers for one job. Existing budgets consume persisted unknown reservations.
Pre-flight: fresh dependency resolution must pass canonical and retained legacy
behavior before it becomes the reproducible installation record; do not weaken
tests or remove legacy prematurely to make a clean install appear successful.
Ruling: close M0 and M1, the earliest unchecked milestones -- complete foundations
before later adapters/cutover -- cost if wrong: M2 and M5 remain for later work.
Ruling: use local process-held locks plus persisted leases, without stealing from
a live worker on time expiry -- protects checkpoint/artifact exclusivity across
pause and restart -- cost if wrong: live stalled workers need explicit operator
termination; shared/network filesystem deployment is not supported by this lock.
Ruling: conservatively charge uncertain time between the last saved execution
heartbeat and recovery, capped at the review ceiling -- a crash must not replenish
the 600-second budget -- cost if wrong: a long outage may exhaust the review and
resume produces the existing deterministic partial deadline report.
M0 clean install initially failed at build dependency download in the network
sandbox. The same installation was retried through approved network escalation;
its result must be inspected before claiming reproducibility.

### Required combined review fix pass (2026-10-14)

M0 evidence now includes a clean declared-extra install, pip check, the full
398-test regression before the publication guard, and a second clean offline
installation of 70 pinned/hash-checked runtime/test/build distributions. No
global environment was changed. The original dependency ranges remain intact;
the platform-specific lock records the tested closure, not an unsolicited upgrade
of the user's interpreter. A non-editable wheel was installed in the second
environment and exercised from outside the source import path: all seven
contracts, owned empty-scope review, persisted replay and deterministic PDF pass,
with no model/network call. A deliberately changed dependency wheel is rejected
by pip hash enforcement, with no package installed.

M1 initial process cases: three RED -> GREEN for killed-worker recovery, later
death detection and external cancellation. The live-worker exclusion
characterization passes. Real service death during Synthesis resumes the saved
Verification, immutable snapshot and original job, keeps counters/ownership/replay,
charges the outstanding reservation and adds honest crash coverage (RED -> GREEN).
Remote-cancellation publication regression RED -> GREEN; the bounded artifact
write now holds the Job Store transaction to serialize with cancellation.
Pre-review final regression in the offline environment: 399 passed, three Windows
symlink skips, one upstream SDK warning. Frontend: 46 passed; TypeScript/build pass.

The single fresh source review found no Critical issues, three Important issues
and two Minors. Required grades stand: late checkpoint writers risk stale state,
dead maintenance leaves jobs stuck, and historical/backlog scans delay operation.
Four regressions observed RED before this one fix pass, then GREEN:
- Checkpoint save is shielded and drained through repeated cancellation before
  releasing private persistence or process ownership; resume cannot overtake it.
- Maintenance continues after a transient failure with capped backoff and safe
  structured diagnostics. Finished maintenance tasks can be supervised/replaced.
- Active rows use indexed, bounded queries; running scans use a stable cursor,
  admission fits configured worker capacity, and completed task references are
  pruned. A persisted backlog advances without new client submissions.

Controlled query sample with 1000 terminal and 120 queued jobs: before 2242
deserializations / 0.097159s, after 100 / 0.008580s. These are one local sample,
not a production latency guarantee. EXPLAIN QUERY PLAN confirms status and
status/identity index searches, without a historical scan or temporary sort.
An initial query-plan scratch script left its SQLite handle open during temporary
cleanup; corrected the verification script with contextlib.closing and reran
successfully. Production stores already close their SQLite handles explicitly.
Evidence: tasks/evidence/m0-m1-review-{red,green}.txt and m1-query-plans.txt.

Final: minor (deferred): a complete rendered graph checkpoint is returned unchanged
when a crash happens between graph completion and Job Store completion; its
accepted report does not gain the new recovery annotation. Job events/accounting
still record the interruption; later report-metadata refresh must stay deterministic.
Final: minor (deferred): an older inventory sentence still describes the previous
slice as having no installation. Current dated clean-install results and scope
are explicit here; label that historical sentence in a later documentation pass.

Final: Ruling: reviewer did not execute installers/tests or independently inspect
wheel hashes/contents -- the two real clean installs, changed-wheel rejection,
installed-package smoke and fresh regression provide local evidence -- cost if
wrong: these checks are not an independent supply-chain/vulnerability audit.
Final: Ruling: Unix locks and other OS/Python environments were not executed --
keep the completed gate scoped to this Windows x64/Python 3.11 local service --
cost if wrong: other platforms require their own CI gate before release.
Final: Ruling: clock rollback/suspend was not independently assessed -- monotonic
heartbeat elapsed cannot decrease and recovery conservatively reconciles unknown
wall time -- cost if wrong: outage/suspend may consume the review ceiling and
return a partial report. There is no budget refund on recovery.
Final: Ruling: unrelated staged work, live-provider quality and later milestones
were outside this review -- preserve the shared baseline and retain those open
gates -- cost if wrong: M0/M1 completion is not whole-project release approval.
On-call questions for maintenance diagnostics: is recovery retrying, which bounded
error class caused it, and which maintenance run/entry point emitted it? JSON logs
include only that metadata and capped retry delay, never source or error payloads.
No extra review is dispatched; required covering tests and the final regression
are the completion gate. No stage, commit, push, deployment or legacy deletion.

Final: fixed late private checkpoint writers --
test_shutdown_drains_checkpoint_thread_through_repeated_cancellation RED -> GREEN;
both persistence and execution locks remain held until the real writer drains.
Final: fixed maintenance permanently stopping on a temporary store failure --
test_transient_maintenance_failure_recovers_later_dead_worker RED -> GREEN;
subsequent actual process death is recovered and diagnostics contain no error text.
Final: fixed unbounded history scans and task admission --
test_large_backlog_admits_only_worker_capacity_and_advances_without_new_submission
and test_active_queries_do_not_deserialize_terminal_history_and_are_batched
RED -> GREEN. Indexed active reads and configured capacity are enforced.

Final fresh offline-environment regression after the one required fix pass:
python -m pytest -q -rs -> 403 passed, three existing Windows symlink-privilege
skips, one upstream LangSmith SDK deprecation warning, 140.41s. Evidence:
tasks/evidence/m0-m1-backend-reviewed.txt. Frontend 46 tests/11 files and
TypeScript/Vite production build passed in this continuation; no frontend code
changed during the review fixes, so those successful gates were not repeated.
Generated transport schemas match with both the original and clean interpreters.
Compilation, scoped diff and complete changed-file whitespace checks pass.

Rebuilt the non-editable wheel after all required fixes and reinstalled it only
in the isolated reproduction environment. Its final smoke ran outside the source
import path, confirmed site-packages loading, seven contracts, owned durable
execution, explicit zero-inspection coverage, persisted events and accepted PDF
export without a model or network call. Evidence: m0-wheel-{build,install}-reviewed.txt,
m0-installed-smoke-reviewed.txt and m0-tamper-rejection.txt. The final installed
environment has no broken dependency requirements.

M0: complete for verified Windows x64/Python 3.11 local execution. Existing final
agent contracts/prompts/schema/budget/permission tests and generated wire contracts
pass; dependency/tooling inventory and a complete reproducible hash lock exist;
clean installs, build and non-editable packaged execution are verified.
M1: complete for the local SQLite/filesystem service. Durable owned idempotent
jobs, immutable snapshots, all five stores, atomic outbox/replay/reconnect,
explicit cancel/resume, graceful and abrupt-process recovery now pass their
integration/regression gates. Required source-review issues are fixed in one pass.
Two minor review notes remain documented above; no extra reviewer was dispatched.

The requested two milestones are complete; this is not a full-project completion
or live-model accuracy claim. M2, remaining M3/M4 integration gates, M5 legacy
removal, M6 quality/security evaluation, M7 IDE clients and optional M8 adapters
remain open in todo.md. Exactly seven AI identities and the final agreed workflow,
tools, budgets, storage boundaries and publishing rules remain unchanged. All
unrelated staged/dirty work and verification artifacts remain intact.

## Remaining milestones continuation (2026-10-14)

User authorizes completing all remaining milestones. Added concrete acceptance
gates in tasks/plan.md; keep M0/M1 evidence and all unrelated dirty/staged work.
Pre-flight: M2 parser/runtime artifacts feed deterministic analysis and graph
context; cache keys must invalidate the former parser-unavailable results. Exact
command definitions are operator-owned, never instructions from inspected source.
Pre-flight: M3 tools must preserve 600s/250k/50k/3/8/12/2-round/2-retry/1-repair
cumulative accounting, scoped private state, evidence gates and deterministic tail.
Pre-flight: metadata capture additions require generated consumer schema parity
before cutover. M5 may remove old modules only after import consumers migrate.
Ruling: optional adapters are implemented as opt-in capabilities, not automatic
connections to external accounts -- the user authorized building, not sending
messages/publishing/deploying -- cost if wrong: live account/platform checks still
depend on supplied configuration and cannot be represented as tested offline.
Ruling: the agreed local trusted-host design supplies threat-model deployment and
trust context -- no new internet-facing or arbitrary-command permission is added
-- cost if wrong: expanding exposure requires a new threat/permission assessment.

M2 implemented: bounded isolated Python/JS/TS parser workers, actual symbols,
calls/import edges, role-specific AST/graph/config/Git tools and versioned cache.
Git metadata is immutable, separately hash-checked and file-scoped; it is explicitly
client-reported rather than causal proof. Config evidence redacts sensitive keys.
Exact operator-owned command IDs run assigned immutable files in disposable scratch
with a clean environment, bounded output/deadline, durable admission and no unknown
completion replay. Windows suspended startup and kill-on-close Job Objects contain
ordinary descendants even after parent exit; this is not a security sandbox.
Owner-granted SQLite tools inspect schema/EXPLAIN in query-only connections.
Measurement artifacts are task-granted, runtime-serialized, atomically replaced
and integrity-checked. Evidence: m2-intelligence-green (20), m2-git-green (20),
m2-artifact-green (7), m2-final-scope-green (12), m2-frontend-green (47), production
frontend build. Full intermediate regression: 413 passed, 3 Windows symlink skips;
later process-tree/integrity fixes have focused green gates, full gate still pending.
Ruling: Tree-sitter callbacks caused a native access violation in the real suite;
use byte-input parsing in a bounded isolated worker -- service survival takes
priority over avoiding process startup -- cost if wrong: extra parser latency.
Parser dependencies are now pinned to tested Windows wheels with SHA256 hashes.

M3 runtime gates: 41 tests passed across iterative agents, cumulative retry limits,
trusted tools, resume and completion-first finalization. Unknown tool completion
now has an explicit failed-coverage reason and cannot initiate automatic retries.
Optional LangSmith metadata export uses the durable Event Store, is disabled by
default, strips prompts/source/tool bodies/identifiers and records export attempts
before network effects; failed/unknown sends do not repeat review work. Unit gates
passed; service integration and final full regression remain pending.

M2/M3 final gate: stable hash-checked 73-package installation and pip check passed.
Full backend: 420 passed, 3 Windows symlink skips, one upstream wrapper warning,
149.31s (m2-m4-backend-final.txt). Service metadata opt-in/default-denial gates:
16 passed (m3-observability-service-green.txt). Both milestones now complete for
the local Windows runtime. No live-provider accuracy is implied by scripted tests.
An earlier full gate overlapped dependency reinstallation and had a transient PDF
worker failure; stable-environment reproduction passed all 11 recovery tests and
the full gate. The process-recovery event expectation now includes the newly
specified transactional budget event; lease/deadline assertions remain intact.

M4 client parity: accounting events refresh the owned ledger during an open SSE
stream with bounded refresh frequency. Watch callbacks/returned models use deep
copies; original scope/key and internal job ownership cannot be changed by callers
(RED -> GREEN, 10 watch tests). Narrow-screen skip-link switches to the review pane
and focuses results (real Chrome RED -> GREEN). Browser capture/reopen/source and
all three exports passed at 320/768/1024/1440 widths with no console errors. Added
owned bounded snapshot-bound tool-evidence viewer; unit gate 49 tests and build
passed, final expanded browser gate still running.

M4 final expanded Chrome gate passed (m4-browser-final.txt), including the actual
owned tool-evidence fetch/view and export/reopen/keyboard/responsive flow. All 49
frontend tests and TypeScript/Vite build pass. Canonical service/CLI/watch/source/
PDF/replay parity is complete; consumers have no old transport imports.
Ruling: a fully rendered checkpoint recovered after a crash keeps its original
accepted immutable report; the persistent job_interrupted event provides recovery
provenance -- rebuilding an already accepted report would change its historical
meaning -- cost if wrong: recovery annotation is in job history, not original PDF.

M5 cutover: before removal, archived 89 legacy/current documentation/source files,
82 removal targets and their available staged Git blobs. Original conftest was
added separately. Every working-tree archive entry was SHA256-verified and ZIP
integrity checked. Removed only inventoried source and derived cache-only legacy
directories with resolved workspace bounds; Git index and unrelated work remain.
Canonical capture constants/public contracts replace old tier/budget aliases.
Library imports no longer load .env; source imports cannot implicitly load local
credentials. The actual SDK transport tests exposed obsolete raw wrappers and
unclosed clients. Replaced wrappers with direct SDK clients, max_retries=0, and
drained cancellation-safe HTTP cleanup (22 focused tests passed).
The RED SDK fixture attempted automatic telemetry with synthetic test input;
network policy blocked it. Canonical tests now disable ambient telemetry, and
product SDK code has no automatic wrapper. Metadata export remains explicit opt-in.
Fresh cutover regression is running; M5 stays open until package/docs/runtime
archive/reference and final regression gates pass.

M5 final gates: stable final backend regression 206 passed in 131.32s with only
the test-imported upstream LangSmith wrapper deprecation warning; frontend 49 and
real Chrome canonical flow passed. Actual SDK delay-cancellation leak reproduced
RED -> GREEN; all clients close/drain before returning, including constructor,
delay, failure and cancellation paths. Removed unused sync/capability/circuit APIs.
Package regression reproduced stale build/lib carrying 18 retired entries into
the wheel. Preserved that generated library privately, rebuilt, and verified no
retired runtime remains in the wheel (m5-package-{red,green}.txt).
Final non-editable wheel: 90,334 bytes, SHA256
6baa572ca72436faeb0d41591716933ceab7771d83eb4fed2e8a90cf2a05cd48.
Installed-wheel smoke outside the source path verified seven identities, durable
owned execution, no model/network calls and an accepted PDF (m5-installed-smoke).
Generated schema freshness and pip check passed. Offline closure generator now
records 69 current dependency wheels, removing four unused legacy packages.
Archived the incompatible 160 MB legacy checkpoint in .devwatch/legacy-archive/
after checking no legacy worker remained; canonical runtime was untouched.
README, env example, public imports and migration inventory now describe only the
canonical runtime. Original test fixture/index blobs and source remain in history.
M5: complete for the verified local Windows package; M6/M7/M8 remain open.
One prior full run exceeded the test helper's 8-second wait in an ownership test;
the exact test reproduced green in 1.38s, and the unchanged-timeout complete rerun
passed. Failure diagnostics now show safe event kinds if this recurs; no deadline,
ownership assertion, production budget or quality threshold was relaxed.

M6 corpus: 60 distinct executable scenarios, 30 defective/30 clean, ten behavior
families across Python and JavaScript. Gold labels and labelled IDs are excluded
from provider inputs. The deterministic fixture provider selects findings only
from actual immutable-source + approved-command evidence, and the combined final
agent rereads references before verification/synthesis. This provider exists only
in the evaluator, not the product runtime. All three evaluation tests passed in
237.57s; reconciled accepted reports yielded 30 TP, 0 FP, 0 FN, precision/recall 1.0,
zero failed jobs. Silent-provider regression correctly yields zero recall; the
fresh label/ID-exclusion tests also pass. Evidence: m6-quality-offline.json.
No live model was called and live_model_accuracy is explicitly null. Full M6
regression and dependency advisory checks are running; M6 remains open until done.
M7 pre-flight: IDEs reuse capture/owned job/replay/source/report contracts through
a small isolated bridge, never another engine. Extended ADR-002 with stdin secret
handling, original-intent recovery and read-only virtual source requirements.

M6: complete for the offline/local quality gate. Full regression 209 passed in
296.57s; confirmed precision/recall 1.0 on 60 independently labelled executable
scenarios. Runtime token/tool/iteration/retry/concurrency/crash/resource gates are
part of that suite. Frontend native audit: zero known advisories. Python audit
found only build-tool advisories (pip24/setuptools79); upgraded isolated tools to
pip26.2.1/setuptools83.0.0, regenerated the same 69-package hash closure from verified
wheels, raised the build backend requirement and rebuilt/installed successfully.
Fresh audit of the corrected lock: zero known advisories (m6-python-audit-fixed).
Retired 20-case/legacy evaluation outputs are preserved privately under the legacy
archive, not kept as contradictory active schemas or falsely labelled live quality.
Live-model accuracy remains unmeasured (null); explicit --live harness exists,
but no paid provider calls or automatic telemetry were used to obtain offline scores.

M7 bridge: real-service capture, exact intent retry, replay/cursor, immutable source
hashes and JSON/PDF passed 10 tests. Source excerpts normalize line separators while
preserving original captured bytes/hash. VS Code controller tests reproduced
missing implementation then passed original-intent/replay/no-implicit-control cases.
Extension compiles and packages as a local VSIX; no publication/installation occurs.
Packaging audit found six high dev-tool issues under vsce3; official vsce4 release
updates the scanner tree and Node baseline. Updated with scripts disabled and tests
passed; fresh extension audit and actual extension-host validation remain pending.

M7 current gates: VS Code local VSIX builds; after the reviewed vsce4 update its
native audit has zero known advisories. Two controller tests and ten Python bridge
tests pass. The installed VS Code host test initially failed before extension load:
its installed SDK directory has incompatible Windows AppContainer ACLs. Preserve
the user's installation/ACLs; test an isolated workspace copy instead. This is an
environment failure, not a passing extension-host gate. JetBrains SDK build and
both IDE runtime gates remain open. Official plugin/virtual-document SDK docs were
checked before implementation; Gradle download is checksum-verified.

2026-10-17: user supplied a new local-side-project milestone sequence and asked to
start at Reliability & Recovery M7, stopping after each milestone. This takes
precedence over the historical IDE M7 and optional infrastructure M8 above.
Preserved the shared dirty workspace and implemented inline without commits.

M7 recovery: one bounded sanitized tool-error receipt now reaches subsequent model
requests and survives explicit resume; successful retrieval clears it. Async
context selection/action deadlines drain work. Resumed tasks clear only their
resolved cancellation marker. Specialist crashes preserve saved/sibling findings
during initial execution and follow-up; storage/SQLite/ownership failures still
fail execution and drain siblings. No new agents, dependencies or public schemas.

M7 verification: existing 42-test baseline passed. Added 19 behavioral cases;
latest milestone/core boundary gate passed all 27 tests in 26.73s. The expanded
113-test recovery gate exposed one storage-failure isolation regression, fixed
without weakening its existing test. Earlier full run: 272 passed, that one
failure, one upstream SDK warning in 429.00s. A fresh full run is in progress on
the corrected code. Details and acceptance matrix: m7-reliability-report.md.
Evidence: evidence/m7-{boundaries,backend,backend-final,recovery-focused}.txt.
Stop after this milestone; Observability & Streaming M8 has not started.

M7 final gate: complete. Fresh full backend regression passed all 281 tests in
498.95s, including the 19 new milestone cases and the unchanged storage-drain
regression. One existing upstream LangSmith SDK wrapper deprecation warning.
Compilation and incremental whitespace checks passed. Reviewed the two runtime
diffs against saved workspace baselines; no dependencies, agent identities,
transport schemas or unrelated user changes were altered. The evidence-backed
report records local limitations and exact failures corrected during development.
No live provider calls, commits, pushes or deployments. Stopped before new M8.

2026-10-17 M8: user requested the next milestone (Observability & Streaming).
Added 14 event kinds and 13 optional bounded metadata fields; actual agent/model/
tool lifecycle, iterations, safe retries, evidence stages, candidates, verification
and finalization/rendering are visible through existing durable replay/SSE/WS.
Normal model completion and its charge now commit together through the existing
Job Store transaction/outbox; pending post-crash calls are recorded as unknown.
`devwatch events JOB_ID --after N --follow` observes without owning execution.
Generated contracts retain old payload compatibility; CLI metadata errors are
sanitized. No new agents, dependencies or services; shared user work preserved.

M8 approval review: rejected the proposed export of hashes of private job/task/
evidence identifiers. That patch was not applied. Implemented the safe alternative:
full correlation remains local; opt-in metadata export includes only allowlisted
classifications and random invocation/call IDs. No live export/provider calls.

M8 gates so far: 21 new backend cases; expanded gate 88 passed in 93.94s before
the last visibility regression; final 38-case boundary gate passed in 72.90s.
Frontend 50 passed, build passed, generated schema freshness/compilation passed.
Normal scripted fixture: 46 events, 5 model calls, 1 tool call, 75 charged tokens.
Full final backend regression is running. See m8-observability-report.md and
evidence/m8-{focused,final-boundaries,backend,backend-final}.txt. Stop before M9.

M8 final gate: complete. Fresh full backend regression passed all 302 tests in
732.03s, including all 21 new observability cases and the real process-kill
recovery assertions. One existing upstream LangSmith SDK wrapper deprecation
warning. Frontend: 50 passed; TypeScript/Vite build passed with existing plugin
deprecation notices. Generated schema freshness, changed Python compilation and
incremental whitespace checks passed. The final visibility regression verifies
that a visible model completion already has its token charge durably committed.
Reviewed runtime diffs against saved workspace baselines; prior user work and
the original seven-agent LangGraph architecture were preserved. No live external
telemetry/provider calls, commits, pushes or deployment. Stopped before M9.
