# 🔍 DevWatch

DevWatch is a local, durable code-review service. It captures source files
immutably, submits a review job to a worker-owned service, and produces
evidence-based JSON, Markdown, or PDF reports.

The project provides:

- A FastAPI service with durable jobs, checkpoints, events, and recovery.
- A seven-agent LangGraph review workflow: one planner, five iterative
  specialists, and a combined verification/synthesis agent.
- A command-line client for reviewing directories, files, and changed Git
  scope.
- A browser client in [`frontend/`](frontend/).
- VS Code and JetBrains integration under [`extensions/`](extensions/).
- Immutable source navigation and bounded tool evidence.

Reviewed source is never modified by the review workflow.

## How DevWatch works

```text
CLI / Browser / IDE
        |
        v
  Snapshot capture
        |
        v
  Durable job service
        |
        v
  Seven-agent review workflow
        |
        v
  Completion and acceptance checks
        |
        v
  Deterministic JSON / Markdown / PDF report
```

The service owns the review workers. A client disconnect, timeout, or
interrupted command does not cancel a submitted job. Jobs can be explicitly
cancelled or resumed.

The default local runtime uses separate SQLite-backed stores:

| Store | Responsibility |
| --- | --- |
| Job Store | Job requests, status, ownership, limits, and recovery state |
| Checkpoint Store | LangGraph workflow checkpoints |
| Repository Cache | Versioned parser and repository intelligence cache |
| Event Store | Ordered, replayable job events |
| Artifact Store | Immutable snapshots, evidence, and generated reports |

The default runtime directory is `.devwatch/runtime/`.

## Requirements

- Windows x64 with Python 3.11 is the verified environment.
- Python 3.11 or newer, as declared in [`pyproject.toml`](pyproject.toml).
- Node.js and npm for the browser client.
- An OpenAI-compatible provider or Gemini-compatible provider.
- A model identifier for each of the `small`, `medium`, and `strong` tiers.

Other operating systems and Python versions may work, but they require their
own installation and regression validation.

## Installation

### Python service and CLI

Create a virtual environment and install the project in editable mode:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
```

For the reproducible Windows dependency set:

```powershell
python -m venv .venv-verified
.venv-verified\Scripts\python.exe -m pip install --require-hashes -r requirements-windows-py311.lock
.venv-verified\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
.venv-verified\Scripts\python.exe -m pip check
```

The hash-locked file is platform-specific. The dependency ranges in
[`pyproject.toml`](pyproject.toml) and [`constraints.txt`](constraints.txt)
remain the source of truth for other environments.

### Browser client

```powershell
cd frontend
npm install
```

## Configuration

Set configuration in the process that starts the service. DevWatch does not
load `.env` files implicitly when imported.

### Required model and provider settings

```powershell
$env:DEVWATCH_MODEL_SMALL = "your-small-model-id"
$env:DEVWATCH_MODEL_MEDIUM = "your-medium-model-id"
$env:DEVWATCH_MODEL_STRONG = "your-strong-model-id"
$env:DEVWATCH_PROVIDER = "openai"
$env:OPENAI_API_KEY = "replace-with-your-provider-key"
$env:DEVWATCH_API_KEY = "replace-with-your-private-service-key"
```

For the Gemini-compatible adapter:

```powershell
$env:DEVWATCH_PROVIDER = "gemini"
$env:GEMINI_API_KEY = "replace-with-your-provider-key"
```

The provider adapter also supports compatible OpenRouter configuration. Use
provider-specific model identifiers; the examples above are placeholders.

### Service settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `DEVWATCH_RUNTIME_DIR` | `.devwatch/runtime` | Root directory for local stores |
| `DEVWATCH_ENV` | `development` | `production` requires an API key |
| `DEVWATCH_SERVICE_URL` | `http://127.0.0.1:8000` | CLI service URL |
| `DEVWATCH_API_KEY` | unset | Client authentication key |
| `DEVWATCH_LANGSMITH_METADATA` | `false` | Opt-in metadata-only telemetry |
| `DEVWATCH_LANGSMITH_PROJECT` | `devwatch-metadata` | Telemetry project name |

