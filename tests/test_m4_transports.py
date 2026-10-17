"""M4 transport parity and disconnect behavior."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from devwatch.models import AgentStepUpdate, ReviewReport
from devwatch.config import Config
from devwatch.server import app
from devwatch.storage import ReportStorage


def test_websocket_review_uses_report_lookup_store(monkeypatch, tmp_path):
    from devwatch.routers import review, ws

    storage = ReportStorage(str(tmp_path / "reports"))
    monkeypatch.setattr(review, "report_storage", storage)

    async def audit(self, target_path, client_identity, client_ip, step_callback=None):
        step_callback(AgentStepUpdate(agent_name="planner", status="RUNNING", message="Planning"))
        return ReviewReport(target_path=target_path, summary="# Done")

    monkeypatch.setattr(ws.ReviewOperations, "audit_repository", audit)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/review") as socket:
            socket.send_json({"target_path": "."})
            progress = socket.receive_json()
            completion = socket.receive_json()
        assert progress["type"] == "agent_update"
        assert completion["type"] == "review_completion"
        assert completion["report_id"]
        stored = client.get(f"/api/reports/{completion['report_id']}")
        assert stored.status_code == 200
        assert stored.json()["report"] == completion["report"]


@pytest.mark.asyncio
async def test_quiet_websocket_disconnect_cancels_review(monkeypatch):
    from devwatch.routers import ws

    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def audit(self, target_path, client_identity, client_ip, step_callback=None):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    class Socket:
        client = None

        async def accept(self):
            pass

        async def receive_json(self):
            return {"target_path": "."}

        async def receive(self):
            await started.wait()
            return {"type": "websocket.disconnect"}

        async def send_json(self, payload):
            raise AssertionError(f"unexpected message: {payload}")

        async def close(self):
            pass

    async def authenticate(_socket):
        return "test-client"

    monkeypatch.setattr(ws, "authenticate_ws_connection", authenticate)
    monkeypatch.setattr(ws.ReviewOperations, "audit_repository", audit)
    await asyncio.wait_for(ws.websocket_review_endpoint(Socket()), timeout=2)
    assert cancelled.is_set()


@pytest.mark.parametrize("route", [
    "/api/review/propose-fix",
    "/api/review/apply-proposal",
    "/api/review/apply-fix",
    "/api/fs/write",
])
def test_retired_mutation_routes_always_return_gone(monkeypatch, tmp_path, route):
    monkeypatch.setattr(Config, "API_KEY", None)
    sample = tmp_path / "sample.py"
    sample.write_text("original\n", encoding="utf-8")

    with TestClient(app) as client:
        response = client.post(route, json={})

    assert response.status_code == 410
    assert "report-only" in response.json()["detail"]
    assert sample.read_text(encoding="utf-8") == "original\n"


@pytest.mark.parametrize("route", [
    "/api/review/propose-fix",
    "/api/review/apply-proposal",
    "/api/review/apply-fix",
    "/api/fs/write",
])
def test_retired_routes_keep_authentication(monkeypatch, route):
    monkeypatch.setattr(Config, "ENV", "production")
    monkeypatch.setattr(Config, "API_KEY", "test-secret")
    with TestClient(app) as client:
        response = client.post(route, json={})
    assert response.status_code in (401, 403)


def test_websocket_review_uses_existing_rate_limit(monkeypatch, tmp_path):
    from fastapi import HTTPException
    from devwatch import rate_limiter

    monkeypatch.setattr(Config, "API_KEY", None)
    def reject(*args, **kwargs):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    monkeypatch.setattr(rate_limiter.rate_limiter, "check_rate_limit", reject)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/review") as socket:
            socket.send_json({"target_path": str(tmp_path)})
            error = socket.receive_json()

    assert error["type"] == "review_error"
    assert "Rate limit exceeded" in error["message"]
