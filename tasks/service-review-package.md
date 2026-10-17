# Canonical local-service continuation review

Review source only. No external calls, builds, dependency changes or repository
edits. The workspace is dirty; inspect the listed implementations directly rather
than treating the entire user diff as this continuation.

Binding spec: tasks/seven-agent-design.md. Progress/rulings: tasks/progress.md.
Current scope: review/service.py; retry additions in review/subgraphs.py; partial
and deadline recovery in review/workflow.py and review/jobs.py; max_retries=0 in
providers/openai_adapter.py. Tests: test_review_service, test_review_retries,
test_review_partial_failures, test_review_deadline_recovery. Previously implemented
contracts/stores/budgets/repository/finalization are supporting interfaces.

Review focus: authentication identity and ownership across every transport;
credential/source leakage on malformed requests and persisted events; chunked
body/path/cursor bounds; disconnect task cleanup independent of job cancellation;
deadline drain before partial finalization; no model calls or budget reset during
recovery/retry; safe retry classification including quota subclass; authoritative
partial coverage/candidate evidence and completion-before-acceptance/rendering;
graceful restart/resume; no hidden provider retries. Check untested input and
failure branches deliberately, particularly malformed WS auth and persisted
checkpoint provenance. Grade findings by concrete user effect, not spec silence.

Not claimed complete: process-kill leases, live-provider accuracy, JS/TS and
trusted command/profiling tools, CLI/frontend/watch migration, PDF, retention,
all store adapters, optional observability and legacy cleanup. Flag defects in
implemented scope; separately list boundaries declined, with no readiness claim.

Return Critical/Required/Minor findings with exact files/lines, failure scenario
and smallest meaningful regression. One review, one fix pass, no re-review.
