# Canonical watch continuation review

Authority: tasks/seven-agent-design.md; implementation: tasks/plan.md;
ledger: tasks/progress.md, canonical watch continuation rulings.
Scope: new devwatch/review/watch.py, CLI watch command/imports, new
tests/test_watch_reviews.py and three watch CLI tests in test_durable_cli.py,
README/watch inventory/todo/ledger documentation. Unrelated dirty/staged prior
work and the already-reviewed core/service/browser/PDF slices are outside scope.

Review focus: deterministic debouncing/hash/scope/coverage; latest-version coalescing,
backpressure and duplicate/revert handling; capture provenance, omissions/deletion
tracking across limits and scope changes; memory/time/input bounds; selected root
and link continuity; unknown accepted POST and original printed intent; callbacks/
exceptions and stale state; interruption, Ctrl+C, max-review exit and independent
durable execution; status transitions; no automatic retry/resume/cancel, no local
model/report engine; unchanged seven roles/tools/budgets/gates/stores/SSE/WS.

Verification: seven RED->GREEN core/CLI cases; Ctrl+C and actual graceful server
interruption pass; NaN polling interval RED->GREEN before submission. 19 focused
tests pass using actual capture, API/stores/graph and scripted providers; full
backend regression underway. No watcher dependency, prior watcher or compatibility
adapter. Polling can miss transient edits; exact rule and operator costs in ledger.

One final source-only review under executing-plans, then one required RED->GREEN
fix pass. Do not edit, execute project/tests/providers/network, install or delegate.
Report Critical/Important/Minor with exact file/line and practical user effect;
include declined-to-judge items. Referenced reviewer template is unavailable under
global roots; use installed code-review-and-quality checklist without inventing it.

Post-review disposition (2026-10-13): both Important deletion findings were
reproduced failing and fixed in one pass; 21 focused tests pass. Mutable callback
payloads remain a deferred Minor because the current CLI callbacks only print.
Review limits and rulings are recorded in progress.md; no re-review requested.
Fresh full backend regression after the fix pass: 393 passed, three existing
Windows symlink skips, one upstream SDK warning. Contract freshness, compilation,
CLI help, scoped diff and whitespace checks also pass.
