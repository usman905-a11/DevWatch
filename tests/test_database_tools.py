"""Actual read-only SQLite schema/query analysis through role and owner policy."""
import asyncio
import importlib
import sqlite3

import pytest

from devwatch.review.contracts import AgentAction, AgentId, ReviewTask
from tests.test_trusted_runtime import setup


def api():
    assert importlib.util.find_spec("devwatch.review.database_tools"), "Database analysis tools are missing"
    return importlib.import_module("devwatch.review.database_tools")


def test_readonly_schema_and_real_query_plan_require_owner_and_role(tmp_path):
    module = api()
    path = tmp_path / "fixture.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript("CREATE TABLE items(id INTEGER PRIMARY KEY,value TEXT); INSERT INTO items VALUES(1,'private row');")
    connection.close()
    _, _, repo, jobs, job, _ = setup(tmp_path, "def query(db):\n    return db.execute('SELECT id FROM items WHERE id = ?', (1,))\n")
    policy = module.DatabasePolicy(database_id="fixture", path=path, owners=frozenset({"alice"}))
    tools = module.DatabaseTools(repo, job, policies=(policy,))
    task = ReviewTask(task_id="db-perf", agent_id=AgentId.PERFORMANCE_SCALABILITY, files=["probe.py"], focus="Inspect query plan")
    async def scenario():
        schema = await tools.execute(task, AgentAction(kind="call_tool", tool="db_analyze", arguments={"database_id": "fixture"}))
        record = repo.evidence(schema.evidence_ref)
        assert record["data"]["tables"][0]["name"] == "items"
        assert "private row" not in str(record) and schema.inspected == []
        query = await tools.execute(task, AgentAction(kind="call_tool", tool="query_analyze",
            arguments={"database_id": "fixture", "query": "SELECT id FROM items WHERE id = ?", "parameters": [1]}))
        assert any("PRIMARY KEY" in row[-1] for row in repo.evidence(query.evidence_ref)["data"]["query_plan"])
        with pytest.raises(PermissionError):
            await tools.execute(task, AgentAction(kind="call_tool", tool="query_analyze", arguments={"database_id": "fixture", "query": "DROP TABLE items"}))
        with pytest.raises(PermissionError):
            await tools.execute(task.model_copy(update={"agent_id": AgentId.BUG_RELIABILITY}),
                AgentAction(kind="call_tool", tool="db_analyze", arguments={"database_id": "fixture"}))
        denied = module.DatabaseTools(repo, job.model_copy(update={"owner": "bob"}), policies=(policy,))
        with pytest.raises(PermissionError):
            await denied.execute(task, AgentAction(kind="call_tool", tool="db_analyze", arguments={"database_id": "fixture"}))
    asyncio.run(scenario())
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT count(*) FROM items").fetchone()[0] == 1
    connection.close()
