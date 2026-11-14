"""Source identity, scratch isolation and cache freshness using real disk stores."""

import importlib

import pytest


def stores():
    assert importlib.util.find_spec("devwatch.review.stores"), "Separated stores are missing"
    return importlib.import_module("devwatch.review.stores")


def test_two_store_locations_are_distinct(tmp_path):
    api = stores()
    layout = api.StoreLayout(tmp_path / "runtime")
    paths = [layout.app_db, layout.checkpoints]
    assert len(set(paths)) == 2
    assert all(path.is_relative_to(tmp_path / "runtime") for path in paths)


def test_snapshot_identity_is_stable_and_owned(tmp_path):
    api = stores()
    store = api.ArtifactStore(tmp_path / "devwatch.sqlite")
    files = {"service.py": "def f():\n    return 1\n", "src/index.ts": "export const x = 1;\n"}
    snapshot = store.capture(owner="alice", files=files)
    second = store.capture(owner="alice", files=dict(reversed(list(files.items()))))
    assert snapshot.content_hash == second.content_hash
    assert store.read_source(snapshot.snapshot_id, "service.py", owner="alice") == "def f():\n    return 1\n"
    assert snapshot.entries["service.py"].line_count == 2
    with pytest.raises(PermissionError):
        store.read_source(snapshot.snapshot_id, "service.py", owner="bob")


def test_snapshot_rejects_traversal_sensitive_files_and_external_ids(tmp_path):
    api = stores()
    store = api.ArtifactStore(tmp_path / "devwatch.sqlite")
    for path in ("../private.py", "C:/private.py", ".env", "nested/.env.test", "key.pem", ".git/config"):
        with pytest.raises(ValueError):
            store.capture(owner="alice", files={path: "sensitive"})
    with pytest.raises(ValueError):
        store.read_source("../other", "service.py", owner="alice")
    assert not (tmp_path / "private.py").exists()


def test_snapshot_detects_tampering_instead_of_reviewing_changed_source(tmp_path):
    import sqlite3
    api = stores()
    db_path = tmp_path / "devwatch.sqlite"
    store = api.ArtifactStore(db_path)
    snapshot = store.capture(owner="alice", files={"service.py": "x = 1\n"})
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE snapshot_files SET content = ? WHERE snapshot_id = ? AND file_path = ?",
            ("x = 2\n", snapshot.snapshot_id, "service.py"),
        )
    with pytest.raises(api.SnapshotIntegrityError):
        store.read_source(snapshot.snapshot_id, "service.py", owner="alice")


@pytest.mark.parametrize("path", ["CON.py", "nested/NUL/file.py", "service.py.", "folder /file.py"])
def test_windows_reserved_or_aliasing_paths_are_rejected_before_capture(tmp_path, path):
    import sqlite3
    api = stores()
    db_path = tmp_path / "devwatch.sqlite"
    store = api.ArtifactStore(db_path)
    with pytest.raises(ValueError):
        store.capture(owner="alice", files={path: "x = 1\n"})
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 0


def test_windows_case_aliases_are_rejected_before_capture(tmp_path):
    import os
    import sqlite3
    if os.name != "nt":
        pytest.skip("case-insensitive Windows filename boundary")
    api = stores()
    db_path = tmp_path / "devwatch.sqlite"
    store = api.ArtifactStore(db_path)
    with pytest.raises(ValueError, match="duplicate"):
        store.capture(owner="alice", files={"service.py": "x=1", "SERVICE.py": "x=2"})
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 0
