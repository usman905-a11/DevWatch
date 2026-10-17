# DevWatch

DevWatch reviews changed code and produces reports. It does not apply fixes to reviewed files. The review engine collects Git changes, selects nearby context, runs bounded static analysis and optional configured commands in a disposable copy, sends relevant work to LangGraph specialists, verifies evidence, and renders confirmed findings plus manual-review candidates.

## Install and run

From the repository root:

```powershell
python -m pip install -e .
$env:GROQ_API_KEY = "replace-with-your-key"
$env:DEVWATCH_RUN_COMMANDS = "false"
devwatch review .
uvicorn devwatch.server:app --port 8000
```

The provider adapter also accepts `OPENROUTER_API_KEY` or `OPENAI_API_KEY`. Set `DEVWATCH_API_KEY` when protecting the HTTP API; production mode (`DEVWATCH_ENV=production`) refuses to start without it. `DEVWATCH_WORKSPACE_DIR` limits which local paths the API can read. The CLI's `--output` option explicitly writes a Markdown report to the path supplied by the operator.

For a frontend development session, run `npm install` and `npm run dev` in `frontend/`. The app expects the API at `http://localhost:8000`.

## Review interfaces

- CLI: `devwatch review <directory>` or `devwatch review <directory> --output report.md`.
- REST: `POST /api/review` with `{"target_path":"."}`; `POST /api/review/file` and `POST /api/review/files` accept uploaded source; `GET /api/reports/{report_id}` retrieves stored repository reports.
- WebSocket: `/ws/review` accepts `{"target_path":"."}`, sends `agent_update` frames and a final `review_completion` with `report_id`, or `review_error`. A disconnected client cancels its review.
- Retired mutation endpoints (`/api/review/propose-fix`, `/api/review/apply-proposal`, `/api/review/apply-fix`, and `/api/fs/write`) remain discoverable and return HTTP 410. They do not change files.

Repository reviews use staged, unstaged, and untracked Git changes. For a non-Git directory, DevWatch reviews its eligible files. A clean Git tree produces an explanatory empty report. The strict gate requires source evidence and verification before a finding is confirmed. Uncertain high-impact findings appear separately for manual review. If a stage fails, the report records the failure and may be partial.

## Limits and command containment

The main settings are listed in [`.env.example`](.env.example). Defaults in `devwatch/config.py` include 100 review files, 1,000 snapshot files, 10 MB of scanner input, 100 MB per snapshot, 1,000 candidate findings, 10 concurrent LLM calls, 250,000 job tokens, and a 120-second review deadline. The command runner caps each command at 120 seconds and 200,000 captured output bytes; `DEVWATCH_RUN_COMMANDS=false` disables commands.

When commands are enabled, DevWatch discovers supported test commands or reads exact argv entries from `.devwatch.toml`. It rejects shells, inline Python, package installation, path traversal, and executables inside the reviewed workspace. Commands run with secret-like environment variables removed and within a disposable source snapshot. This is containment for accidental effects, not a security boundary for hostile code. Disable commands when reviewing untrusted repositories.

## Generated data and retention

| Data | Default location | Lifecycle |
|---|---|---|
| Source snapshots and uploaded-file artifacts | `.devwatch/runs/{job_id}/` | The engine prunes expired run directories when a new engine starts; default retention is 7 days (`DEVWATCH_ARTIFACT_RETENTION_DAYS`). A resume requires its run directory to remain. |
| LangGraph checkpoints | `.devwatch/checkpoints.sqlite` | Durable across restarts. No automatic row pruning occurs. Stop reviews before deleting the database and its SQLite sidecar files; doing so removes all resume state. |
| Stored REST/WebSocket repository reports | `.devwatch/reports/{report_id}.json` | Persist until an operator removes them. Report lookup stops working after deletion. |

Keep `.devwatch/` private: artifacts and reports can contain source code, and checkpoints contain review metadata. Back up or purge these locations under your own retention policy. Never remove an active run directory or SQLite database during a review.

## Verification

```powershell
python -m pytest -q
python -m pytest tests/test_m5_acceptance.py -q -s
cd frontend
npm test
npm run build
```

The versioned offline evaluation uses 20 changed-file cases and scores confirmed findings from a real Git-change review without a live provider. It measures the deterministic path; live-model accuracy depends on the configured provider and is not established by that offline gate.
