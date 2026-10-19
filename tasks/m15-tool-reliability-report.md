# M15 - Tool Infrastructure Reliability

Date: 2026-10-19. Status: **COMPLETE - engineering and deterministic runtime gates**.

## A. Existing implementation

The existing seven custom LangGraph roles already used permission-filtered tool
catalogues, immutable owner-bound snapshots, scoped evidence pages, exact approved
commands and read-only owner-granted SQLite inspection. Delivery and explicit
inspection acknowledgments were separate receipts. Tool/iteration/token limits,
durable checkpoints and unknown-command completion guards already existed.
M13's provider/context fixes and M14's single-writer orchestration are preserved.

## B. Problems found

- Invalid source starts and evidence offsets returned generic errors without
  usable bounds. Direct source-handler type errors could escape classification;
  empty captured files could not be read honestly.
- The graph gave the model only a two-field generic receipt. Identical failed
  calls could run again; checkpoint restart did not retain a failed-call guard.
- Pending-action checkpoints could retain arbitrary invalid argument values.
  Recoverable read errors and ambiguous command failures shared one classification.
- Most tools shared fallback descriptions. File schema checks did not normalize
  all file-based tools or enforce assignment before custom handlers; non-finite
  query bindings could reach SQLite.
- SQLite and configuration decoding exceptions lacked safe actionable guidance.
  Corrupt context evidence could be attributed to model failure. Content-addressed
  malformed evidence could raise TypeError/KeyError instead of an integrity error.
- Pydantic result-schema failures after a real command effect could be mistaken
  for correctable model arguments. The new real-command regression observed a
  second model request; post-dispatch schema failures now stop immediately.

## C. Changes implemented

`tool_errors.py` supplies bounded structured diagnostics: tool, stable code, static
hint, recoverability, safe argument snapshot and allowlisted numeric details.
Unknown fields and free text (SQL, bindings, symbols, capability IDs) are redacted;
exception strings and dependency error messages never become model feedback.
An internal SHA-256 identity normalizes valid arguments including defaults. Only
the private checkpoint retains this identity; public events contain metadata.

`repository.py` reports actual line/page bounds; empty files yield empty evidence
without invented source locations. EOF clamping remains. Missing, malformed or
tampered evidence and changed source receive controlled classifications. Parser
and configuration errors guide source/search fallback. SQLite failures provide
safe schema/SELECT guidance without executing a query or disclosing query values.

`subgraphs.py` retains the legacy error receipt and adds one active diagnostic to
the next prompt. A new model action may correct a recoverable request within the
existing limits. An identical failed action stops before another handler call or
tool charge. Eight private diagnostics survive checkpoint restart/follow-up;
success clears active guidance, retaining history. Permission, integrity, timeout,
unknown completion and ambiguous command failures stop. Sanitized checkpoint
actions are diagnostic records; existing restart logic never replays them.
Admission schema errors are correctable; schema errors after dispatch are terminal
execution/result failures because effects may already have occurred.

`tool_catalogue.py` validates finite arguments and repository-relative assigned
paths before effects. Every one of 24 tool names has a dedicated description;
database descriptions match the installed argument/runtime mode. Tool availability
continues to depend on the existing role and registered capabilities.

| Tools audited | Actual contract and evidence boundary |
|---|---|
| read_source | Assigned immutable path, inclusive bounded lines, EOF clamp; honest empty evidence |
| read_evidence | Scoped verified reference, bounded character page, next_offset and explicit inspection acknowledgment |
| repo_map | Assigned captured metadata only |
| code_search | Literal bounded query, optional assigned path, 20 bounded matches |
| parse_ast, symbol_lookup | Parsed scoped facts; exact optional symbol; explicit source fallback when unavailable |
| call_graph | Syntactic call sites, not proven runtime dispatch |
| dependency_graph, import_graph | Local import edges in task scope and unresolved edges |
| complexity | Syntactic lower bound, not a quality verdict |
| config_read | Captured JSON/TOML, sensitive-key redaction, safe decoder location |
| git_diff, git_history | Captured client-reported metadata, not causal proof |
| run_tests, run_command, lint, type_check, coverage, sast | Exact approved host command in assigned scratch files; bounded output/status, no model argv/shell |
| profile, benchmark | Exact approved workload, scoped measurement, existing capability grant |
| db_analyze, query_analyze | Exact approved command or owner-granted read-only SQLite table/column metadata or EXPLAIN; installed schema advertises the selected mode |
| write_artifact | Explicit measurement grant and runtime-owned destination; no arbitrary writes |

The scoped security review checks model-action admission, owner/snapshot binding,
evidence integrity, diagnostic privacy, and replay after uncertain effects. No
dependencies, public stop reasons, wire contracts, graph topology or resource
ceilings change. Dynamic filtering and specialist reasoning redesign remain M17
and M16 respectively.

