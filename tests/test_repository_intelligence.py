"""Language facts and scoped graph tools operate on real immutable snapshots."""
import asyncio
import json

import pytest

from devwatch.review.contracts import AgentAction, AgentId, AgentWorkItem
from devwatch.review.repository import RepositoryContext
from devwatch.review.stores import ArtifactStore


def repository(tmp_path):
    artifacts = ArtifactStore(tmp_path / "devwatch.sqlite")
    snapshot = artifacts.capture(owner="alice", files={
        "main.py": "from helper import double\ndef result(x):\n    return double(x)\n",
        "helper.py": "def double(x):\n    return x * 2\n",
        "index.ts": "import { double } from './helper';\nexport const result = (x: number): number => double(x);\n",
        "helper.ts": "export function double(x: number) { return x * 2; }\n",
        "view.tsx": "export function View() { return <div>result</div>; }\n",
        "broken.js": "function broken( {",
    })
    return RepositoryContext(artifacts, snapshot.snapshot_id, owner="alice")


def test_real_javascript_typescript_tsx_ast_and_parse_failures(tmp_path):
    repo = repository(tmp_path)
    facts = repo.analyze()
    assert facts["index.ts"]["status"] == "parsed"
    assert {symbol["name"] for symbol in facts["index.ts"]["symbols"]} == {"result"}
    assert facts["index.ts"]["imports"] == ["./helper"]
    assert facts["index.ts"]["calls"][0]["target"] == "double"
    assert facts["view.tsx"]["symbols"][0]["name"] == "View"
    assert facts["broken.js"]["status"] == "parse_failed"
    reopened = RepositoryContext(repo.artifacts, repo.snapshot_id, owner="alice")
    assert reopened.analyze() == facts


def test_call_and_symbol_tools_have_distinct_scoped_outputs(tmp_path):
    repo = repository(tmp_path)
    work = AgentWorkItem(task_id="graphs", agent_id=AgentId.SYNTHESIZER_VERIFIER,
        files=["main.py", "helper.py"], focus="Resolve calls")
    async def scenario():
        tools = repo.tools()
        calls = await tools.execute(work, AgentAction(kind="call_tool", tool="call_graph", arguments={"file_path": "main.py"}))
        assert repo.evidence(calls.evidence_ref)["data"]["calls"][0]["caller"] == "result"
        symbol = await tools.execute(work, AgentAction(kind="call_tool", tool="symbol_lookup", arguments={"file_path": "helper.py", "symbol": "double"}))
        assert repo.evidence(symbol.evidence_ref)["data"] == [{"name": "double", "start_line": 1, "end_line": 2}]
    asyncio.run(scenario())
