"""Source identity, scratch isolation and cache freshness using real disk stores."""

import importlib

import pytest


def stores():
    assert importlib.util.find_spec("devwatch.review.stores"), "Separated stores are missing"
    return importlib.import_module("devwatch.review.stores")


def test_five_store_locations_are_distinct(tmp_path):
    api = stores()
    layout = api.StoreLayout(tmp_path / "runtime")
    paths = [layout.jobs, layout.checkpoints, layout.repo_cache, layout.artifacts, layout.events]
    assert len(set(paths)) == 5
    assert all(path.is_relative_to(tmp_path / "runtime") for path in paths)


def test_report_pdf_artifacts_are_owned_bounded_and_hash_checked(tmp_path):
    api = stores()
    store = api.ArtifactStore(tmp_path / "artifacts")
    assert callable(getattr(store, "put_report_pdf", None)), "PDF artifact storage is missing"
    snapshot = store.capture(owner="alice", files={"service.py": "pass\n"})
    data = b"%PDF-1.7\nfixture\n%%EOF\n"
    identity = "a" * 32
    ref = store.put_report_pdf(identity, snapshot.snapshot_id, owner="alice", data=data)
    assert store.read_report_pdf(identity, snapshot.snapshot_id, owner="alice", reference=ref) == data
    assert store.put_report_pdf(identity, snapshot.snapshot_id, owner="alice", data=data) == ref
    with pytest.raises(PermissionError):
        store.read_report_pdf(identity, snapshot.snapshot_id, owner="bob", reference=ref)
    other = store.capture(owner="bob", files={})
    with pytest.raises(FileNotFoundError):
        store.read_report_pdf(identity, other.snapshot_id, owner="bob", reference=ref)
    with pytest.raises(ValueError):
        store.put_report_pdf("../escape", snapshot.snapshot_id, owner="alice", data=data)
    with pytest.raises(ValueError):
        store.put_report_pdf(identity, snapshot.snapshot_id, owner="alice", data=b"%PDF-" + b"x" * 10_000_000 + b"%%EOF")
    path = next((tmp_path / "artifacts" / "reports").glob("**/*.pdf"))
    path.write_bytes(b"tampered")
    with pytest.raises(api.SnapshotIntegrityError):
        store.read_report_pdf(identity, snapshot.snapshot_id, owner="alice", reference=ref)
    assert store.read_source(snapshot.snapshot_id, "service.py", owner="alice") == "pass\n"


def test_snapshot_identity_is_stable_and_scratch_cannot_mutate_it(tmp_path):
    api = stores()
    store = api.ArtifactStore(tmp_path / "artifacts")
    files = {"service.py": "def f():\n    return 1\n", "src/index.ts": "export const x = 1;\n"}
    snapshot = store.capture(owner="alice", files=files)
    second = store.capture(owner="alice", files=dict(reversed(list(files.items()))))
    assert snapshot.content_hash == second.content_hash
    scratch = store.create_scratch(snapshot.snapshot_id, owner="alice")
    (scratch / "service.py").write_text("changed", encoding="utf-8")
    assert store.read_source(snapshot.snapshot_id, "service.py", owner="alice") == "def f():\n    return 1\n"
    assert snapshot.entries["service.py"].line_count == 2
    with pytest.raises(PermissionError):
        store.read_source(snapshot.snapshot_id, "service.py", owner="bob")


def test_snapshot_rejects_traversal_sensitive_files_and_external_ids(tmp_path):
    api = stores()
    store = api.ArtifactStore(tmp_path / "artifacts")
    for path in ("../private.py", "C:/private.py", ".env", "nested/.env.test", "key.pem", ".git/config"):
        with pytest.raises(ValueError):
            store.capture(owner="alice", files={path: "sensitive"})
    with pytest.raises(ValueError):
        store.read_source("../other", "service.py", owner="alice")
    assert not (tmp_path / "private.py").exists()


def test_snapshot_detects_tampering_instead_of_reviewing_changed_source(tmp_path):
    api = stores()
    store = api.ArtifactStore(tmp_path / "artifacts")
    snapshot = store.capture(owner="alice", files={"service.py": "x = 1\n"})
    path = store.source_root(snapshot.snapshot_id, owner="alice") / "service.py"
    path.write_text("x = 2\n", encoding="utf-8")
    with pytest.raises(api.SnapshotIntegrityError):
        store.read_source(snapshot.snapshot_id, "service.py", owner="alice")
    with pytest.raises(api.SnapshotIntegrityError):
        store.create_scratch(snapshot.snapshot_id, owner="alice")


def test_cache_partition_and_versions_prevent_stale_results(tmp_path):
    api = stores()
    cache = api.RepoCache(tmp_path / "repo-cache.sqlite")
    key = api.CacheKey(owner_namespace="alice", namespace="ast", content_hash="hash1", parser_version="python-1")
    cache.put(key, {"symbols": ["f"]})
    assert api.RepoCache(tmp_path / "repo-cache.sqlite").get(key) == {"symbols": ["f"]}
    for changes in ({"content_hash": "hash2"}, {"parser_version": "python-2"},
                    {"owner_namespace": "bob"}, {"analysis_config_hash": "config2"},
                    {"prompt_version": "prompt2"}, {"model_name": "model2"}):
        assert cache.get(key.model_copy(update=changes)) is None
    with pytest.raises(api.CacheConflict):
        cache.put(key, {"symbols": ["different"]})


@pytest.mark.parametrize("path", ["CON.py", "nested/NUL/file.py", "service.py.", "folder /file.py"])
def test_windows_reserved_or_aliasing_paths_are_rejected_before_capture(tmp_path, path):
    api = stores()
    store = api.ArtifactStore(tmp_path / "artifacts")
    with pytest.raises(ValueError):
        store.capture(owner="alice", files={path: "x = 1\n"})
    assert list((tmp_path / "artifacts" / "snapshots").iterdir()) == []


def test_windows_case_aliases_are_rejected_before_capture(tmp_path):
    import os
    if os.name != "nt":
        pytest.skip("case-insensitive Windows filename boundary")
    api = stores()
    store = api.ArtifactStore(tmp_path / "artifacts")
    with pytest.raises(ValueError, match="duplicate"):
        store.capture(owner="alice", files={"service.py": "x=1", "SERVICE.py": "x=2"})
    assert list((tmp_path / "artifacts" / "snapshots").iterdir()) == []
