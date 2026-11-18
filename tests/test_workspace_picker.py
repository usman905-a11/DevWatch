from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.review import service as service_module
from backend.review.contracts import ModelTier


HEADERS = {"X-API-Key": "test-key"}


def _make_client(tmp_path: Path) -> TestClient:
    settings = service_module.ServiceSettings(
        runtime_root=tmp_path / "runtime",
        models={t: t.value for t in ModelTier},
        api_keys=frozenset({"test-key"}),
    )
    app = service_module.create_app(settings=settings, provider=SimpleNamespace())
    return TestClient(app)


def test_workspace_pick_sets_workspace_root_when_selected(tmp_path: Path, monkeypatch) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    async def fake_dialog() -> tuple[str | None, str | None]:
        return str(repo_dir), None

    monkeypatch.setattr(service_module, "_run_folder_picker_dialog", fake_dialog)

    with _make_client(tmp_path) as client:
        picked = client.post("/workspace/pick", headers=HEADERS)
        assert picked.status_code == 200
        assert picked.json()["path"] == str(repo_dir.resolve())

        current = client.get("/workspace", headers=HEADERS)
        assert current.status_code == 200
        assert current.json()["path"] == str(repo_dir.resolve())


def test_workspace_pick_handles_cancel_and_unavailable_cleanly(tmp_path: Path, monkeypatch) -> None:
    async def fake_cancel() -> tuple[str | None, str | None]:
        return None, None

    monkeypatch.setattr(service_module, "_run_folder_picker_dialog", fake_cancel)

    with _make_client(tmp_path) as client:
        cancelled = client.post("/workspace/pick", headers=HEADERS)
        assert cancelled.status_code == 200
        assert cancelled.json()["path"] is None
        assert cancelled.json()["cancelled"] is True

        async def fake_error() -> tuple[str | None, str | None]:
            return None, "display unavailable"

        monkeypatch.setattr(service_module, "_run_folder_picker_dialog", fake_error)
        failed = client.post("/workspace/pick", headers=HEADERS)
        assert failed.status_code == 200
        assert failed.json()["path"] is None
        assert failed.json()["error"] == "display unavailable"


def test_workspace_browse_lists_only_directories_and_requires_auth(tmp_path: Path) -> None:
    (tmp_path / "repo_alpha").mkdir()
    (tmp_path / "repo_beta").mkdir()
    (tmp_path / "secret.txt").write_text("hidden", encoding="utf-8")

    with _make_client(tmp_path) as client:
        unauth = client.get("/workspace/browse")
        assert unauth.status_code == 401

        root_res = client.get("/workspace/browse", headers=HEADERS)
        assert root_res.status_code == 200
        root_payload = root_res.json()
        assert root_payload["current_path"]
        assert isinstance(root_payload["roots"], list)

        sub_res = client.get("/workspace/browse", params={"path": str(tmp_path)}, headers=HEADERS)
        assert sub_res.status_code == 200
        sub_payload = sub_res.json()
        assert sub_payload["current_path"] == str(tmp_path.resolve())
        dir_names = [d["name"] for d in sub_payload["directories"]]
        assert dir_names == ["repo_alpha", "repo_beta", "runtime"]
        assert "secret.txt" not in dir_names

        missing = client.get("/workspace/browse", params={"path": str(tmp_path / "missing")}, headers=HEADERS)
        assert missing.status_code == 404
