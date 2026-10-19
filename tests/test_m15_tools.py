"""Actionable errors from real immutable-source and evidence handlers."""

import asyncio
from hashlib import sha256
import json

import pytest

from devwatch.review.contracts import AgentAction
from devwatch.review.repository import RepositoryContext
from devwatch.review.tool_errors import ToolFailure
from tests.test_repository_context import setup_repository


def test_invalid_source_start_reports_real_bounds_without_source_text(tmp_path):
    _, _, _, repo, task = setup_repository(tmp_path)
    with pytest.raises(ValueError) as error:
        asyncio.run(repo.tools().execute(task, AgentAction(kind="call_tool", tool="read_source",
            arguments={"file_path": "service.py", "start_line": 99, "end_line": 100})))
    assert getattr(error.value, "code", None) == "invalid_source_range"
    assert error.value.details == {"line_count": 2, "max_lines": 200}
    assert error.value.recoverable
    assert "start_line" in error.value.hint
    assert "return items[0]" not in str(error.value)


@pytest.mark.parametrize("arguments", [
    {"start_line": "private-invalid-value"}, {"start_line": True},
    {"start_line": 2, "end_line": 1}, {"start_line": 1, "end_line": 201},
])
def test_source_handler_rejects_bad_types_and_ranges_with_controlled_errors(tmp_path, arguments):
    _, _, _, repo, task = setup_repository(tmp_path)
    with pytest.raises(ValueError) as error:
        repo._read_source({"file_path": "service.py", **arguments}, task)
    assert getattr(error.value, "code", None) == "invalid_source_range"
    assert "private-invalid-value" not in str(error.value)


def test_empty_source_returns_honest_evidence_without_invented_line_locations(tmp_path):
    _, artifacts, _, repo, task = setup_repository(tmp_path)
    snapshot = artifacts.capture(owner="alice", files={"empty.py": ""})
    empty = RepositoryContext(artifacts, repo.cache, snapshot.snapshot_id, owner="alice")
    work = task.model_copy(update={"files": ["empty.py"]})
    observation = asyncio.run(empty.tools().execute(work, AgentAction(kind="call_tool", tool="read_source",
        arguments={"file_path": "empty.py"})))
    record = empty.evidence(observation.evidence_ref)
    assert record["data"] == "" and record["line_count"] == 0
    assert "start_line" not in record and "end_line" not in record
    assert record["source_scope"] == ["empty.py"]


def test_evidence_offset_reports_actual_artifact_size(tmp_path):
    _, _, _, repo, task = setup_repository(tmp_path)
    ref = repo._read_source({"file_path": "service.py"}, task).evidence_ref
    size = len((repo.evidence_root / (ref + ".json")).read_text(encoding="utf-8"))
    with pytest.raises(ValueError) as error:
        repo.evidence_page(ref, task, offset=size)
    assert getattr(error.value, "code", None) == "invalid_evidence_offset"
    assert error.value.details == {"total_chars": size}
    assert error.value.recoverable


def test_tampered_evidence_is_terminal_instead_of_correctable_input(tmp_path):
    _, _, _, repo, task = setup_repository(tmp_path)
    ref = repo._read_source({"file_path": "service.py"}, task).evidence_ref
    path = repo.evidence_root / (ref + ".json")
    record = json.loads(path.read_text(encoding="utf-8"))
    record["data"] = "private-tampered-content"
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError) as error:
        repo.evidence(ref)
    assert getattr(error.value, "code", None) == "evidence_integrity_failure"
    assert not error.value.recoverable
    assert "private-tampered-content" not in str(error.value)


def test_scope_denial_does_not_disclose_file_bounds(tmp_path):
    _, _, _, repo, task = setup_repository(tmp_path)
    with pytest.raises(PermissionError):
        repo._read_source({"file_path": "other.py", "start_line": 999}, task)


@pytest.mark.parametrize("record", [[], {}, {"snapshot_id": "forged", "source_scope": "other.py"}])
def test_content_address_alone_does_not_make_malformed_evidence_valid(tmp_path, record):
    _, _, _, repo, _ = setup_repository(tmp_path)
    encoded = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    ref = "evidence-" + sha256(encoded.encode()).hexdigest()
    (repo.evidence_root / (ref + ".json")).write_text(encoded, encoding="utf-8")
    with pytest.raises(ToolFailure) as error:
        repo.evidence(ref)
    assert error.value.code == "evidence_integrity_failure"
    assert not error.value.recoverable
