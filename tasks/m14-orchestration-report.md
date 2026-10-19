# M14 - LangGraph Workflow and Orchestration

Date: 2026-10-18. Status: **COMPLETE - engineering and runtime validation**.

## A. Existing implementation

The parent StateGraph already has a deterministic eleven-node path from
repository intelligence through planning, bounded specialists, blackboard,
structural evidence validation and completion. Its specialist node uses a
TaskGroup and job-local semaphore; the executor supplies a shared three-call model
semaphore. Workers use separate invocation/private state and task-keyed SQLite
checkpoints. Results are collected in dispatch order and published by one writer.

The existing completion graph limits follow-up to one admitted existing task,
then runs acceptance and deterministic rendering. Cancellation drains workers and
SQLite writes. Task-local exceptions retain private findings; persistence and
ownership failures abort safely. Existing recovery tests already cover completed
verification and admitted follow-up. M13's 450-test passing baseline and its
PARTIAL live status are preserved as history.

## B. Problems found

| Confirmed boundary gap | Evidence and consequence |
|---|---|
| Duplicate entries in worker dispatch executed twice | A valid Planner normally prevents duplicates, but the worker boundary accepted duplicate task IDs from a supplied/restored task list. A real-store regression observed duplicate provider work. |
| Initial completed-worker checkpoint reuse skipped assignment/generation checks | Changed files, role, initial/follow-up generation, or result owner could be reused without any new investigation. Four red cases demonstrated the missing binding before dispatch/reuse events. |
| Missing internal worker output escaped the task-local failure boundary | A None result reached model_dump in aggregation and aborted the job. Red test reproduced the AttributeError; malformed/foreign results now become explicit specialist_failed coverage. |
| Aggregation published before checking a complete one-to-one task/result join | Missing and duplicate results could be accepted; unknown owners or roles could fail after earlier results had already mutated the blackboard. Five red cases cover incomplete, duplicate, unknown, wrong-role and duplicate-assignment joins. |

These are deterministic orchestration/contract failures, not evidence of improved
model reasoning. M13's live tool/result/provider failures remain separate; M14
does not reclassify them as graph defects or successful investigations.

## C. Changes implemented

Only `devwatch/review/workflow.py` changes production behavior in M14:

- Reject duplicate task IDs before creating worker executions.
- Require an initial worker checkpoint's exact assignment and generation one;
  validate cached result structure and task/role identity before reuse.
- Validate each newly returned worker result inside the existing task-local
  failure handler. Missing or foreign outputs preserve valid siblings and publish
  explicit failure coverage. Checkpoint integrity errors propagate and retain the
  existing sibling-drain behavior.
- Validate every aggregation entry and the complete unique task/result/role join
  before publishing any result. Valid candidates still pass the existing evidence
  gate; invalid candidate siblings remain quarantined rather than aborting a join.

Tests live in `test_m14_orchestration.py` and `test_m14_runtime.py`. The latter
drives real parent/child graphs, stores, tool evidence, verification, acceptance
and rendering, replacing only remote model behavior. One narrowly injected worker
fault and a wrapper around real checkpoint persistence exercise internal failure
and interruption boundaries without swallowing their side effects.

The graph topology, workflow version, seven identities, model/provider choices,
public contracts and dependencies remain the existing implementation. M13's
changes in workflow.py are retained; `evidence/m14-workflow.patch` compares this
milestone against its actual shared-tree starting point.

### Send and reducer decision