The SDK/full-graph check reproduced a second context issue: at 20,000 tokens,
corrected source was processed but trimmed before delivery to preserve an 8,192
response reservation. After dropping optional metadata, non-Planner requests now
fit response output to remaining headroom (at least 512) before discarding evidence
pages. Schemas, acknowledgments and cumulative ceilings remain authoritative.
The previous M10 assertion that AST pages must be omitted at 20,000 is replaced
with a positive assertion of the requested page's inspected offset in both windows.
A separate graph case sizes the context from the real mandatory role/schema bytes
and verifies that a page that still cannot fit receives no delivery/inspection
receipts. Existing runtime tests retain explicit failure when mandatory fields
cannot fit. An initial fixed 13,500-token test stopped at Planner admission, so it
was replaced by this role-scoped check instead of changing Planner budgets.

## D. Tests executed

Failing-first evidence is retained under `tasks/evidence/`: source errors (8
failures), recovery (6 failures), boundary enforcement (7 failures), query/context
classification (5 failures) and malformed evidence shape (2 failures, 1 already
passing). Corrected focused gates passed 37, 55, 39 and 68 tests at successive
slices. One restart test initially raised cancellation directly inside a graph
node; the harness now cancels the actual paused invocation after persistence.
No production timeout or failure expectation was weakened.

Broader focused gate: **81 passed, 1 failed**, 216.97s. The new SDK test reproduced
source processing without delivery at 20,000 tokens. After the reservation fix,
15 context/SDK/execution checks passed; only the old assertion requiring AST
omission failed as expected under the new behavior. Corrected positive/negative
context and real execution gate: **7 passed**, 34.32s (`m15-context-accepted.txt`).
Full backend: **526 passed**, zero failures/errors/skips, **822.71s**
(`m15-backend.txt/.xml`). All 36 new M15 cases and the unchanged M13/M14 checks
pass. The 15-second job-deadline scenario passes (17.794s total test duration,
including setup/cleanup); no deadline was relaxed. One existing upstream LangSmith
wrapper deprecation warning remains. Tests used a fresh system-temp directory
outside the checkout. All source/test hashes match before and after the full run
(`m15-backend-run.json`, `m15-verification-hashes-before/after.json`).

Final replay review added a failing-first post-effect schema case: **1 failed,
1 passed**, 1.20s (`m15-result-schema-red.txt`). Full regression was interrupted
early for final wording/classification edits and then rerun against final frozen
hashes; interrupted runs are not counted as successful verification.

Final focused gate: **87 passed**, 52.08s (`m15-final-focused.txt`), including all
**36 new M15 cases**, existing argument/permission/privacy/restart checks and the
SDK-to-report path. Both 20,000- and 32,768-token corrected reads are delivered and
acknowledged. A page that cannot fit is omitted without fabricated receipts.

Generated wire-contract freshness, Python compilation and diff whitespace checks
pass (`m15-boundaries.json`). Public wire/frontend source is unchanged; no fresh
frontend run is represented by this milestone. Review across correctness,
readability, architecture, scoped security and resource behavior has no remaining
required implementation finding (`m15-review.json`). The complete tool inventory
and M15-only production patch are retained beside these checks.

Deterministic matrix: **24/24** case/mode runs completed, zero failed coverage or
excluded runs (`m15-fixture-results.json`). Full-system scripted scores remain
TP=1, FP=0, FN=5, recall 1/6, matching the programmed reviewer. This is an honest
miss-counting check, not improved model accuracy. Consolidated results:
[verification summary](evidence/m15-verification-summary.json),
[backend log](evidence/m15-backend.txt), [JUnit](evidence/m15-backend.xml),
[review](evidence/m15-review.json), [production diff](evidence/m15-production.patch),
[tool inventory](evidence/m15-tool-inventory-after.json).

## E. Live evaluation

No paid provider calls are made for M15. HTTP MockTransport replaces the remote
response while the actual SDK, stores, tool execution, graph, evidence inspection,
verification, acceptance and report rendering run locally. These checks establish
runtime correction behavior, not a new live-model accuracy result. M13's approved
five-fixture live result remains historical evidence.

## F. Resource usage

M15 provider cost: US$0. Conservative cumulative Gemini charges remain
US$0.76974150 of the original US$1 cap; US$0.23025850 remains. Failed tool calls
already dispatched retain their charge; blocked duplicates consume no second tool
call. Invalid arguments consume no handler effects. All iterations and corrective
model requests retain cumulative accounting. Histories are bounded to eight and
only the latest active diagnostic is added to model context.

The deterministic matrix used **181 scripted model calls**, **73 tool calls**,
**2,715 synthetic tokens** and **78.121s summed job latency**. These counters are
local fixture measurements, not provider pricing or live latency estimates.

## G. Remaining limitations

Free-text and capability values are intentionally redacted in durable diagnostics;
coordinates, scoped paths, field names, structured codes and private identities
support diagnosis without copying sensitive input. Recovering a call retains its
historical `task:tool` failed-call coverage receipt. Successful correction does not
erase that event or imply the whole task failed.

Approved commands remain trusted host processes in scratch directories, not a
hostile-code sandbox. Parser/search evidence remains structural; measurement and
caller-contract interpretation still require verification. Existing delivery and
inspection receipts prove which pages were acknowledged, not semantic reading or
causal correctness. No broader model quality guarantee is inferred. The historical
15-second runtime test's timing sensitivity remains recorded in earlier reports.

## H. Next milestone

Stop after M15. M16 will address specialist investigation goals, evidence needs,
stopping conditions and reasoning quality when requested.
