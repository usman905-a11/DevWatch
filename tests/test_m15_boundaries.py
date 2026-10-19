"""Admission and diagnostic behavior across registered tool implementations."""

import asyncio

import pytest

from devwatch.review.contracts import AgentAction, AgentId
from devwatch.review.repository import RepositoryContext
from devwatch.review.subgraphs import PermissionedTools, ToolObservation
from devwatch.review.tool_errors import ToolFailure
from tests.test_repository_context import setup_repository


@pytest.mark.parametrize("tool", ["read_source", "parse_ast", "code_search", "symbol_lookup"])
def test_registry_rejects_unassigned_paths_before_any_registered_handler(tmp_path, tool):
    _, _, _, _, task = setup_repository(tmp_path)
    tools, calls = PermissionedTools(), []
    async def handler(arguments, work):
        calls.append(arguments)
        return ToolObservation(evidence_ref="must-not-be-returned")
    tools.register(tool, handler)
    arguments = {"file_path": "other.py", **({"query": "private"} if tool == "code_search" else {})}
    with pytest.raises(PermissionError):
        asyncio.run(tools.execute(task, AgentAction(kind="call_tool", tool=tool, arguments=arguments)))
    assert calls == []


def test_parser_path_contract_rejects_absolute_paths_before_handler(tmp_path):
    _, _, _, _, task = setup_repository(tmp_path)
    tools = PermissionedTools()
    async def handler(arguments, work):
        raise AssertionError("absolute source path reached handler")
    tools.register("parse_ast", handler)
    with pytest.raises(ValueError):
        asyncio.run(tools.execute(task, AgentAction(kind="call_tool", tool="parse_ast",
                                                   arguments={"file_path": "C:/private/source.py"})))


def test_unsupported_parser_has_a_source_retrieval_fallback(tmp_path):
    _, artifacts, _, repo, task = setup_repository(tmp_path)
    snapshot = artifacts.capture(owner="alice", files={"notes.txt": "This is plain text."})
    repo = RepositoryContext(artifacts, repo.cache, snapshot.snapshot_id, owner="alice")
    task = task.model_copy(update={"files": ["notes.txt"]})
    with pytest.raises(ToolFailure) as error:
        asyncio.run(repo.tools().execute(task, AgentAction(kind="call_tool", tool="parse_ast", arguments={"file_path": "notes.txt"})))
    assert getattr(error.value, "code", None) == "parser_unavailable"
    assert "read_source" in error.value.hint
    ref = asyncio.run(repo.tools().execute(task, AgentAction(kind="call_tool", tool="read_source", arguments={"file_path": "notes.txt"}))).evidence_ref
    assert repo.evidence(ref)["data"] == "This is plain text."


def test_invalid_captured_json_reports_location_without_secret_source(tmp_path):
    _, artifacts, _, repo, task = setup_repository(tmp_path)
    snapshot = artifacts.capture(owner="alice", files={"settings.json": '{"private-token": invalid}'})
    repo = RepositoryContext(artifacts, repo.cache, snapshot.snapshot_id, owner="alice")
    work = task.model_copy(update={"agent_id": AgentId.ARCHITECTURE_SECURITY, "files": ["settings.json"]})
    with pytest.raises(ValueError) as error:
        asyncio.run(repo.tools().execute(work, AgentAction(kind="call_tool", tool="config_read", arguments={"file_path": "settings.json"})))
    assert getattr(error.value, "code", None) == "invalid_configuration"
    assert error.value.details == {"line": 1, "column": 19}
    assert "private-token" not in str(error.value)