I retained the bounded TaskGroup and single aggregation writer. LangGraph
documents [Send and per-key reducers](https://docs.langchain.com/oss/python/langgraph/graph-api)
for dynamic parallel graph branches, and explains that interrupted nodes can run
again from their beginning. Here, dispatch already fans out dynamically inside
one node, and private checkpoints supply task-level reuse. The new runtime tests
demonstrate that reuse, bounded concurrency and deterministic aggregation work
without introducing concurrent writers to the parent results field. Therefore a
Send topology migration and append reducer would add migration/replay obligations
without correcting another demonstrated M14 failure. The existing default
replacement reducer remains appropriate for this single-writer field.

## D. Tests executed

- Corrected dispatch/reuse red gate: **six expected failures**, 2.39s
  (`m14-dispatch-red-corrected.txt`). The first attempt had four fixture-construction
  errors because required coverage was omitted; those test fixtures were repaired
  before production edits. Duplicate dispatch and missing output failed as intended.
- First green plus existing canonical/recovery checks: **12 passed**, 17.84s
  (`m14-dispatch-green.txt`).
- Aggregation red gate: **five expected failures**, 1.15s
  (`m14-aggregation-red.txt`); green plus recovery/candidate/deadline tests:
  **23 passed**, 14.88s (`m14-aggregation-green.txt`).
- Initial runtime gate: 11 passed, one test-fixture timeout. The barrier assumed
  three simultaneous calls while defaults admit one job and conservative
  reservations permitted only two same-role workers. Inspection of persisted jobs
  and model-start events confirmed that admission was behaving correctly. The
  corrected fixture explicitly uses two jobs, two worker slots per job, and the
  unchanged shared three-call model ceiling. Corrected gate: **12 passed**, 32.16s
  (`m14-runtime-fixed.txt`). No production budget or deadline was relaxed.
- Final focused gate: **40 passed**, 75.38s (`m14-focused.txt/.xml`), including all
  **16 new M14 cases** and existing failure-drain, follow-up, deadline recovery,
  candidate preservation and canonical graph tests.
- Generated wire freshness, Python compilation and diff whitespace checks passed
  (`m14-boundaries.json`). M14 changes no wire/frontend source; M13's frontend
  results are historical and are not represented as newly run M14 checks.

The interrupted-worker test waits for actual durable completion of one worker
while its sibling is paused, interrupts the service, then recreates the executor.
Only the unfinished worker and final agent make new model calls after resume;
both findings survive and no failed coverage remains. The concurrency test runs
two jobs with five tasks for the same specialist role each, proves a shared peak
of three active calls, separate current-task state, sorted dispatch, zero pending
reservations and five accepted uncertain findings per job. A separate full-graph
internal-output failure retains the healthy sibling finding through both final
phases, with specialist_failed recorded only for the failed task.

The deterministic matrix completed **24/24** case/mode runs with no failed
coverage (`m14-fixture-results.json`, `m14-fixture-run.txt`). Full-system scripted
scores remain TP=1, FP=0, FN=5, recall 1/6, matching M13's programmed detector.
This demonstrates the unchanged scorer counts misses; it is not a model-quality
improvement.

Full backend: **466 passed**, zero failures/errors/skips, **754.70s**, including
all **16 new M14 cases** and the existing complete five-specialist HTTP/runtime,
crash recovery, repeated follow-up, budget, evidence and rendering checks. The
existing 15-second deadline scenario passed (17.57s total test duration). One
existing LangSmith SDK wrapper deprecation warning remains. Evidence:
[full log](evidence/m14-backend.txt), [JUnit](evidence/m14-backend.xml),
[verification summary](evidence/m14-verification-summary.json). Tests used a fresh
system-temp root outside the checkout, and changed source/test hashes remained
unchanged through the full run.

Self-review checked the M14-only source diff against each acceptance criterion:
assigned specialists receive scoped tasks; parallel workers retain separate state;
valid results survive partial failures; interruption reuses completed work; the
final agent remains reachable; budgets and existing bounded follow-up/recursion
controls terminate work. No required implementation finding remains.

## E. Live evaluation

No new paid-provider calls were made for M14. Its changed behavior is deterministic
and is exercised against the real runtime with scripted model boundaries. The
M13 live sample remains four successful first-response Planner dispatches and
partial downstream investigations. It is not rescored or promoted to successful
live synthesis by this milestone. Native tool calling, model streaming and live
review quality are not established by these orchestration tests.

## F. Resource usage

No M14 provider charges. Budget ceilings, retries, iteration limits, follow-up
admission and timeout policies are unchanged. The two-job test uses a lower
job-local concurrent-call limit of two while preserving the shared limit of three;
it does not raise token ceilings. Cancelled model consumption remains charged
conservatively and no pending reservation survives completed/interrupted jobs.

Test durations measure local runtime execution, not production provider latency.
The deterministic matrix used **181 scripted model calls**, **73 tool calls**,
**2,715 synthetic tokens**, and **81.361s summed job latency**. Scripted tokens
cannot measure model cost savings.

## G. Remaining limitations

The M13 intermittent real-deadline timing behavior remains a known observation;
M14 does not alter its 15-second deadline or claim its cause is fixed. The exact
historical M11 provider causes remain undetermined where raw envelopes were not
retained. Live source-tool recovery, specialist result/stop behavior and verifier
quality remain M15/M16/M20 work.

The added reuse checks cover the initial specialist assignment boundary;
existing follow-up generation/admission and final-candidate reuse checks remain
in place. This is not a comprehensive adversarial checkpoint-store audit or a
new persistence format. The orchestration node may replay on interruption; the
runtime test proves completed task reuse, not exactly-once remote execution after
an unacknowledged network effect. Unknown consumption is charged rather than
silently replayed. Implementation review is self-review, with no independent
reviewer claim.

## H. Milestone status

**COMPLETE for M14's orchestration engineering gates.** Final backend 466 passed,
focused 40 passed, deterministic matrix 24/24 complete, and boundary checks passed.
M13's partial live model-quality status is unchanged; this milestone does not
claim dependable complete live reviews. M15 has not started. No commit, push,
deployment or global configuration change.