When no API key is configured, only loopback clients are accepted. Credentials
are sent through the `X-API-Key` header or a Bearer authorization header, never
in URLs.

## Start the service

Start the canonical service with either command:

```powershell
uvicorn devwatch.review.service:create_app --factory --host 127.0.0.1 --port 8000
```

or:

```powershell
devwatch serve
```

Keep this process running while using the CLI, browser, or IDE clients.

## Use the CLI

Open a second terminal with the same service configuration:

```powershell
# Review the current directory and wait for the report.
devwatch review . --output report.md

# Submit without waiting.
devwatch review . --no-wait

# Inspect a job.
devwatch job JOB_ID

# Replay metadata events, follow activity, or reconnect from a sequence number.
devwatch events JOB_ID
devwatch events JOB_ID --follow
devwatch events JOB_ID --after 120 --follow

# Download a completed report.
devwatch job JOB_ID --report --format json --output report.json
devwatch job JOB_ID --report --format pdf --output report.pdf

# Recover or stop a job explicitly.
devwatch resume JOB_ID
devwatch cancel JOB_ID
```

Use `--service-url` or `DEVWATCH_SERVICE_URL` when the service is not running
at the default address.

Report output files must be new files with the matching `.md`, `.json`, or
`.pdf` extension. Existing files are never overwritten.

### Sharing behavioral constraints

When a captured snapshot includes a contract or requirements document, declare it
as shared context so every review role receives the same constraints:

```sh
devwatch submit SNAPSHOT_ID --idempotency-key REVIEW_KEY --context-file requirements.md
```

Repeat `--context-file` for at most four files, with 6000 UTF-8 bytes of content
combined. Every path must belong to that owned snapshot. The JSON job request and
Python client's `submit` accept the same optional `context_files` list. Preserve
the original context list when retrying an idempotency key; changing it is a new
review intent. Omitted context preserves existing submission behavior.

Declared context is snapshot data pinned in each role's prompt. It grants no tool
permissions, widens no task scope and creates no source-inspection receipt. If it
cannot fit the prompt bounds, the review stops with a context limitation instead
of silently dropping the constraints. Model judgments still require review.

### Debugging a review

`events` prints one JSON event per line, draining paginated history. `--follow`
polls the same durable stream until completion, failure, cancellation or interruption.
`Ctrl+C` disconnects the observer and leaves the job running. The browser uses SSE;
WebSocket and HTTP replay return the same persisted sequence. Reconnect with the
last `sequence` as `--after`; no review is restarted by observation.

Use `agent_id`, `task_id` and the random `run_id` to follow one agent invocation.
`iteration_started` records admitted investigation steps. `model_call_started` /
`model_call_completed` and `tool_called` / `tool_result` share an `operation_id`.
Their completion records include outcome and duration; model records include
attempt, finish classification and token consumption. A provider failure charges
unknown usage conservatively. Crash recovery records pending dispatched calls as
`unknown`; it does not silently replay them. A budget refusal creates no model-call
event, and `agent_completed.stop_reason` explains why the agent stopped.

Evidence moves through `evidence_retrieved`, `evidence_delivered` and
`evidence_inspected`. Delivery/inspection include page offsets; inspection means
the agent acknowledged the delivered page, not proof that its conclusion is correct.
`candidate_submitted` records structured candidates, `finding_created` records
structurally accepted publication, and `candidate_rejected` records quarantine.
`verification_completed` records each verdict. `validation_passed` is explicitly
scoped to the structural gate or final acceptance; rendering and finalization
have separate start/completion records. A verified candidate becomes a final
report only after acceptance, rendering and `job_completed`.

Local events contain bounded identifiers, counts and classifications. They omit
prompts, source, tool arguments/results, model reasoning and raw exception text.
Evidence bodies remain in the separately owned artifact endpoint.

### Cleaning local storage

