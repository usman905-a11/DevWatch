# M0 and M1 final combined review

Authority: tasks/seven-agent-design.md and the current two-milestone acceptance
checks in tasks/plan.md. Decisions and tradeoffs: latest M0/M1 section in
tasks/progress.md; docs/decisions/001-local-job-recovery.md.

Scope: devwatch/review/leases.py; the lease, publication and manager lifecycle
additions in jobs.py; runtime crash coverage additions in repository.py/workflow.py;
tests/test_crash_recovery.py and the new remote-cancellation PDF lifecycle test;
requirements-windows-py311.lock and M0/M1 README/inventory/plan/ledger updates.
Earlier core/service/watch/UI/PDF code and unrelated staged/dirty work remain
outside this new review except where needed to verify the changed interfaces.

Review focus: atomic claim/outbox/recovery; process lock identity and lifetime;
no live-worker stealing or overlapping graph/checkpoint/artifact writers;
startup and later process death; queued rescheduling/backpressure and cancelled
waiters; external cancellation and report publication; heartbeat/clock/error
handling and conservative cumulative accounting; retention of intent, snapshot,
unknown reservations, follow-up and private state; owner/replay consistency;
clean-install lock closure/platform/hash claims and wheel packaging; no new AI
identity/tool grant/store, source writes or public wire-schema changes. Judge
complete M0/M1 claims against actual acceptance checks, not just added files.

Evidence: three process cases RED -> GREEN; killed real service checkpoint/usage/
replay integration and explicit crash coverage RED -> GREEN; remote cancellation
publication RED -> GREEN. Existing live-worker exclusion passes. Full clean-env
regression before the publication guard: 398 passed / three Windows symlink skips.
Latest focused publication/recovery gate: 14 passed. Frontend: 46 tests and build
pass; generated schemas match. Second pinned/hash-checked offline installation
passes; packaged-wheel smoke/full final regression follows before completion.

One fresh source-only review under executing-plans. Read files; do not mutate,
execute project/providers/network, install or delegate. Return Critical/Important/
Minor findings with concrete file/line/user effect and declined-to-judge items.
The referenced code-reviewer.md template is unavailable in installed roots;
use installed code-review-and-quality guidance without inventing a template.

Final disposition (2026-10-14): three Important findings reproduced by four
failing cases and fixed in one pass; both Minors and review boundaries are in
progress.md. No re-review. Fresh offline-environment backend gate: 403 passed,
three Windows symlink skips, one upstream SDK warning. Final rebuilt installed
wheel smoke, schema freshness, compilation, diff and whitespace checks pass.
M0 and M1 are complete for Windows x64/Python 3.11 local SQLite execution.
