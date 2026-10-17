# ADR-002: Permissioned tools operate on immutable snapshots and exact trusted commands

Status: accepted for the agreed local review service. Date: 2026-10-14.

The source/model boundary is untrusted. The reviewed repository can contain code,
configuration and prompt-like text, but cannot choose host executables, argv,
environment variables, credentials, output destinations or tool grants. Agent
contracts in review/contracts.py authorize tools before review/subgraphs.py
admits their cumulative budget. review/stores.py owns immutable source and scratch;
review/service.py authenticates ownership. These are the evidence anchors for the
runtime boundary; optional remote adapters introduce no default network authority.

Operator-owned definitions select exact executable/argv and permitted tool/task
scope. Runtime calls use only definition IDs. Execution occurs in a fresh scratch
copy, with stripped environment, bounded output, clipped deadlines and process-tree
termination/drain before cancellation returns. Commands are not blindly replayed
after an unknown completion. Generated artifacts stay in the Artifact Store and
cannot publish reports. The host runner is explicitly not a security sandbox.

Assets are source confidentiality/integrity, provider credentials, review evidence,
job accounting and host compute. Principal abuse paths are source-driven command
injection (deny dynamic argv/shell and untrusted definitions), source/credential
exfiltration (scoped reads, environment stripping and output redaction), stale
evidence/replayed effects (snapshot-bound evidence and persisted admission), and
resource exhaustion (existing file/token/tool/iteration/time/output bounds).

Execution is disabled until explicitly configured by the operator. Real local
fixtures verify execution/lifecycle; no untrusted project script or remote account
is invoked merely to finish this implementation. Internet exposure, multi-host
execution and protection against trusted code acting maliciously are outside this
host adapter's contract and need a separate deployment decision.

The IDE adapter boundary uses the same authenticated job service. The developer
selects a trusted workspace and explicitly invokes capture/submit/control/export.
An installed Python bridge runs with `-I` outside the reviewed directory, accepts
bounded typed stdin JSON and emits bounded JSON/metadata only. Credentials travel
over stdin, never command arguments, source files, logs or workspace settings.
Original snapshot/scope/idempotency intent is persisted before submission; unknown
outcomes require explicit recovery with that intent. Closing an IDE viewer only
stops observation. Immutable source opens as a read-only virtual document; generated
report exports require a user-selected artifact destination. No IDE path permits
model-selected host commands, source edits, automatic resume or remote publication.
