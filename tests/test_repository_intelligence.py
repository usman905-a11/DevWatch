"""Language facts and scoped graph tools operate on real immutable snapshots."""
import asyncio
import json

import pytest

from devwatch.review.contracts import AgentAction, AgentId, AgentWorkItem, ReviewTask
from devwatch.review.repository import RepositoryContext
from devwatch.review.stores import ArtifactStore, RepoCache


def repository(tmp_path):
    artifacts = ArtifactStore(tmp_path / "artifacts")
    snapshot = artifacts.capture(owner="alice", files={
        "main.py": "from helper import double\ndef result(x):\n    return double(x)\n",
        "helper.py": "def double(x):\n    return x * 2\n",
        "index.ts": "import { double } from './helper';\nexport const result = (x: number): number => double(x);\n",
        "helper.ts": "export function double(x: number) { return x * 2; }\n",
        "view.tsx": "export function View() { return <div>result</div>; }\n",
        "broken.js": "function broken( {",
        "config.json": '{"debug":true,"api_key":"SECRET-SENTINEL"}',
    })
    return RepositoryContext(artifacts, RepoCache(tmp_path / "cache.sqlite"), snapshot.snapshot_id, owner="alice")


def test_real_javascript_typescript_tsx_ast_and_parse_failures(tmp_path):
    repo = repository(tmp_path)
    facts = repo.analyze()
    assert facts["index.ts"]["status"] == "parsed"
    assert {symbol["name"] for symbol in facts["index.ts"]["symbols"]} == {"result"}
    assert facts["index.ts"]["imports"] == ["./helper"]
    assert facts["index.ts"]["calls"][0]["target"] == "double"
    assert facts["view.tsx"]["symbols"][0]["name"] == "View"
    assert facts["broken.js"]["status"] == "parse_failed"
    reopened = RepositoryContext(repo.artifacts, repo.cache, repo.snapshot_id, owner="alice")
    assert reopened.analyze() == facts


def test_dependency_import_and_call_tools_have_distinct_scoped_outputs(tmp_path):
    repo = repository(tmp_path)
    work = AgentWorkItem(task_id="graphs", agent_id=AgentId.SYNTHESIZER_VERIFIER,
        files=["main.py", "helper.py"], focus="Resolve calls")
    async def scenario():
        tools = repo.tools()
        dependency = await tools.execute(work, AgentAction(kind="call_tool", tool="dependency_graph", arguments={"file_path": "main.py"}))
        data = repo.evidence(dependency.evidence_ref)
        assert data["tool"] == "dependency_graph"
        assert data["data"]["edges"] == [{"from": "main.py", "to": "helper.py", "import": "helper"}]
        assert set(data["source_scope"]) == {"main.py", "helper.py"}
        calls = await tools.execute(work, AgentAction(kind="call_tool", tool="call_graph", arguments={"file_path": "main.py"}))
        assert repo.evidence(calls.evidence_ref)["data"]["calls"][0]["caller"] == "result"
        symbol = await tools.execute(work, AgentAction(kind="call_tool", tool="symbol_lookup", arguments={"file_path": "helper.py", "symbol": "double"}))
        assert repo.evidence(symbol.evidence_ref)["data"] == [{"name": "double", "start_line": 1, "end_line": 2}]
        narrow = work.model_copy(update={"files": ["main.py"]})
        scoped = await tools.execute(narrow, AgentAction(kind="call_tool", tool="dependency_graph", arguments={"file_path": "main.py"}))
        assert repo.evidence(scoped.evidence_ref)["data"]["edges"] == []
        assert "helper.py" not in repo.evidence(scoped.evidence_ref)["source_scope"]
    asyncio.run(scenario())


def test_static_quality_security_and_config_tools_are_honest_and_redacted(tmp_path):
    repo = repository(tmp_path)
    async def scenario():
        security = ReviewTask(task_id="security", agent_id=AgentId.ARCHITECTURE_SECURITY, files=["config.json"], focus="Inspect config")
        config = await repo.tools().execute(security, AgentAction(kind="call_tool", tool="config_read", arguments={"file_path": "config.json"}))
        serialized = json.dumps(repo.evidence(config.evidence_ref))
        assert "SECRET-SENTINEL" not in serialized and "[redacted]" in serialized
        quality = ReviewTask(task_id="quality", agent_id=AgentId.QUALITY_TESTABILITY, files=["main.py"], focus="Complexity")
        output = await repo.tools().execute(quality, AgentAction(kind="call_tool", tool="complexity", arguments={"file_path": "main.py"}))
        assert repo.evidence(output.evidence_ref)["data"]["cyclomatic_lower_bound"] == 1
        with pytest.raises(PermissionError):
            await repo.tools().execute(quality, AgentAction(kind="call_tool", tool="config_read", arguments={"file_path": "config.json"}))
    asyncio.run(scenario())
