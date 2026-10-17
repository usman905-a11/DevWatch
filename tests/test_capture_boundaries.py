"""Regression checks for bounded enumeration and inert Git metadata capture."""
import importlib
import os
from pathlib import Path
import sys

from tests.test_source_capture import repository, commit, git


def api():
    return importlib.import_module("devwatch.review.capture")


def test_directory_catalog_stops_consuming_at_limit_even_for_excluded_entries(tmp_path, monkeypatch):
    collector = api()
    for index in range(20):
        (tmp_path / f".excluded-{index}").mkdir()
    original = os.scandir
    consumed = []
    class Counted:
        def __init__(self, path):
            self.stream = original(path)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def __iter__(self):
            return self
        def __next__(self):
            item = next(self.stream)
            consumed.append(item.name)
            return item
    monkeypatch.setattr(collector.os, "scandir", Counted)
    monkeypatch.setattr(collector, "MAX_CATALOG_ENTRIES", 5)
    result = collector.capture_source(tmp_path)
    assert len(consumed) <= 5
    assert any("catalog" in note and "limit" in note for note in result.coverage.limitations)


def test_git_changed_candidates_cannot_reenter_truncated_catalog(tmp_path, monkeypatch):
    collector = api()
    repository(tmp_path)
    (tmp_path / "base.py").write_text("base = 1\n")
    commit(tmp_path)
    for index in range(10):
        (tmp_path / f"changed-{index}.py").write_text("value = 1\n")
    monkeypatch.setattr(collector, "MAX_CATALOG_ENTRIES", 3)
    result = collector.capture_source(tmp_path)
    assert len(result.files) <= 3
    assert any("catalog" in note and "limit" in note for note in result.coverage.limitations)


def test_tracked_generated_directories_use_same_policy_as_directory_capture(tmp_path):
    collector = api()
    repository(tmp_path)
    for directory in ("dist", "build", "coverage", "venv"):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "generated.py").write_text("generated = 1\n")
    (tmp_path / "service.py").write_text("source = 1\n")
    commit(tmp_path)
    for directory in ("dist", "build", "coverage", "venv"):
        (tmp_path / directory / "generated.py").write_text("generated = 2\n")
    result = collector.capture_source(tmp_path)
    assert set(result.files) == {"service.py"}
    assert result.changed_files == []
    for directory in ("dist", "build", "coverage", "venv"):
        assert result.coverage.skipped[f"{directory}/generated.py"] == "excluded_directory"


def test_unreadable_directory_is_reported_without_raw_os_error(tmp_path, monkeypatch):
    collector = api()
    (tmp_path / "service.py").write_text("pass\n")
    denied = tmp_path / "denied"
    denied.mkdir()
    original = os.scandir
    def listing(path):
        if Path(path) == denied:
            raise PermissionError("private raw OS error")
        return original(path)
    monkeypatch.setattr(collector.os, "scandir", listing)
    result = collector.capture_source(tmp_path)
    assert result.files == {"service.py": (tmp_path / "service.py").read_bytes().decode("utf-8")}
    assert result.coverage.failed["denied"] == "unavailable_directory"
    assert "private raw" not in result.model_dump_json()


def test_parent_git_capture_does_not_execute_submodule_only_filter(tmp_path):
    external, parent = tmp_path / "external", tmp_path / "parent"
    external.mkdir()
    parent.mkdir()
    repository(external)
    (external / "filtered.py").write_text("value = 1\n")
    (external / ".gitattributes").write_text("filtered.py filter=marker\n")
    commit(external)
    repository(parent)
    (parent / "service.py").write_text("pass\n")
    git(parent, "-c", "protocol.file.allow=always", "submodule", "add", str(external), "modules/sub")
    commit(parent)
    child = parent / "modules" / "sub"
    marker = tmp_path / "marker.txt"
    script = tmp_path / "marker-filter.py"
    script.write_text("import sys\nfrom pathlib import Path\n" +
        f"Path({str(marker)!r}).write_text('executed')\n" + "sys.stdout.buffer.write(sys.stdin.buffer.read())\n")
    git(child, "config", "filter.marker.clean", f'"{sys.executable}" "{script}"')
    (child / "filtered.py").write_text("value = 2\n")
    result = api().capture_source(parent)
    assert not marker.exists(), "Git capture executed a submodule-only filter"
    assert result.coverage.skipped["modules/sub"] == "git_submodule_not_captured"
    assert any("submodule" in note.lower() for note in result.coverage.limitations)
