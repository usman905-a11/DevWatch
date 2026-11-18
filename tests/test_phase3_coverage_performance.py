"""Phase 3 TDD suite: coverage metrics, import-graph prioritization, AST cache, client pooling, and execution modes."""

import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.config import Config
from backend.providers.base import LLMRequest, LLMResponse, LLMUsage
from backend.providers.openai_adapter import OpenAIProviderAdapter
from backend.review.budgets import BudgetManager
from backend.review.contracts import AgentId, AgentPrivateState, AgentWorkItem, ModelTier, ReviewTask
from backend.review.jobs import DurableJobManager, JobRecord, JobStore
from backend.review.repository import RepositoryContext
from backend.review.service import ServiceSettings, create_app
from backend.review.stores import ArtifactStore, StoreLayout
from backend.review.workflow import CanonicalReviewExecutor, _ReviewSession
from backend.review.workspace import build_workspace_manifest
from tests.test_control_agents import MODELS
from tests.verification_fixtures import reviewed


def test_coverage_metrics_track_discovered_eligible_excluded_limits_and_assigned_files(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "dist").mkdir()
    (repo / "dist" / "bundle.js").write_text("console.log(1);\n", encoding="utf-8")
    (repo / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (repo / "huge.py").write_text("x = 1\n" * 100, encoding="utf-8")
    (repo / "asset.bin").write_bytes(b"\x00\x01\x02\x03")
    (repo / "entry.py").write_text("def f(x):\n    return x[0]\n", encoding="utf-8")
    (repo / "helper.py").write_text("def g():\n    return 1\n", encoding="utf-8")
    (repo / "extra.py").write_text("def h():\n    return 2\n", encoding="utf-8")

    manifest = build_workspace_manifest(repo, max_file_bytes=200)
    cc = manifest.capture_coverage
    assert cc.discovered_count == 7
    assert cc.excluded_by_reason["ignored"] == 1
    assert cc.excluded_by_reason["excluded_secret"] == 1
    assert cc.excluded_by_reason["too_large"] == 1
    assert cc.excluded_by_reason["binary"] == 1
    assert sorted(manifest.entries) == ["entry.py", "extra.py", "helper.py"]

    class ScopedProvider:
        async def generate_completion(self, request):
            data = json.loads(request.prompt)
            role = data["task"]["agent_id"]
            phase = data["phase"]
            pages = data["selected_context"].get("evidence", [])
            refs = [p["evidence_ref"] for p in pages]
            if role == "planner":
                action = {
                    "kind": "submit_plan",
                    "payload": {
                        "selected_agents": ["logic_correctness"],
                        "priority_files": ["entry.py", "helper.py"],
                        "priority_symbols": [],
                        "risk_areas": ["indexing"],
                        "review_tasks": [
                            {
                                "task_id": "logic-1",
                                "agent_id": "logic_correctness",
                                "files": ["entry.py", "helper.py"],
                                "focus": "Check entry and helper",
                            }
                        ],
                        "review_strategy": "Focus on entry and helper",
                        "coverage_expectations": ["entry.py", "helper.py"],
                    },
                }
            elif role == "logic_correctness":
                if not data["private_state"]["evidence_refs"]:
                    action = {"kind": "call_tool", "tool": "read_file", "arguments": {"file_path": "entry.py", "additional_files": ["helper.py"]}}
                else:
                    action = {
                        "kind": "submit_candidates",
                        "payload": {"task_id": "logic-1", "agent_id": role, "candidates": [], "coverage": {}, "stop_reason": "evidence_complete"},
                    }
            elif phase == "verification":
                action = {"kind": "submit_verification", "payload": {"decisions": []}}
            else:
                action = {"kind": "submit_synthesis", "payload": {"summary": "Clean", "limitations": []}}
            action["inspected_evidence"] = refs
            return LLMResponse(
                finish_reason="stop",
                content=json.dumps(action),
                provider="scripted",
                model=request.model,
                latency_ms=0,
                usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )

    import asyncio

    async def run():
        layout = StoreLayout(tmp_path / "runtime")
        artifacts = ArtifactStore(layout.app_db)
        jobs = JobStore(layout.app_db)
        # Capture pre-built manifest files simulating bounded workspace scan limits:
        snap = artifacts.capture(
            owner="alice",
            files={path: (repo / path).read_text(encoding="utf-8") for path in sorted(manifest.entries)},
            capture_coverage=cc,
        )
        executor = CanonicalReviewExecutor(layout, artifacts, jobs, ScopedProvider(), models=MODELS)
        manager = DurableJobManager(jobs, executor)
        try:
            job = await manager.submit(owner="alice", request={"snapshot_id": snap.snapshot_id}, idempotency_key="p3-cov")
            done = await manager.wait(job.job_id, owner="alice")
        finally:
            await manager.close()
        report = json.loads(done.result["json"])
        metrics = report["coverage"]["metrics"]
        assert metrics["total_discovered"] == 7
        assert metrics["eligible"] == 3
        assert metrics["excluded"] >= 4
        assert metrics["assigned"] == 2
        assert metrics["inspected"] == 2
        assert metrics["skipped_limits"] >= 1
        assert metrics["failed"] == 0
        assert "Coverage metrics:" in done.result["markdown"]

    asyncio.run(run())


def test_large_repo_prioritizes_import_hubs_and_surfaces_max_files_limitation(tmp_path):
    repo = tmp_path / "large_repo"
    repo.mkdir()
    (repo / "z_hub_auth.py").write_text("def check_token(tok):\n    return bool(tok)\n", encoding="utf-8")
    for i in range(110):
        content = "from z_hub_auth import check_token\ndef run():\n    return check_token('x')\n" if i < 15 else "def leaf():\n    return 1\n"
        (repo / f"mod_{i:03d}.py").write_text(content, encoding="utf-8")

    manifest = build_workspace_manifest(repo)
    assert any(str(Config.MAX_FILES_PER_REVIEW) in note for note in manifest.capture_coverage.limitations)

    layout = StoreLayout(tmp_path / "runtime")
    artifacts = ArtifactStore(layout.app_db)
    jobs = JobStore(layout.app_db)
    ctx = RepositoryContext(artifacts, owner="local", workspace_root=repo)
    executor = CanonicalReviewExecutor(layout, artifacts, jobs, provider=object(), models=MODELS)
    job = JobRecord(job_id="b" * 32, owner="local", status="queued", request={"workspace_path": str(repo)}, created_at=1, updated_at=1)
    session = _ReviewSession(executor, job, ctx, BudgetManager(), sorted(ctx.manifest.entries))

    planner_work = AgentWorkItem(task_id="__planner", agent_id=AgentId.PLANNER, files=sorted(ctx.manifest.entries), focus="Plan")
    planner_ctx = session.context({"task": planner_work, "private_state": AgentPrivateState(), "action": None})
    assert "import_graph" in planner_ctx
    assert planner_ctx["import_graph"]["hub_files"][0] == "z_hub_auth.py"
    assert planner_ctx["changes"].index("z_hub_auth.py") < 10

    sec_work = ReviewTask(task_id="sec-1", agent_id=AgentId.ARCHITECTURE_SECURITY, files=["z_hub_auth.py", "mod_000.py"], focus="Sec")
    sec_task_ctx = session.context({
        "task": sec_work,
        "private_state": AgentPrivateState(),
        "action": None,
    })
    assert "import_graph" in sec_task_ctx
    assert any(edge["to"] == "z_hub_auth.py" for edge in sec_task_ctx["import_graph"]["edges"])


def test_ast_cache_persists_in_repo_cache_sqlite_and_avoids_respawning_workers(tmp_path, monkeypatch):
    from backend.review import intelligence

    parse_calls = []
    orig_analyze = intelligence.analyze_source

    def tracked_analyze(path, source):
        if path.endswith(".py"):
            parse_calls.append(path)
        return orig_analyze(path, source)

    monkeypatch.setattr("backend.review.repository.analyze_source", tracked_analyze)

    layout = StoreLayout(tmp_path / "runtime")
    artifacts = ArtifactStore(layout.app_db)
    snap1 = artifacts.capture(
        owner="alice",
        files={
            "main.py": "from helper import dbl\ndef run(x):\n    return dbl(x)\n",
            "helper.py": "def dbl(x):\n    return x * 2\n",
        },
    )
    first_facts = RepositoryContext(artifacts, snap1.snapshot_id, owner="alice").analyze()
    assert sorted(parse_calls) == ["helper.py", "main.py"]
    assert layout.repo_cache_db.exists()

    # Re-analyzing identical content hits SQLite repo-cache with 0 worker calls.
    parse_calls.clear()
    second_facts = RepositoryContext(artifacts, snap1.snapshot_id, owner="alice").analyze()
    assert second_facts == first_facts
    assert parse_calls == []

    # Updating only main.py misses cache ONLY for main.py; helper.py still hits cache.
    snap2 = artifacts.capture(
        owner="alice",
        files={
            "main.py": "from helper import dbl\ndef run(x):\n    return dbl(x) + 1\n",
            "helper.py": "def dbl(x):\n    return x * 2\n",
        },
    )
    parse_calls.clear()
    third_facts = RepositoryContext(artifacts, snap2.snapshot_id, owner="alice").analyze()
    assert parse_calls == ["main.py"]
    assert third_facts["helper.py"] == first_facts["helper.py"]


def test_openai_adapter_pools_client_and_defaults_to_zero_request_delay(monkeypatch):
    monkeypatch.delenv("DEVWATCH_REQUEST_DELAY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    adapter = OpenAIProviderAdapter(provider_name="openai")
    assert adapter.request_delay == 0.0

    monkeypatch.setenv("DEVWATCH_REQUEST_DELAY", "0.25")
    configured = OpenAIProviderAdapter(provider_name="openai")
    assert configured.request_delay == 0.25

    import asyncio
    import openai

    seen_http_clients = []

    class FakeCompletions:
        async def create(self, **kwargs):
            return SimpleNamespace(
                id="cmp-1",
                choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="{}", refusal=None))],
                usage=SimpleNamespace(prompt_tokens=5, completion_tokens=5, total_tokens=10),
            )

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            seen_http_clients.append(kwargs["http_client"])
            self.chat = SimpleNamespace(completions=FakeCompletions())
            self._http = kwargs["http_client"]

        async def close(self):
            await self._http.aclose()

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeAsyncOpenAI)

    async def scenario():
        pool_adapter = OpenAIProviderAdapter(provider_name="openai")
        r1 = await pool_adapter.generate_completion(LLMRequest(prompt="one", model="gpt-4o-mini"))
        r2 = await pool_adapter.generate_completion(LLMRequest(prompt="two", model="gpt-4o-mini"))
        assert r1.usage.total_tokens == 10 and r2.usage.total_tokens == 10
        assert len(seen_http_clients) == 2
        assert seen_http_clients[0] is seen_http_clients[1]
        assert not seen_http_clients[0].is_closed
        await pool_adapter.aclose()
        assert seen_http_clients[0].is_closed

    asyncio.run(scenario())