Stop every service and worker using the runtime before maintenance. Preview the
eligible files, job IDs, row counts and byte totals as local JSON:

```powershell
devwatch cleanup --runtime-dir .devwatch/runtime
```

Inspect the preview, then apply its exact plan ID with the same retention options:

```powershell
devwatch cleanup --runtime-dir .devwatch/runtime --apply --plan-id <plan_id>
```

Any change to selected artifacts, jobs, cache entries or row counts invalidates
the plan. Generate and inspect a new preview before retrying. A service or worker
holding a shared runtime lease blocks cleanup; maintenance blocks startup. The
lease is released by the OS after process death. Do not remove `.maintenance.lock`
or `jobs.sqlite.leases/` lock files.

| Option | Environment variable | Default |
| --- | --- | --- |
| `--terminal-days` | `DEVWATCH_RETENTION_TERMINAL_DAYS` | 30 days |
| `--orphan-days` | `DEVWATCH_RETENTION_ORPHAN_DAYS` | 30 days |
| `--scratch-hours` | `DEVWATCH_RETENTION_SCRATCH_HOURS` | 24 hours |
| `--cache-days` | `DEVWATCH_RETENTION_CACHE_DAYS` | 30 days |

Ages must be finite and positive; command options override environment values.
Terminal age uses the job's last update. Queued, running and interrupted reviews
are retained regardless of age, along with their snapshots, evidence, checkpoints,
reports and measurements. Shared snapshots survive while any retained job needs
them. Scratch copies are disposable and expire by age while workers are stopped.
Orphan snapshots, evidence, reports and measurements use their newest file or
directory modification time. Abandoned runtime temporary files use the scratch
threshold. Cache entries age from their latest successful read/write; legacy
entries receive a full grace period when the cache is first opened after upgrade.

Expired terminal bundles lose job lookup, replay, reports, checkpoints and
idempotency history. Reusing an expired intent can submit a new review. Cleanup
handles only canonical runtime locations and filenames; arbitrary user files,
source checkouts, exported reports, backups and external logs are outside its scope.
Links/junctions/hard links in deletion targets are refused. Use a private local
runtime directory; this is not a sandbox against another process that can modify it.

Cleanup is explicitly invoked, with no background or startup deletion. Run it
periodically between local review sessions. Failed or interrupted maintenance may
be partial: inspect a fresh preview and finish cleanup before restarting workers.
SQLite rows are removed and freed pages are reused on later runs; database files
retain their size high-water mark because cleanup does not run `VACUUM`.

### Reviewing a watch directory

`watch` turns source changes into bounded review submissions:

```powershell
devwatch watch . --interval 1 --debounce 1
devwatch watch . --max-reviews 3
```

The watcher coalesces changes while a job is running. `Ctrl+C` stops the
watcher, not the service-owned job. If a submission has an unknown outcome,
use the printed snapshot ID and idempotency key with `devwatch submit` rather
than recapturing the source.

### Capture behavior

Capture is intentionally bounded and read-only:

- At most 100 files, 500 KB per file, and 10 MB total.
- Sensitive filenames, secret-like extensions, generated files, links, and
  unreadable files are excluded or reported as omissions.
- Git scope uses staged, unstaged, and untracked status paths.
- A single-file or non-Git request captures the eligible source under that
  request.
- Git history, deleted source, and submodule contents are not uploaded.
- A clean Git scope does not make model calls; it produces a coverage report.

## Use the browser client

Start the service, then run the frontend:

```powershell
cd frontend
npm run dev
```

Open the local Vite URL shown in the terminal. The browser defaults to
`http://127.0.0.1:8000` for the service.

The browser can:

1. Connect to a service and keep the API key in memory.
2. Capture an eligible local folder.
3. Submit and monitor a review job.
4. Reconnect to an existing job by ID.
5. Resume or cancel a job explicitly.
6. Navigate immutable source excerpts and evidence.
7. Download deterministic JSON, Markdown, or PDF reports.

