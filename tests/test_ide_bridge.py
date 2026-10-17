"""IDE bridge uses the actual owned service, retains intent and never changes source."""
import importlib
import json
from fastapi.testclient import TestClient
import pytest

from devwatch.review.client import ReviewClient
from tests.test_review_client import Transport
from tests.test_review_service import ALICE, app, completed


def test_bridge_capture_submit_replay_source_and_report_use_one_durable_job(tmp_path):
    bridge = importlib.import_module("devwatch.ide_bridge")
    source = tmp_path / "service.py"
    source.write_text("def first(items):\n    return items[0]\n")
    original = source.read_bytes()
    with TestClient(app(tmp_path)) as http:
        client = ReviewClient(api_key=ALICE["X-API-Key"], opener=Transport(http))
        captured = bridge.dispatch({"action": "capture", "root": str(source)}, client=client)
        intent = captured["intent"]
        assert intent["changed_files"] == ["service.py"]
        created = bridge.dispatch({"action": "submit", "intent": intent}, client=client)
        assert bridge.dispatch({"action": "submit", "intent": intent}, client=client)["job_id"] == created["job_id"]
        identity = created["job_id"]
        completed(http, identity)
        history = bridge.dispatch({"action": "events", "job_id": identity, "after": 0}, client=client)
        assert any(event["kind"] == "job_completed" for event in history["events"])
        reference = next(event["payload"]["evidence_ref"] for event in history["events"] if event["payload"]["evidence_ref"])
        evidence = bridge.dispatch({"action": "evidence", "job_id": identity, "evidence_ref": reference}, client=client)
        assert evidence["snapshot_id"] == intent["snapshot_id"]
        assert bridge.dispatch({"action": "events", "job_id": identity, "after": history["next_cursor"]}, client=client)["events"] == []
        manifest = bridge.dispatch({"action": "snapshot", "job_id": identity}, client=client)
        assert "service.py" in manifest["entries"]
        excerpt = bridge.dispatch({"action": "source", "job_id": identity, "file_path": "service.py", "start_line": 1, "end_line": 2}, client=client)
        assert excerpt["data"] == "\n".join(original.decode().splitlines())
        from hashlib import sha256
        assert excerpt["content_hash"] == sha256(original).hexdigest()
        report = bridge.dispatch({"action": "report", "job_id": identity, "format": "json"}, client=client)
        assert json.loads(report["text"])["snapshot_id"] == intent["snapshot_id"]
        pdf = bridge.dispatch({"action": "report", "job_id": identity, "format": "pdf"}, client=client)
        import base64
        assert base64.b64decode(pdf["base64"]).startswith(b"%PDF-")
    assert source.read_bytes() == original


def test_bridge_rejects_dynamic_commands_destinations_and_unrelated_arguments():
    bridge = importlib.import_module("devwatch.ide_bridge")
    for payload in ({"action": "run_command", "argv": ["anything"]},
        {"action": "source", "job_id": "a" * 32, "file_path": "../private.py"},
        {"action": "report", "job_id": "a" * 32, "destination": "workspace.py"},
        {"action": "submit", "intent": {"snapshot_id": "a" * 32, "idempotency_key": "intent"}, "root": "."}):
        with pytest.raises(ValueError):
            bridge.BridgeRequest.model_validate(payload)
