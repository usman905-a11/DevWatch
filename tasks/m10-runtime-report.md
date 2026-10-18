# Milestone 10 - End-to-End Runtime Testing

Date: 2026-10-18. Scope: the attached local side-project M10 after completed M9.
Status: **Complete for the tested local runtime.** Stopped before milestone 11.

## Outcome and architecture

Twenty new cases drive the real local system through isolated Git repository
capture, a real ephemeral loopback HTTP server, the production ReviewClient,
durable submission, LangGraph execution, tools, shared blackboard, verification,
synthesis and accepted JSON/Markdown/PDF publication. Events are read through the
real paginated HTTP endpoint and token accounting through the persisted ledger.

The normal path invokes exactly the existing seven AI identities: Planner, all
five Specialists and the combined Synthesizer/Verifier. Orchestration, blackboard,
evidence/acceptance gates and report rendering retain their responsibilities.
Runtime source, public schemas and dependencies are unchanged. Test helpers have
no production switches; model responses are scripted. Scoped injections remove an
optional handler, raise a specialist-local exception and supply test budget inputs.

## Files and functions

| File / functions | Change |
| --- | --- |
| `tests/runtime_scenarios.py`: `repository` | Five isolated source files in a fresh Git repository, with global Git config/templates disabled for initialization; real bounded capture and explicit captured/changed file sets. |
| `runtime_scenarios.py`: `ScenarioProvider.generate_completion`, `action` | Complete model responses for all roles; malformed/truncated output, paused calls, repeated investigation and inconsistent final drafts; record bounded request metadata for context assertions. |
| `runtime_scenarios.py`: `live_runtime`, `timeline` | Ephemeral loopback Uvicorn service and actual network ReviewClient; proxy-free local transport; bounded startup, shutdown/drain and paginated replay. |
| `tests/test_m10_runtime.py`: normal path and parameterized fault tests | Final report findings/coverage, evidence provenance, all-role execution, format availability, source immutability, ordered events and durable usage; bounded repair/exhaustion and sibling preservation. |
| `test_m10_runtime.py`: admission, oversized evidence, cancellation, restart and deadline tests | Refuse dispatch before budget/context violations; distinguish processed evidence from delivered/inspected pages; drain cancellation, preserve verification/checkpoints and explicitly resume synthesis. |
| `README.md`, `tasks/plan.md`, `todo.md`, `progress.md`, this report | Repeatable commands, acceptance matrix, results, measurements and limits. |

## Acceptance matrix

| Requested scenario | Evidence / expected user-visible behavior |
| --- | --- |
| Normal review | All seven roles execute; all five files inspected; one confirmed `logic.py:2` finding; JSON/Markdown/PDF available after final acceptance; snapshot survives a working-tree edit. |
| Tool failure | A real out-of-range source read fails; a subsequent valid read succeeds; failed tool produces no evidence; sibling verified finding survives with honest failure coverage. |
| Invalid arguments | Unknown source-read arguments are rejected before a tool effect/admission; corrected call succeeds; tool count remains one. |
| Unavailable tools | Remove an optional benchmark handler; real permissioned execution reports unavailable, then permits a bounded alternative read. A separate unapproved-command case correctly stops with `permission_denied`. |
| Malformed output | First malformed response repairs once; persistent malformed output exhausts repair and records `invalid_schema`; other specialists survive. |
| Context limits | A 4,096-token request ceiling prevents any model dispatch and yields a partial report; bounded requests also exercise optional evidence omission at 20,000. |
| Oversized evidence | A 400-function AST remains in an artifact; the default context delivers/acknowledges offset 12,000-13,000. A smaller context omits that artifact page without claiming inspection and still permits a small source excerpt. |
| Truncated output | `finish_reason=length` is charged and stopped as `provider_truncated`, with no silent retry or acceptance of the incomplete response. |
| Budget exhaustion | Investigation stops after eight admitted iterations/tools; a separate one-token job budget prevents all dispatch and produces an explicit partial report. |
| Timeout/cancellation | An accelerated provider timeout drains and conservatively accounts unknown consumption. A real 15-second job deadline drains synthesis and publishes the previously verified finding as partial. Explicit cancellation publishes no report/PDF. |
| Specialist failure | A task-local exception is injected at the specialist execution boundary; sibling work completes, `specialist_failed` persists, and raw error text does not enter the public report/events. |
| Resume/recovery | Stop and restart the real service during synthesis; retain job/snapshot/intent and verification, resume synthesis alone, do not repeat specialist/tool work, and charge the new call cumulatively. Existing actual process-kill recovery cases run in the focused gate and full suite. |
| Finalization repair | A schema-valid draft drops a recorded non-rejected finding. Consistency validation rejects it, permits one repair, or preserves confirmed findings in a partial report after repair exhaustion. |