def test_job_request_accepts_execution_mode_and_job_tokens_cap(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def ok():\n    return 1\n", encoding="utf-8")

    class StaticProvider:
        async def generate_completion(self, request):
            data = json.loads(request.prompt)
            role = data["task"]["agent_id"]
            if role == "planner":
                action = {
                    "kind": "submit_plan",
                    "payload": {
                        "selected_agents": [],
                        "priority_files": [],
                        "priority_symbols": [],
                        "risk_areas": [],
                        "review_tasks": [],
                        "review_strategy": "Quick check",
                        "coverage_expectations": [],
                    },
                }
            elif data["phase"] == "verification":
                action = {"kind": "submit_verification", "payload": {"decisions": []}}
            else:
                action = {"kind": "submit_synthesis", "payload": {"summary": "Empty", "limitations": []}}
            return LLMResponse(
                finish_reason="stop",
                content=json.dumps(action),
                provider="scripted",
                model=request.model,
                latency_ms=0,
                usage=LLMUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

    app = create_app(
        settings=ServiceSettings(runtime_root=tmp_path / "runtime", models={t: t.value for t in ModelTier}),
        provider=StaticProvider(),
    )
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        seq = client.post(
            "/api/jobs",
            headers={"Idempotency-Key": "mode-seq"},
            json={"workspace_path": str(repo), "execution_mode": "sequential", "job_tokens": 50000},
        )
        assert seq.status_code == 202
        seq_body = seq.json()
        assert seq_body["limits"]["concurrent_model_calls"] == 1
        assert seq_body["limits"]["job_tokens"] == 50000

        bal = client.post(
            "/api/jobs",
            headers={"Idempotency-Key": "mode-bal"},
            json={"workspace_path": str(repo), "execution_mode": "balanced"},
        )
        assert bal.status_code == 202
        assert bal.json()["limits"]["concurrent_model_calls"] == 2

        par = client.post(
            "/api/jobs",
            headers={"Idempotency-Key": "mode-par"},
            json={"workspace_path": str(repo), "execution_mode": "parallel"},
        )
        assert par.status_code == 202
        assert par.json()["limits"]["concurrent_model_calls"] == 3
