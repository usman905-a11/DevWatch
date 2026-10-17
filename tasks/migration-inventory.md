# Canonical migration inventory

The binding architecture is [seven-agent-design.md](seven-agent-design.md).
Historical inventories are archived and do not describe retained runtime code.

The package now contains one canonical FastAPI/durable-job/LangGraph implementation.
CLI and browser use the same owned job, snapshot/source, evidence, event and report
API. Seven contracts define Planner, five iterative specialists and the combined
Verification/Synthesis agent. Deterministic components own routing, context,
budgets, evidence/completion/acceptance and report rendering.

| Responsibility | Implementation |
|---|---|
| Public service and owned transports | review/service.py |
| Jobs, leases, outbox and persistent events | review/jobs.py, leases.py |
| Five storage responsibilities and immutable snapshots | review/stores.py, workflow.py checkpoints |
| Python/JS/TS intelligence/cache | review/intelligence.py, intelligence_worker.py, repository.py |
| Permissioned trusted commands, measurement and DB tools | review/tool_runtime.py, windows_process_job.py, database_tools.py |
| Iterative seven-agent orchestration and gates | review/contracts.py, subgraphs.py, workflow.py, finalization.py |
| Deterministic reports/PDF | review/finalization.py, pdf.py, pdf_worker.py, _pdf_document.py |
| CLI capture/watch | cli.py, review/capture.py, client.py, watch.py |
| Browser jobs/source/events/reports | frontend/src/review/ |
| Optional metadata-only LangSmith | review/observability.py; disabled by default |

Legacy engines, standalone agent roles, routers, schemas/prompts, scanners,
facades, old storage, rate/retry managers and their configuration aliases are
removed. Source/index snapshots are in the non-executable backend archive.
Legacy checkpoints are preserved privately under .devwatch/legacy-archive/;
canonical runtime files are untouched. See [migration coverage](../docs/migration.md).

Windows x64/Python 3.11 is the verified runtime. The offline SHA256 wheel lock
now contains only the current project/test/build dependency closure (69 packages).
Parser packages are real installed Python/JS/TS grammars. GitPython, implicit
python-dotenv loading and the deprecated Typer all extra are removed as direct
requirements. LangGraph brings the LangSmith SDK; telemetry activation is optional.
Other platforms and live providers/accounts have separate verification gates.

M5 package/reference/regression gates are tracked in todo.md and progress.md.
M6 quality evaluation, M7 IDE clients and M8 optional storage/integration adapters
remain separate milestone gates; they are not inferred from core completion.