To open a Git-scoped review in the browser, submit it from the CLI with
`devwatch review PATH --no-wait`, then use **Open job** in the browser.

## API overview

The service exposes the same contract used by the CLI and clients:

| Endpoint | Purpose |
| --- | --- |
| `POST /api/snapshots` | Store an immutable source snapshot |
| `POST /api/jobs` | Submit a snapshot for review |
| `GET /api/jobs/{job_id}` | Read durable job status |
| `POST /api/jobs/{job_id}/resume` | Resume an interrupted job |
| `POST /api/jobs/{job_id}/cancel` | Request explicit cancellation |
| `GET /api/jobs/{job_id}/snapshot` | Read the immutable file catalog |
| `GET /api/jobs/{job_id}/source` | Read a bounded source excerpt |
| `GET /api/jobs/{job_id}/evidence/{evidence_ref}` | Read owned tool evidence |
| `GET /api/jobs/{job_id}/events` | Replay persisted events |
| `GET /api/jobs/{job_id}/report` | Return JSON, Markdown, or PDF |
| `GET /api/jobs/{job_id}/stream` | Stream events over SSE |
| `GET /api/jobs/{job_id}/ws` | Stream events over WebSocket |

Use an `Idempotency-Key` when submitting a job. Reusing the same snapshot,
scope, and key safely returns the same submission; changing the request is
rejected.

## Trusted tools and database inspection

Commands are disabled unless the operator configures
`DEVWATCH_TRUSTED_TOOLS_FILE`. The file contains exact approved command IDs,
absolute executables, argument lists, source-file assignments, and bounded
timeouts. Reviewed project configuration cannot grant command execution.

Commands run against disposable copies and are bounded at 120 seconds and
200 KB of output. This is trusted-host execution, not a hostile-code security
sandbox.

Optional SQLite inspection requires `DEVWATCH_DATABASE_POLICIES_FILE`. Policies
grant owners access to specific absolute database paths. Connections are
read-only and query-only; model-provided queries cannot modify databases.

Optional LangSmith export is disabled by default. When enabled, only allowlisted
metadata is exported. Source, prompts, arguments, and evidence bodies are not
sent. The local Event Store remains authoritative.
Exported events include phase, iteration, attempt, outcome and random invocation /
call IDs. Job/task/evidence/finding identifiers and fingerprints remain local;
use the local timeline for complete review correlation. No automatic LangGraph
or SDK tracing is enabled, and no external telemetry account is required.

## IDE integrations

### VS Code

The VS Code extension is in [`extensions/vscode/`](extensions/vscode/). It
requires a trusted Python interpreter with DevWatch installed and a running
local service.

```powershell
cd extensions/vscode
npm install
npm test
```

Available commands include:

- **DevWatch: Review Workspace**
- **DevWatch: Open Review Job**
- **DevWatch: Recover Same Submission**
- **DevWatch: Set Service API Key**

### JetBrains

The JetBrains plugin is in [`extensions/jetbrains/`](extensions/jetbrains/).
Use the Gradle wrapper/tasks provided by that extension for local development.

## Development and verification

Run the backend tests:

```powershell
python -m pytest -q
```

Run the complete local runtime scenarios and process-recovery checks:

```powershell
python -m pytest tests/test_m10_runtime.py tests/test_crash_recovery.py -q
```

The runtime matrix creates isolated Git repositories and a real HTTP service on
an ephemeral loopback port. It drives all seven roles through repository capture,
tools, evidence/blackboard handoff, verification, synthesis and JSON/Markdown/PDF
publication. Models return scripted responses; no provider credentials are needed.
Cases cover bounded failures/repair, unavailable tools, context/evidence limits,
budget exhaustion, timeouts, cancellation, specialist isolation and explicit resume.
The service and workers are drained after every case. These checks establish local
runtime behavior; live-agent review quality is evaluated separately.
When overriding `--basetemp` for the full suite, choose a temporary directory
outside this project's Git tree so standalone-directory capture tests keep their
independent scope.

Run the M11 agent evaluator from the repository root:

