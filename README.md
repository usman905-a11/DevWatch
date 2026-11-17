# 🔍 DevWatch

DevWatch is a local, durable multi-agent code-review service and web IDE. It opens a local workspace folder read-only, runs a seven-agent LangGraph review workflow in a worker-owned FastAPI service, persists checkpoints and replayable events in SQLite, and produces deterministic **JSON** and **Markdown** reports.

The project provides:

- A FastAPI service ([`devwatch/review/service.py`](devwatch/review/service.py)) with durable jobs, checkpoints, SSE/WebSocket event streams, and crash recovery.
- A seven-agent LangGraph workflow: one `planner`, five parallel specialists (`architecture_security`, `bug_reliability`, `logic_correctness`, `quality_testability`, `performance_scalability`), and one `synthesizer_verifier`.
- A React + Monaco web IDE in [`frontend/`](frontend/) with lazy folder browsing, live review activity tracking, source click-through, and report exports.
- Bounded AST/tree-sitter repository intelligence and immutable evidence tracking.
- IDE extension packages under [`extensions/`](extensions/).

Reviewed workspace source files are never modified by the review workflow.

## How DevWatch works

```text
Browser Web IDE (React + Monaco) / API Client
        |
        v
  Local Workspace (/workspace, /fs/*) or Snapshot (/api/snapshots)
        |
        v
  Durable FastAPI Job Service (POST /api/jobs)
        |
        v
  Seven-Agent LangGraph Workflow
    [planner] -> 5 parallel specialists -> [synthesizer_verifier]
        |
        v
  Deterministic JSON / Markdown Report
```

The backend service owns all worker execution. Closing a browser tab or disconnecting a client stream does not cancel a running review job; jobs can be reopened, resumed, or explicitly cancelled.

Local state is stored in two SQLite files under `.devwatch/runtime/` (configurable via `DEVWATCH_RUNTIME_DIR`):

| File | Contents |
| --- | --- |
| `devwatch.sqlite` | Jobs, events, workspace/snapshot manifests, cached AST intelligence, evidence receipts, and finalized reports |
| `checkpoints.sqlite` | LangGraph workflow checkpoints for resume and crash recovery |

## Requirements

- Windows x64 with Python 3.11+ (verified on Python 3.11, per [`pyproject.toml`](pyproject.toml))
- Node.js and npm for the web IDE in [`frontend/`](frontend/)
- An OpenAI-compatible, Gemini, or OpenRouter API key

## Installation

### Backend

