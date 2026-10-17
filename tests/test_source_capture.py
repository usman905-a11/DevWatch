"""Bounded local capture for canonical job clients; original source is never written."""
import importlib
from pathlib import Path
import subprocess

import pytest

from devwatch.config import Config


def capture(path):
    return importlib.import_module("devwatch.review.capture").capture_source(path)


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


def repository(path):
    git(path, "init")
    git(path, "config", "user.name", "Fixture")
    git(path, "config", "user.email", "fixture@example.invalid")


def commit(path):
    git(path, "add", ".")
    git(path, "commit", "-m", "fixture baseline")


def test_directory_capture_excludes_sensitive_generated_and_invalid_source(tmp_path):
    (tmp_path / "service.py").write_text("def first(items):\n    return items[0]\n", encoding="utf-8")
    (tmp_path / "context.ts").write_text("export const n = 1;\n", encoding="utf-8")
    (tmp_path / ".env").write_text("PRIVATE_SECRET=never-upload")
    (tmp_path / "secrets.json").write_text('{"key":"never-upload"}')
    (tmp_path / "bad.py").write_bytes(b"\xff\x00")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.js").write_text("secret dependency source")
    before = (tmp_path / "service.py").read_bytes()
    result = capture(tmp_path)
    assert set(result.files) == {"service.py", "context.ts"}
    assert set(result.changed_files) == set(result.files)
    assert result.coverage.skipped["secrets.json"] == "excluded_source"
    assert result.coverage.skipped["node_modules"] == "excluded_directory"
    assert result.coverage.failed["bad.py"] == "invalid_text_source"
    assert "never-upload" not in result.model_dump_json()
    assert (tmp_path / "service.py").read_bytes() == before


def test_git_selection_includes_staged_unstaged_untracked_and_rename_with_context(tmp_path):
    repository(tmp_path)
    for name in ("old.py", "deleted.py", "staged.py", "unstaged.py", "context.py"):
        (tmp_path / name).write_text(f"name = {name!r}\n")
    (tmp_path / ".gitignore").write_text("ignored.py\n")
    commit(tmp_path)
    git(tmp_path, "mv", "old.py", "new.py")
    git(tmp_path, "rm", "deleted.py")
    (tmp_path / "staged.py").write_text("n = 2\n")
    git(tmp_path, "add", "staged.py")
    (tmp_path / "unstaged.py").write_text("n = 3\n")
    (tmp_path / "untracked.py").write_text("n = 4\n")
    (tmp_path / "ignored.py").write_text("n = 5\n")
    result = capture(tmp_path)
    assert set(result.changed_files) == {"new.py", "staged.py", "unstaged.py", "untracked.py"}
    assert "context.py" in result.files
    assert "ignored.py" not in result.files
    assert result.coverage.skipped["deleted.py"] == "deleted_source_unavailable"
    assert result.scope_kind == "git_changes"


def test_clean_git_and_nested_scope_do_not_select_outside_changes(tmp_path):
    repository(tmp_path)
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "inside.py").write_text("inside = 1\n")
    (tmp_path / "outside.py").write_text("outside = 1\n")
    commit(tmp_path)
    assert capture(tmp_path).changed_files == []
    (tmp_path / "outside.py").write_text("outside = 2\n")
    result = capture(tmp_path / "nested")
    assert result.changed_files == [] and set(result.files) == {"inside.py"}
    (tmp_path / "nested" / "inside.py").write_text("inside = 2\n")
    assert capture(tmp_path / "nested").changed_files == ["inside.py"]


def test_changed_source_is_prioritized_and_capture_limits_are_reported(tmp_path, monkeypatch):
    repository(tmp_path)
    (tmp_path / "a_context.py").write_text("a = 1\n")
    (tmp_path / "z_changed.py").write_text("z = 1\n")
    commit(tmp_path)
    (tmp_path / "z_changed.py").write_text("z = 2\n")
    monkeypatch.setattr(Config, "MAX_FILES_PER_REVIEW", 1)
    result = capture(tmp_path)
    assert set(result.files) == {"z_changed.py"}
    assert result.coverage.skipped["a_context.py"] == "snapshot_file_limit"
    monkeypatch.setattr(Config, "MAX_BYTES_PER_FILE", 3)
    result = capture(tmp_path)
    assert not result.files
    assert result.coverage.failed["z_changed.py"] == "snapshot_file_size_limit"


def test_single_file_capture_and_missing_target(tmp_path):
    source = tmp_path / "service.py"
    source.write_bytes(b"pass\r\n")
    result = capture(source)
    assert result.files == {"service.py": "pass\r\n"}
    assert result.changed_files == ["service.py"]
    with pytest.raises(ValueError):
        capture(tmp_path / "missing.py")


def test_git_metadata_failure_is_explicit_and_never_reports_clean_scope(tmp_path, monkeypatch):
    api = importlib.import_module("devwatch.review.capture")
    repository(tmp_path)
    (tmp_path / "service.py").write_text("pass\n")
    def unavailable(*args):
        raise TimeoutError("private upstream detail")
    monkeypatch.setattr(api, "_git", unavailable)
    result = api.capture_source(tmp_path)
    assert result.changed_files == ["service.py"]
    assert any("Git metadata unavailable" in item for item in result.coverage.limitations)
    assert "private upstream detail" not in result.model_dump_json()