```powershell
New-Item -ItemType Directory -Force output | Out-Null
python -m scripts.run_agent_evaluation --fixture --output output/evaluation-fixture.json
```

This exercises 12 paired Python/JavaScript samples through individual specialist
subgraphs and the complete workflow. The deliberately narrow scripted provider
only recognizes one bug family; its scores validate the evaluator, not model
accuracy. Independent gold locations, descriptions and match facets never enter
reviewer requests. Defect-specific matching checks the claim, file/line range and
snapshot evidence; duplicates count as false positives. The older 60-case
contract evaluator now also rejects unrelated findings on defective samples.

For an explicitly paid run, configure `DEVWATCH_PROVIDER` and all three
`DEVWATCH_MODEL_SMALL/MEDIUM/STRONG` tiers, plus the provider's existing environment
credential. Supply current per-million-token USD input/output rates for every
model (see [`tasks/m11-pricing.json`](tasks/m11-pricing.json)):

```powershell
python -m scripts.run_agent_evaluation --live --rates tasks/m11-pricing.json --max-cost-usd 2 --output output/evaluation-live.json
```

The cost guard reserves before dispatch, includes unallocated reasoning tokens at
output rates and retains unknown charges. It estimates spending from supplied
prices; provider billing remains authoritative. A provider completion with unknown
usage stops the batch. Each finished case is saved so interrupted runs retain their
observations. Choose a new output filename for every invocation. The cap applies
to that invocation; previous attempts consume the overall authorized budget too.

Results separate individual candidates, accepted report claims, precision/recall,
FP/FN, evidence/localization, duplicates, source inspection, tool outcomes, latency,
provider/ledger tokens and approximate cost. Facet matching is a screening heuristic.
Semantic evidence and causal tool usefulness require manual annotation; severity
accuracy is unavailable because the production finding schema has no severity.
Provider-blocked cases are excluded from quality estimates. Local raw results
include the authored corpus's evidence for inspection, with ambient tracing disabled.

Re-score saved results without model calls:

```powershell
python -m scripts.run_agent_evaluation --rescore results.json --judgments judgments.json --output reviewed.json
```

Judgments map `case_id:mode` to `findings` (zero-based
finding index -> `defect_id` or null, and boolean `evidence_correct`) and optional
`tools` (observed operation ID -> boolean `appropriate` and `necessary`). The
[`M11 report`](tasks/m11-evaluation-report.md) records measurements and limitations.

Run contract export checks:

```powershell
python -m scripts.export_review_contracts --check
```

Run frontend tests and the production build:

```powershell
cd frontend
npm test
npm run build
```

Browser parity verification requires local Chrome and the isolated Playwright
tools:

```powershell
python -m scripts.verify_browser_parity
```

The repository's canonical migration inventory is documented in
[`tasks/migration-inventory.md`](tasks/migration-inventory.md). The focused
legacy cutover tests are [`tests/test_legacy_removal.py`](tests/test_legacy_removal.py)
and [`tests/test_package_cutover.py`](tests/test_package_cutover.py).

## Current limitations

- The verified environment is Windows x64 with Python 3.11.
- The default stores require a local filesystem; distributed/network storage
  adapters are not part of the default service.
- Live-provider accuracy, deployment, and remote publication require separate
  validation.
- A review can finish with partial coverage when an agent fails, a deadline
  expires, or a required capability is unavailable.
- Legacy checkpoints and reports are not imported into the canonical schema.
  Start new snapshots and jobs for the current runtime.

## Project documentation

- [`docs/migration.md`](docs/migration.md) - canonical migration and cutover
  details.
- [`docs/decisions/001-local-job-recovery.md`](docs/decisions/001-local-job-recovery.md)
  - local recovery design.
- [`docs/decisions/002-trusted-tool-runtime.md`](docs/decisions/002-trusted-tool-runtime.md)
  - trusted command execution boundary.
- [`tasks/migration-inventory.md`](tasks/migration-inventory.md) - current
  implementation mapping.
