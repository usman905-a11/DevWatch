# Seven-agent migration inventory

The target design is [seven-agent-design.md](seven-agent-design.md). This inventory
records migration dependencies; the old components listed here are not architecture
to retain. Do not remove them before replacement behavior and consumers are tested.

## Runtime and verification environment

- Python requires 3.11 or newer because the existing command configuration reader
  imports standard-library `tomllib`. `pyproject.toml` now matches that requirement.
- Test tooling is declared as the `test` extra: pytest, pytest-asyncio and HTTPX.
  Reproduction command: `python -m pip install -e ".[test]" -c constraints.txt`.
  No dependency installation or upgrade was performed during this slice.
- The workspace `.venv` lacks pytest. Verification used the already installed
  Python 3.11 interpreter returned by `python`, with existing dependencies.
  M0 now also verifies two clean Windows x64/Python 3.11 environments under
  ignored `.tools/`: one declared-extra resolution and one offline hash-checked
  reproduction. `requirements-windows-py311.lock` records the complete runtime,
  test and build-tool closure; other platforms need separate verification.
- Existing pinned LangGraph/checkpoint families are in `constraints.txt`.
  New foundation modules use the existing LangGraph/Pydantic/SQLite stack.
- Tree-sitter is absent from the inspected interpreter. Python/JS/TS intelligence
  adapters and their dependency/lock updates remain M2 work.
- LangSmith remains installed by the existing dependency graph. New graph entry
  points explicitly disable automatic tracing even in an enabled ambient context.
  The optional metadata-only adapter and dependency classification remain migration
  work. Never enable raw LangGraph/provider tracing as that adapter.
- Existing frontend uses npm, its package lock, TypeScript, Vite and Vitest.
  No frontend packages were changed. Current plugin/Vite deprecation warnings
  remain visible in verification logs.

## Replacement and removal map

| Existing component | Replacement / migration gate | Removal gate |
|---|---|---|
| `review/models.py`, public legacy issue/report models | Canonical contracts in `review/contracts.py`; explicit job/report/source transport schemas | M4 consumer migration, then M5 |
| `review/engine.py`, `pipeline/dag.py`, legacy adapter/facade nodes | One canonical LangGraph workflow using job/store/contracts and iterative subgraphs | Root graph + all CLI/REST/streaming parity, then M5 |
| `review/agents.py`, `agents/planner.py`, `quality.py`, `security.py`, standalone `verifier.py` and `synthesizer.py` | Seven contract identities; Planner + five specialist subgraphs + combined two-phase final agent | Model-backed graph parity, then M5 |
| `agents/registry.py`, old route/model tier logic and context facades | Deterministic router/context/budget components, no added AI identities | M3/M4 migration, then M5 |
| `review/state.py`, old task/reducer/checkpoint schemas | Versioned canonical private states and shared blackboard; separate Checkpoints | Archive incompatible checkpoints before M5 |
| `review/evidence.py`, `review/runner.py`, old static confirmation rules | Immutable snapshot/cache intelligence, structural gate, permissioned tools, explicitly trusted exact commands in scratch | M2/M3 evidence/command tests, then M5 |
| `review/reporting.py`, JSON report storage and report lookup helpers | Structured report draft after completion, final acceptance, deterministic renderers, Artifact Store | M4 reports/exports/ownership parity, then M5 |
| `routers/review.py`, `routers/ws.py`, `operations/review_operations.py`, server client-owned tasks | Durable Job Manager + common owner-scoped REST/SSE/WS event history | M1/M4 replay/reconnect/cancel/resume parity, then M5 |
| `routers/fs.py` and frontend live-source reads | Immutable snapshot source reads bound to job ownership | M4 source navigation parity, then M5 |
| Old mutation `410` handlers | No mutation API in the target service | M4 client migration, then M5 |
| CLI pipeline calls (removed) and frontend old result/progress types | CLI now uses canonical job/report APIs; frontend migration remains | CLI behavior tests pass; remaining M4 transport/UI regression, then M5 |
| Duplicate env/config aliases, scanner/agent/model budgets, default tracing wrappers | Single Balanced policy and explicit small/medium/strong settings; metadata-only opt-in tracing | M3/M4 configuration migration, then M5 |
| Tests tied to compatibility/single-call/old wire schemas | Port behavioral assertions to canonical jobs/tools/graphs/reports before deleting old tests | M5 cleanup, followed by full M6 regression |
| Unused dependencies/configs/API/UI after replacement | Import/reference and lockfile inventory after cutover | M5 cleanup; M6 dependency and build verification |

## Current cutover status

The canonical core now runs Planner, selected iterative specialists, the shared
blackboard/structural evidence gate and the combined two-phase final agent through
the completion-first report tail. Durable jobs invoke it directly in integration
tests. Python AST facts, scoped source/search tools, evidence artifacts and
SQLite graph/private checkpoints are connected; graceful interruption/resume
preserves verification and follow-up admission.

The canonical FastAPI factory (`devwatch.review.service:create_app`) now invokes
the durable graph for snapshot/job submission, ownership, reports/source/evidence,
SSE/WS persistent replay and explicit cancel/resume. Classified retries and
mandatory-agent/deadline partial recovery are connected. This service is runnable
directly; the CLI now consumes it without importing the old pipeline. Local capture
selects Git status scope, uploads immutable source and client-reported omissions;
job/status/resume/cancel and deterministic JSON/Markdown download are connected.
The obsolete pipeline-mocked CLI test was replaced after the real API integration
tests passed. The legacy server remains pending the remaining backend consumer gates.
The browser transport foundation in `frontend/src/review/` now consumes canonical
jobs, manifests, reports, immutable source and authenticated SSE replay directly.
Its validation schemas are generated from backend contracts; offline fixtures from
the real ASGI graph/stores test wire parity. The frontend now uses canonical jobs,
snapshot source, persisted events and separate report groups. Real Chrome/ASGI
checks pass local capture, viewer detach/reopen, source and JSON/Markdown exports.
After these gates, obsolete frontend APIs/socket/types/hook/panel/editor/source
helpers and their schema-specific tests were archived as non-executable history
and removed. Git jobs are opened by CLI job ID; browser capture reviews whole files.
JS/TS parser adapters and trusted command/measurement tools remain open. M1 local
process-kill recovery now uses process-held execution locks and persisted Job Store
leases; orphaned jobs become interrupted, queued jobs restart, and explicit resume
retains checkpoints/intent/counters and charges unresolved usage/crash time. Live
workers are not stolen on heartbeat expiry. Canonical CLI watch uses bounded capture, stable source versions,
one active job and one latest pending capture. It preserves exact unknown-submission
intents, requires explicit interrupted-job recovery, reports directory deletions
and exits without cancelling submitted jobs. No previous watcher module/command
or external watcher dependency existed to retain/remove. Deterministic PDF rendering now runs after
acceptance for normal and partial/deadline finalization. Owned, bounded, hash-checked
PDFs live in the Artifact Store; job/checkpoint results hold their references.
Service, CLI and browser exports use those saved bytes. Backend legacy removal follows
successful consumer cutover and regression checks, according to the agreed rule.