Create a virtual environment and install in editable mode:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
```

For the hash-locked Windows Python 3.11 dependency set:

```powershell
python -m venv .venv-verified
.venv-verified\Scripts\python.exe -m pip install --require-hashes -r requirements-windows-py311.lock
.venv-verified\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
.venv-verified\Scripts\python.exe -m pip check
```

Dependency ranges in [`pyproject.toml`](pyproject.toml) and [`constraints.txt`](constraints.txt) remain the source of truth across platforms.

### Frontend

```powershell
cd frontend
npm install
```

## Configuration

Copy [`.env.example`](.env.example) to `.env` (or export variables in your shell). Library imports do not auto-load `.env`, so pass `--env-file .env` when starting `uvicorn`.

### Provider & model environment variables

**Gemini (`gemini` adapter):**

```env
DEVWATCH_PROVIDER=gemini
GEMINI_API_KEY=replace-with-your-gemini-key
DEVWATCH_MODEL=gemini-3.8-flash
# Optional tier overrides (default to DEVWATCH_MODEL / LLM_MODEL):
# DEVWATCH_MODEL_SMALL=gemini-3.8-flash
# DEVWATCH_MODEL_MEDIUM=gemini-3.8-flash
# DEVWATCH_MODEL_STRONG=gemini-3.8-flash
```

**OpenAI / OpenRouter:**

```env
DEVWATCH_PROVIDER=openai
OPENAI_API_KEY=replace-with-your-provider-key
# Or OPENROUTER_API_KEY=replace-with-your-openrouter-key
DEVWATCH_MODEL=replace-with-supported-model-id
```

Model tier resolution checks `DEVWATCH_MODEL` first, then tier-specific variables (`DEVWATCH_MODEL_SMALL` / `DEVWATCH_FAST_MODEL`, `DEVWATCH_MODEL_MEDIUM`, `DEVWATCH_MODEL_STRONG` / `DEVWATCH_HEAVY_MODEL`), and falls back to `LLM_MODEL`.

### Service settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `DEVWATCH_RUNTIME_DIR` | `.devwatch/runtime` | Root directory for SQLite runtime stores |
| `DEVWATCH_ENV` | `development` | Set to `production` to require `DEVWATCH_API_KEY` |
| `DEVWATCH_API_KEY` | unset | Optional client auth key (`X-API-Key` or `Authorization: Bearer`) |
| `DEVWATCH_SSL_VERIFY` | `true` | Set to `false`/`0` only if testing behind a custom TLS proxy |

When `DEVWATCH_API_KEY` is unset in `development` mode, only loopback clients (`127.0.0.1`, `::1`, `localhost`) are accepted.

## Running DevWatch

### 1. Start the backend service

```powershell
e:\dewatch\.venv\Scripts\python.exe -m uvicorn devwatch.review.service:create_app --factory --host 127.0.0.1 --port 8000 --env-file .env
```

Add `--reload` if you want automatic reloads when editing backend Python files.

### 2. Start the frontend web IDE

In a second terminal:

```powershell
cd frontend
npm run dev
```

Open the local Vite URL printed in the terminal (default API target is `http://127.0.0.1:8000`).

### Using the Web IDE

1. **Connect (if using an API key):** If `DEVWATCH_API_KEY` is set in `.env`, expand **Service connection**, paste the key, and click **Connect**. (Leave `DEVWATCH_API_KEY` unset in `development` mode for unauthenticated localhost access.)
2. **Open a workspace folder** via **Open local folder** or **Set workspace** (pasting a path with or without surrounding quotes works). Directories expand lazily and large workspaces skip heavy build/dependency folders cleanly without hanging.
3. **Browse and view source** directly in the Monaco code viewer.
4. **Run review** to start a seven-agent job against the active workspace and watch live planner/specialist/verifier progress over SSE.
5. **Click through findings** to jump directly to the referenced file and line range in Monaco.
6. **Reopen, resume, or cancel** existing jobs by Job ID.
7. **Export reports** as deterministic **JSON** or **Markdown**.

## API Overview

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Service health check and workflow version (`seven-agent-v1`) |
| `GET /workspace` | Get active local workspace path |
| `POST /workspace` | Set active workspace root path |
| `POST /workspace/pick` | Open native OS folder picker and set workspace |
| `GET /fs/list?path=...` | Lazy directory listing under active workspace |
| `GET /fs/read?path=...` | Bounded source file read from active workspace |
| `POST /api/snapshots` | Capture an explicit immutable source snapshot |
| `POST /api/jobs` | Submit a review job (`workspace_path` or `snapshot_id`, requires `Idempotency-Key` header) |
| `GET /api/jobs/{job_id}` | Read durable job status, limits, and token ledger |
| `POST /api/jobs/{job_id}/resume` | Resume an interrupted job |
| `POST /api/jobs/{job_id}/cancel` | Cancel a queued or running job |
| `GET /api/jobs/{job_id}/snapshot` | Read file manifest for a job |
| `GET /api/jobs/{job_id}/source` | Read bounded line range from job source |
| `GET /api/jobs/{job_id}/evidence/{evidence_ref}` | Read immutable tool evidence excerpt |
| `GET /api/jobs/{job_id}/events` | Replay persisted job events (`after` cursor) |
| `GET /api/jobs/{job_id}/report?format=json\|markdown` | Download finalized JSON or Markdown report |
| `GET /api/jobs/{job_id}/stream` | Stream job events over SSE |
| `GET /api/jobs/{job_id}/ws` | Stream job events over WebSocket |