Parameterized fault cases check for unconsumed reservations, paired model-call
events, durable charges, preserved verified work, correct failure coverage and
unchanged source bytes. Explicit cancellation checks the service returns HTTP 409
for a report and that no PDF artifact/render completion was published.

## Tests and metrics

Commands use the existing virtual environment. The focused matrix uses fresh owned
directories under `output/m10-owned/`, with child TEMP/TMP on E:. This avoided the
full C: volume encountered in the first session. On resume C: had free space again;
the final full-suite run uses a fresh system-temp root outside the project's Git
tree. No user's runtime or repository was cleaned.

| Verification | Result |
| --- | --- |
| New cases collected | 20 |
| Focused runtime + process-crash + workflow/deadline recovery | **33 passed in 184.48s**, including all 20 new cases; `tasks/evidence/m10-focused-final.txt`. |
| Capture-test location diagnosis | Both failures reproduced inside the project, then **2 passed in 0.22s** in an external temp root; `m10-capture-location-{red,green}.txt`. |
| Full backend regression | **371 passed in 758.30s**, with one existing upstream LangSmith wrapper deprecation warning; `tasks/evidence/m10-backend-final.txt`. JUnit XML confirms 371 tests, zero failures/errors/skips, including all 20 new cases. |
| Generated review contract freshness | Passed: `scripts/export_review_contracts.py --check`. |
| Changed test module compilation | Passed: `compileall -q tests/runtime_scenarios.py tests/test_m10_runtime.py`. |
| Incremental whitespace checks | Passed. |

Normal scripted fixture: **15 model calls, 7 tool calls, 132 events and 225 charged
scripted tokens**, with one verifier-backed confirmed finding and all seven roles.
A corrected read or structured response adds one call (240 tokens); repeated
investigation reaches 21 calls/315 tokens; an isolated specialist crash leaves
13 calls/195 tokens. Provider timeout charges the reservation conservatively
rather than treating unknown usage as zero. These are harness/accounting metrics,
not live-model quality, price, latency or accuracy measurements.
The 13 logged scenario measurements are also saved in
`tasks/evidence/m10-runtime-metrics.json`; machine-readable full results are in
`tasks/evidence/m10-backend.xml`.

## Review, corrections and remaining limits

Initial failures were test-fixture expectations, not confirmed runtime bugs:

- A fixture under the ignored project output directory inherited the parent Git
  scope and captured an empty source set. Initializing its own repository fixed
  isolation; the helper now checks all expected source and changed paths.
- An unapproved command correctly triggered policy denial, so the missing-handler
  scenario and policy-denial scenario were separated.
- Context compaction correctly withheld an oversized AST page. The test now checks
  that omitted data receives no delivery/inspection receipts, while a source
  excerpt can still be inspected.
- Windows text reads normalized captured CRLF. Immutability now compares original
  encoded bytes, so it detects actual writes without mistaking newline conversion.

The interrupted focused run had no terminal result and was rerun using a fresh
owned test root; the final focused result above is from that completed run.

The first full-suite attempt also placed its temporary root under the ignored
project output tree. That incorrectly switched two existing standalone-directory
tests into parent-Git capture: `test_directory_catalog_stops_consuming_at_limit_even_for_excluded_entries`
and `test_unreadable_directory_is_reported_without_raw_os_error`. The attempt was
stopped and its partial output preserved as `m10-backend-inrepo-aborted.txt`.
Both failures were reproduced narrowly and disappeared when only the temporary
root moved outside the repository. Final full verification uses that corrected
location. The earlier attempt has no complete suite result and is not a success.

Review checks include real network/SQLite/artifact effects, independent literal
expected findings and usage, fault isolation, bounded retries, no false inspection,
no early publication, shutdown/drain and replay across service restarts. Production
changes were unnecessary for the exercised contracts.

This is deterministic runtime validation with scripted models. Live agent accuracy,
representative defect evaluation, pricing and provider-specific behavior belong to
M11. Platform execution here is Windows/Python 3.11; Unix still needs its own gate.
The new cases use loopback HTTP; browser UI behavior and live external services were
not exercised. Existing frontend files and schemas were not changed. No production
data deletion, external export, live provider call, project commit, push or deployment.
