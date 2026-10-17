import os
import shutil
import tempfile
import pytest
from fastapi.testclient import TestClient
from devwatch.config import Config
from devwatch.server import app

client = TestClient(app)



def test_apply_fix_api_endpoint_is_gone_and_does_not_modify_file(monkeypatch):
    monkeypatch.setattr(Config, "API_KEY", None)
    monkeypatch.delenv("DEVWATCH_API_KEY", raising=False)
    temp_dir = tempfile.mkdtemp()
    try:
        sample_file = os.path.join(temp_dir, "app.py")
        with open(sample_file, "w", encoding="utf-8") as f:
            f.write("def foo():\n    eval(user_input)\n")

        payload = {
            "root_path": temp_dir,
            "file_path": "app.py",
            "line_number": 2,
            "target_snippet": "eval(user_input)",
            "replacement_code": "parse_user_input(user_input)",
        }
        response = client.post("/api/review/apply-fix", json=payload)
        assert response.status_code == 410
        data = response.json()
        assert "report-only" in data["detail"]

        with open(sample_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert "parse_user_input" not in content
        assert "eval(" in content
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_websocket_streaming_updates(monkeypatch, tmp_path):
    from devwatch.models import AgentStepUpdate, ReviewReport
    from devwatch.routers import review, ws
    from devwatch.storage import ReportStorage

    monkeypatch.setattr(review, "report_storage", ReportStorage(str(tmp_path / "reports")))
    monkeypatch.setattr(Config, "API_KEY", None)
    monkeypatch.delenv("DEVWATCH_API_KEY", raising=False)

    async def audit(self, target_path, client_identity, client_ip, step_callback=None):
        step_callback(AgentStepUpdate(
            agent_name="Planner Agent", status="COMPLETED", message="Plan ready"
        ))
        return ReviewReport(target_path=target_path, summary="# Complete")

    monkeypatch.setattr(ws.ReviewOperations, "audit_repository", audit)
    with client.websocket_connect("/ws/review") as websocket:
        websocket.send_json({"target_path": "."})
        progress = websocket.receive_json()
        completion = websocket.receive_json()

    assert progress["type"] == "agent_update"
    assert progress["status"] == "COMPLETED"
    assert completion["type"] == "review_completion"
    assert completion["report"]["target_path"] == "."


