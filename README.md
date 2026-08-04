# DevWatch 🛡️
> **Autonomous Multi-Agent Code Review & Security Hardening Platform**

DevWatch is a production-grade automated code review platform powered by an orchestrated crew of specialized AI agents. It scans codebases, performs AST static analysis, maps dependency context, audits OWASP Top 10 vulnerabilities and logic defects, verifies findings to eliminate false positives, and streams actionable reports to CLI terminals, REST endpoints, and IDE webviews.

---

## 🌟 Key Features

* 🤖 **5-Agent Review Pipeline**:
  1. **Planner Agent**: Scopes target files and maps focus risk areas (`ModelTier.FAST`).
  2. **Security Auditor Agent**: Scans for OWASP Top 10 flaws, injection vectors, and hardcoded secrets (`ModelTier.HEAVY`).
  3. **Quality Auditor Agent**: Detects logic errors, exception swallowing, resource leaks, and concurrency risks (`ModelTier.HEAVY`).
  4. **Verification Agent**: Evaluates candidate findings against code context to drop false positive hallucinations (`ModelTier.FAST`).
  5. **Report Synthesizer Agent**: Aggregates verified findings into structured executive reports with risk verdicts.

* 🛡️ **Security Hardening & Prompt Injection Defense**:
  * Fences all source code in `<untrusted_source_code>` XML tags with explicit prompt boundary directives.
  * Redacts secret keys (`sk-...`, `AKIA...`) as `[REDACTED_SECRET]`.
  * Enforces path traversal sandboxing (`_resolve_safe_path()`) and API Key / CORS domain restrictions.

* 🔍 **AST Analysis & Context Engine**:
  * `ASTStaticAnalyzerTool`: Discovers baseline security and quality defects using Python AST parsing.
  * `ASTCodeChunker`: Chunks large source files on class and function boundaries.
  * `DependencyMapper`: Builds cross-file import caller/callee graphs.

* ⚡ **Fast & Resilient Async Architecture**:
  * Concurrent file analysis fan-out/fan-in using `asyncio.gather()` with `Semaphore(5)` rate limiting.
  * Pydantic v2 structured output schemas with 3-attempt self-correction retries.
  * Disk-backed report storage (`ReportStorage`) in `.devwatch/reports/`.

* ⚡ **FastAPI Backend Server**:
  * REST API: `POST /api/review`, `POST /api/review/file`, `POST /api/review/apply-fix`, `GET /api/reports/{id}`.
  * Real-Time WebSocket Streaming: `/ws/review` emitting live JSON agent progress frames.

* 🖥️ **Developer Workflows**:
  * Typer CLI (`devwatch review ./src`).
  * 1-Click Atomic Quick-Fixes via `/api/review/apply-fix`.

---

## 🚀 Quick Start Guide

### 1. Install Dependencies
```bash
# Install DevWatch in editable mode
pip install -e .
```

### 2. Configure Environment (Optional)
```bash
export OPENAI_API_KEY="your-api-key"
export DEVWATCH_API_KEY="your-server-api-key"        # Optional REST/WS authentication
export DEVWATCH_FAST_MODEL="gpt-4o-mini"               # Model for Planner & Verifier
export DEVWATCH_HEAVY_MODEL="gpt-4o"                   # Model for Security & Quality Auditors
```

### 3. Run FastAPI Backend Server
Run this from the **repository root directory** (`E:\dewatch`):
```bash
# Ensure you are at the project root: cd E:\dewatch
uvicorn devwatch.server:app --reload --port 8000
```

### 4. Run CLI Code Review
```bash
# Review current directory
devwatch review .

# Review specific folder and save report
devwatch review ./devwatch --output report.md
```

---

## 🧪 Testing & Benchmark Evaluation

DevWatch includes a full unit test suite and a baseline evaluation benchmark:

```bash
# Run baseline precision & recall evaluation
pytest tests/test_eval_baseline.py -v

# Run full unit and integration test suite
pytest tests/
```

- **Baseline Benchmark**: 100% Precision, 100% Recall, 1.0 F1 Score ([eval_baseline_results.json](file:///e:/dewatch/tests/eval_baseline_results.json)).
- **Test Suite**: 44 passing unit & integration test cases.

---

## 📐 Architecture Overview

$$\text{Planner} \longrightarrow \begin{pmatrix} \text{Security Auditor} \\ \text{Quality Auditor} \end{pmatrix} \longrightarrow \mathbf{\text{Verification Agent}} \longrightarrow \text{Deduplication} \longrightarrow \text{Synthesizer}$$
