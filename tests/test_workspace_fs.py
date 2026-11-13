"""Phase 1 tests: read-only local workspace, /fs/* endpoints, path safety, and live-workspace scans."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from devwatch.review.contracts import ModelTier
from devwatch.review.repository import RepositoryContext
from devwatch.review.service import ServiceSettings, create_app
from devwatch.review.stores import ArtifactStore, RepoCache, StoreLayout


def _make_client(tmp_path: Path) -> TestClient:
    models = {ModelTier.SMALL: "test-small", ModelTier.MEDIUM: "test-medium", ModelTier.STRONG: "test-strong"}
    settings = ServiceSettings(runtime_root=tmp_path / "runtime", models=models, api_keys=frozenset({"test-key"}))
    app = create_app(settings=settings, provider=object())
    return TestClient(app, headers={"X-API-Key": "test-key"})


def test_workspace_set_and_get(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    not_a_dir = tmp_path / "file.txt"
    not_a_dir.write_text("hi", encoding="utf-8")

    with _make_client(tmp_path) as client:
        assert client.get("/workspace").json() == {"path": None}
        assert client.get("/fs/list").status_code == 409

        bad = client.post("/workspace", json={"path": str(tmp_path / "missing")})
        assert bad.status_code == 400
        bad_file = client.post("/workspace", json={"path": str(not_a_dir)})
        assert bad_file.status_code == 400

        ok = client.post("/workspace", json={"path": str(repo)})
        assert ok.status_code == 200
        assert Path(ok.json()["path"]).resolve() == repo.resolve()
        assert Path(client.get("/workspace").json()["path"]).resolve() == repo.resolve()


def test_fs_list_sorting_ignored_and_never_truncated(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".gitignore").write_text("*.log\nsecret_dir/\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "pkg.js").write_text("module.exports = 1\n", encoding="utf-8")
    (repo / "dist").mkdir()
    (repo / "secret_dir").mkdir()
    (repo / "b.py").write_text("print(1)\n", encoding="utf-8")
    (repo / "a.txt").write_text("hello\n", encoding="utf-8")
    (repo / "app.log").write_text("log\n", encoding="utf-8")

    with _make_client(tmp_path) as client:
        client.post("/workspace", json={"path": str(repo)})
        res = client.get("/fs/list", params={"path": ""})
        assert res.status_code == 200
        entries = res.json()["entries"]
        names = [e["name"] for e in entries]
        # Directories first (alphabetical), then files (alphabetical)
        assert names == ["dist", "node_modules", "secret_dir", "src", ".gitignore", "a.txt", "app.log", "b.py"]
        by_name = {e["name"]: e for e in entries}
        assert by_name["dist"]["ignored"] is True
        assert by_name["node_modules"]["ignored"] is True
        assert by_name["secret_dir"]["ignored"] is True
        assert by_name["app.log"]["ignored"] is True
        assert by_name["src"]["ignored"] is False
        assert by_name["b.py"]["ignored"] is False

        # Ignored directories remain expandable
        nm = client.get("/fs/list", params={"path": "node_modules"})
        assert nm.status_code == 200
        assert [e["name"] for e in nm.json()["entries"]] == ["pkg.js"]


def test_fs_read_full_1mb_too_large_and_binary(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    one_mb = ("x" * 99 + "\n") * 10_000  # 1,000,000 bytes
    (repo / "one_mb.txt").write_text(one_mb, encoding="utf-8", newline="\n")
    (repo / "huge.txt").write_bytes(b"a" * (2 * 1024 * 1024 + 10))
    (repo / "image.bin").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x01\x02")

    with _make_client(tmp_path) as client:
        client.post("/workspace", json={"path": str(repo)})

        ok = client.get("/fs/read", params={"path": "one_mb.txt"})
        assert ok.status_code == 200
        data = ok.json()
        assert data["tooLarge"] is False
        assert data["binary"] is False
        assert data["content"] == one_mb
        assert data["lineCount"] == 10_000

        huge = client.get("/fs/read", params={"path": "huge.txt"})
        assert huge.status_code == 200
        assert huge.json()["tooLarge"] is True
        assert huge.json()["content"] is None

        binary = client.get("/fs/read", params={"path": "image.bin"})
        assert binary.status_code == 200
        assert binary.json()["binary"] is True
        assert binary.json()["content"] is None


def test_fs_path_safety_rejects_traversal_and_escaping_symlink(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("top-secret", encoding="utf-8")
    (repo / "inside.txt").write_text("ok", encoding="utf-8")

    with _make_client(tmp_path) as client:
        client.post("/workspace", json={"path": str(repo)})

        for bad_path in ("../outside/secret.txt", "a/../../outside/secret.txt", str(secret), "bad\x00path"):
            assert client.get("/fs/read", params={"path": bad_path}).status_code == 403
            assert client.get("/fs/list", params={"path": bad_path}).status_code == 403

        escape_link = repo / "escape.txt"
        try:
            os.symlink(secret, escape_link)
        except OSError:
            pytest.skip("symlinks require elevated privileges on this Windows host")
        assert client.get("/fs/read", params={"path": "escape.txt"}).status_code == 403


def test_acceptance_5000_plus_files_and_1mb_read(tmp_path: Path):
    repo = tmp_path / "big_repo"
    repo.mkdir()
    # Create 5,050 files across 51 directories + 1 MB file
    for d in range(50):
        sub = repo / f"pkg_{d:02d}"
        sub.mkdir()
        for f in range(100):
            (sub / f"mod_{f:03d}.py").write_text(f"x = {f}\n", encoding="utf-8")
    for f in range(50):
        (repo / f"root_{f:02d}.py").write_text("pass\n", encoding="utf-8")
    one_mb = "line\n" * 200_000  # 1,000,000 bytes
    (repo / "large_source.py").write_text(one_mb, encoding="utf-8", newline="\n")

    with _make_client(tmp_path) as client:
        client.post("/workspace", json={"path": str(repo)})
        root_listing = client.get("/fs/list", params={"path": ""}).json()["entries"]
        # 50 dirs + 50 root_*.py + large_source.py = 101 immediate entries, zero truncation
        assert len(root_listing) == 101
        assert root_listing[0]["type"] == "dir"

        sub_listing = client.get("/fs/list", params={"path": "pkg_49"}).json()["entries"]
        assert len(sub_listing) == 100

        read_res = client.get("/fs/read", params={"path": "large_source.py"}).json()
        assert read_res["tooLarge"] is False
        assert read_res["content"] == one_mb


def test_repository_context_reads_live_workspace_without_snapshot_copy(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def greet():\n    return 'hi'\n", encoding="utf-8", newline="\n")
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "skip.js").write_text("ignored\n", encoding="utf-8")

    layout = StoreLayout(tmp_path / "runtime")
    artifacts = ArtifactStore(layout.artifacts)
    cache = RepoCache(layout.repo_cache)

    ctx = RepositoryContext(artifacts, cache, owner="local", workspace_root=repo)
    assert list(ctx.manifest.entries.keys()) == ["app.py"]
    assert ctx._source("app.py") == "def greet():\n    return 'hi'\n"
    # No snapshot copy was written to artifacts/snapshots
    assert list((layout.artifacts / "snapshots").iterdir()) == []
