"""Phase 1 tests: read-only local workspace, /fs/* endpoints, path safety, and live-workspace scans."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from backend.review.contracts import ModelTier
from backend.review.repository import RepositoryContext
from backend.review.service import ServiceSettings, create_app
from backend.review.stores import ArtifactStore, StoreLayout


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

        quoted = client.post("/workspace", json={"path": f'"{repo}"'})
        assert quoted.status_code == 200
        assert Path(quoted.json()["path"]).resolve() == repo.resolve()


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
    artifacts = ArtifactStore(layout.app_db)

    ctx = RepositoryContext(artifacts, owner="local", workspace_root=repo)
    assert list(ctx.manifest.entries.keys()) == ["app.py"]
    assert ctx._source("app.py") == "def greet():\n    return 'hi'\n"
    assert not (tmp_path / "runtime" / "artifacts" / "snapshots").exists()


def test_build_workspace_manifest_excludes_secrets_and_enforces_total_size(tmp_path: Path):
    from backend.review.workspace import build_workspace_manifest

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("x = 1\n", encoding="utf-8")
    (repo / ".env").write_text("SECRET=123\n", encoding="utf-8")
    (repo / ".env.local").write_text("LOCAL=123\n", encoding="utf-8")
    (repo / "private.key").write_text("KEYDATA\n", encoding="utf-8")
    (repo / "big_extra.py").write_text("y = 2\n" * 50, encoding="utf-8")

    manifest = build_workspace_manifest(repo, max_total_bytes=200)
    assert "main.py" in manifest.entries
    assert ".env" not in manifest.entries
    assert ".env.local" not in manifest.entries
    assert "private.key" not in manifest.entries
    assert manifest.capture_coverage.skipped[".env"] == "excluded_secret"
    assert manifest.capture_coverage.skipped[".env.local"] == "excluded_secret"
    assert manifest.capture_coverage.skipped["private.key"] == "excluded_secret"
    assert manifest.capture_coverage.skipped["big_extra.py"] == "total_size_limit"


def test_planner_context_gracefully_prunes_huge_change_list(tmp_path: Path):
    from backend.review.budgets import BudgetManager
    from backend.review.contracts import AgentId, AgentPrivateState, AgentWorkItem
    from backend.review.jobs import JobRecord, JobStore
    from backend.review.workflow import CanonicalReviewExecutor, _ReviewSession

    repo = tmp_path / "many"
    repo.mkdir()
    for i in range(600):
        (repo / f"module_with_a_fairly_long_filename_number_{i:04d}_service_helper.py").write_text("x = 1\n", encoding="utf-8")
    layout = StoreLayout(tmp_path / "runtime")
    artifacts = ArtifactStore(layout.app_db)
    jobs = JobStore(layout.app_db)
    ctx = RepositoryContext(artifacts, owner="local", workspace_root=repo)
    executor = CanonicalReviewExecutor(layout, artifacts, jobs, provider=object(),
        models={t: t.value for t in ModelTier})
    job = JobRecord(job_id="a" * 32, owner="local", status="queued", request={"workspace_path": str(repo)}, created_at=1, updated_at=1)
    session = _ReviewSession(executor, job, ctx, BudgetManager(), sorted(ctx.manifest.entries))
    work = AgentWorkItem(task_id="__planner", agent_id=AgentId.PLANNER, files=sorted(ctx.manifest.entries), focus="Plan")
    selected = session.context({"task": work, "private_state": AgentPrivateState(), "action": None})
    assert len(selected["changes"]) < len(ctx.manifest.entries)
    assert selected["omitted_changes_count"] > 0


def test_fs_read_blocks_sensitive_files_and_symlinks_with_403(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    sensitive_paths = [
        ".env",
        ".env.local",
        "config/.env.production",
        "private.key",
        "cert.pem",
        "id_rsa",
        "secrets.json",
        "service_account.json",
        ".git/config",
        ".aws/credentials",
        ".ssh/id_ed25519",
    ]
    for rel in sensitive_paths:
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("TOP_SECRET_VALUE\n", encoding="utf-8")

    with _make_client(tmp_path) as client:
        assert client.post("/workspace", json={"path": str(repo)}).status_code == 200
        assert client.get("/fs/read", params={"path": "src/app.py"}).status_code == 200
        for rel in sensitive_paths:
            res = client.get("/fs/read", params={"path": rel})
            assert res.status_code == 403, f"expected 403 for {rel}, got {res.status_code}"
            assert "TOP_SECRET_VALUE" not in res.text


def test_fs_list_does_not_leak_external_symlink_target_metadata(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    outside_file = outside_dir / "secret.txt"
    outside_file.write_text("x" * 1234, encoding="utf-8")

    link_dir = repo / "ext_dir"
    link_file = repo / "ext_file.txt"
    try:
        os.symlink(outside_dir, link_dir, target_is_directory=True)
        os.symlink(outside_file, link_file)
    except OSError:
        pytest.skip("symlinks require elevated privileges on this Windows host")

    with _make_client(tmp_path) as client:
        client.post("/workspace", json={"path": str(repo)})
        entries = {e["name"]: e for e in client.get("/fs/list", params={"path": ""}).json()["entries"]}
        assert entries["ext_dir"]["isSymlink"] is True
        assert entries["ext_dir"]["ignored"] is True
        assert entries["ext_dir"]["type"] == "file"
        assert entries["ext_dir"]["size"] == 0
        assert entries["ext_file.txt"]["isSymlink"] is True
        assert entries["ext_file.txt"]["ignored"] is True
        assert entries["ext_file.txt"]["size"] == 0
        assert client.get("/fs/list", params={"path": "ext_dir"}).status_code == 403
        assert client.get("/fs/read", params={"path": "ext_file.txt"}).status_code == 403


def test_workspace_state_is_isolated_per_principal(tmp_path: Path):
    from backend.review.contracts import ModelTier
    from backend.review.service import ServiceSettings, create_app

    repo_a = tmp_path / "repo_a"
    repo_a.mkdir()
    (repo_a / "a.py").write_text("a = 1\n", encoding="utf-8")
    repo_b = tmp_path / "repo_b"
    repo_b.mkdir()
    (repo_b / "b.py").write_text("b = 2\n", encoding="utf-8")

    app = create_app(
        settings=ServiceSettings(
            runtime_root=tmp_path / "runtime",
            models={t: t.value for t in ModelTier},
            api_keys=frozenset({"alice-key", "bob-key"}),
        ),
        provider=object(),
    )
    with TestClient(app) as client:
        alice = {"X-API-Key": "alice-key"}
        bob = {"X-API-Key": "bob-key"}
        assert client.post("/workspace", headers=alice, json={"path": str(repo_a)}).status_code == 200
        assert client.get("/workspace", headers=bob).json() == {"path": None}
        assert client.get("/fs/list", headers=bob).status_code == 409
        assert client.post("/workspace", headers=bob, json={"path": str(repo_b)}).status_code == 200
        alice_list = [e["name"] for e in client.get("/fs/list", headers=alice).json()["entries"]]
        bob_list = [e["name"] for e in client.get("/fs/list", headers=bob).json()["entries"]]
        assert alice_list == ["a.py"]
        assert bob_list == ["b.py"]


def test_fs_list_never_follows_external_reparse_entry_even_without_os_symlink(tmp_path: Path, monkeypatch):
    from backend.review import workspace as ws_mod

    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("x" * 2048, encoding="utf-8")

    class FakeDirEntry:
        def __init__(self, name: str, path: Path, *, escape: bool):
            self.name = name
            self.path = str(path)
            self._escape = escape

        def is_symlink(self) -> bool:
            return self._escape

        def is_dir(self, *, follow_symlinks: bool = True) -> bool:
            if self._escape and follow_symlinks:
                raise AssertionError("must never call is_dir(follow_symlinks=True) on external symlink")
            return False

        def stat(self, *, follow_symlinks: bool = True):
            if self._escape and follow_symlinks:
                raise AssertionError("must never call stat(follow_symlinks=True) on external symlink")
            raise AssertionError("must never stat external symlink")

    fake_entry = FakeDirEntry("ext_link", repo / "ext_link", escape=True)

    class _ScanCtx:
        def __enter__(self):
            return iter([fake_entry])

        def __exit__(self, *args):
            return False

    orig_realpath = ws_mod.os.path.realpath

    def fake_realpath(p, *args, **kwargs):
        if Path(p) == repo / "ext_link":
            return str(outside / "secret.txt")
        return orig_realpath(p, *args, **kwargs)

    monkeypatch.setattr(ws_mod.os, "scandir", lambda _target: _ScanCtx())
    monkeypatch.setattr(ws_mod.os.path, "realpath", fake_realpath)

    mgr = ws_mod.WorkspaceManager()
    mgr.set_root(repo)
    entries = mgr.list_dir("")
    assert len(entries) == 1
    assert entries[0].to_dict() == {
        "name": "ext_link",
        "path": "ext_link",
        "type": "file",
        "size": 0,
        "isSymlink": True,
        "ignored": True,
    }