`POST /api/jobs` also accepts optional `context_files` (up to 4 workspace files, max 6,000 UTF-8 bytes combined) to pin shared behavioral constraints into agent prompts, and optional `changed_files` to scope the review.

## Runtime Limits & Verification Policy

- Default `BalancedLimits` ([`devwatch/review/contracts.py`](devwatch/review/contracts.py)):
  - `review_seconds`: `600` (10-minute wall-clock limit per job)
  - `provider_timeout_seconds`: `90` (configurable up to `120`)
  - `job_tokens`: `None` (uncapped by default; pass an explicit integer limit in `BalancedLimits` if a per-job token ceiling is desired)
  - `model_context_tokens`: `131072`
  - `iterations_per_task`: `8`, `tool_calls_per_task`: `12`, `concurrent_model_calls`: `3`
- Under the independent-support publication policy, candidates without an independently computed finite-domain arithmetic proof remain in `uncertain_high_impact_candidates` rather than `confirmed_defects`, even when specialists and verifier agree.

## Development and Verification

### Backend tests

```powershell
e:\dewatch\.venv\Scripts\python.exe -m pytest -q
```

If overriding `--basetemp` on Windows, place the directory outside the repository root so standalone-directory tests retain an isolated workspace scope.

### API schema & TypeScript types

Verify [`frontend/src/review/api-types.ts`](frontend/src/review/api-types.ts) matches backend Pydantic/FastAPI schemas (or omit `--check` to regenerate):

```powershell
e:\dewatch\.venv\Scripts\python.exe scripts/generate_api_types.py --check
```

### Frontend typecheck, build & tests

```powershell
cd frontend
npx tsc --noEmit
npm run build
npm test -- --run
```

### Chrome browser E2E smoke test

Requires Chrome/Playwright installed in `.venv`:

```powershell
e:\dewatch\.venv\Scripts\python.exe -m scripts.verify_browser_parity
```

### Live Gemini / seeded repo baseline scan

Runs a live scan against [`tests/fixtures/seeded_repo/`](tests/fixtures/seeded_repo/) using credentials in `.env` and reports recall/precision against [`manifest.json`](tests/fixtures/seeded_repo/manifest.json):

```powershell
e:\dewatch\.venv\Scripts\python.exe scripts/run_seeded_scan.py
```

### Evaluation corpus runner

Run fixture evaluation with scripted responses (no API calls):

```powershell
New-Item -ItemType Directory -Force output | Out-Null
e:\dewatch\.venv\Scripts\python.exe -m scripts.run_agent_evaluation --fixture --output output/evaluation-fixture.json
```

For a paid live corpus run using [`tasks/m11-pricing.json`](tasks/m11-pricing.json):

```powershell
e:\dewatch\.venv\Scripts\python.exe -m scripts.run_agent_evaluation --live --rates tasks/m11-pricing.json --max-cost-usd 2 --output output/evaluation-live.json
```

## IDE Integrations

Experimental extension sources are located under [`extensions/vscode/`](extensions/vscode/) and [`extensions/jetbrains/`](extensions/jetbrains/). Note that the VS Code extension tests (`cd extensions/vscode && npm install && npm test`) and JetBrains Gradle build target the `/api/jobs` HTTP service and should be updated alongside any client contract changes.

## Project Documentation

- [`docs/migration.md`](docs/migration.md) - canonical migration and cutover notes.
- [`docs/decisions/001-local-job-recovery.md`](docs/decisions/001-local-job-recovery.md) - local recovery architecture.
- [`tasks/migration-inventory.md`](tasks/migration-inventory.md) - current implementation mapping.
