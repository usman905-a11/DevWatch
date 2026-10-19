"""Read-only query failures remain correctable without exposing query values."""

import asyncio
import sqlite3

import pytest

from devwatch.review.contracts import AgentAction, AgentId, ReviewTask
from devwatch.review.database_tools import DatabasePolicy, DatabaseTools
from tests.test_trusted_runtime import setup


def configured(tmp_path):
    path = tmp_path / "fixture.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE items(id INTEGER)")
    _, _, repo, _, job, _ = setup(tmp_path, "def probe():\n    pass\n")
    runtime = DatabaseTools(repo, job, policies=(DatabasePolicy(database_id="fixture", path=path, owners={"alice"}),))
    task = ReviewTask(task_id="query", agent_id=AgentId.PERFORMANCE_SCALABILITY, files=["probe.py"], focus="Query plans")
    return repo, runtime, task


def test_query_error_is_structured_and_does_not_leak_sql_or_host_paths(tmp_path):
    repo, runtime, task = configured(tmp_path)
    action = AgentAction(kind="call_tool", tool="query_analyze", arguments={
        "database_id": "fixture", "query": "SELECT private_token FROM missing_table"})
    with pytest.raises((ValueError, sqlite3.Error)) as error:
        asyncio.run(repo.tools(database_runtime=runtime).execute(task, action))
    assert getattr(error.value, "code", None) == "invalid_query"
    assert error.value.recoverable
    assert "private_token" not in str(error.value) and str(tmp_path) not in str(error.value)
    good = AgentAction(kind="call_tool", tool="query_analyze", arguments={"database_id": "fixture", "query": "SELECT id FROM items"})
    observation = asyncio.run(repo.tools(database_runtime=runtime).execute(task, good))
    assert repo.evidence(observation.evidence_ref)["data"]["query_plan"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_query_parameters_are_rejected_before_database_execution(tmp_path, value):
    repo, runtime, task = configured(tmp_path)
    with pytest.raises(ValueError):
        asyncio.run(repo.tools(database_runtime=runtime).execute(task, AgentAction(kind="call_tool", tool="query_analyze",
            arguments={"database_id": "fixture", "query": "SELECT ?", "parameters": [value]})))
    assert not list(repo.evidence_root.glob("evidence-*.json"))
