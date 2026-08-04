import os
import shutil
import tempfile
import pytest
from fastapi.testclient import TestClient
from devwatch.tools.fix_applier import apply_code_fix
from devwatch.server import app

client = TestClient(app)


def test_apply_code_fix_function():
    temp_dir = tempfile.mkdtemp()
    try:
        sample_file = os.path.join(temp_dir, "vulnerable.py")
        vulnerable_code = "query = f'SELECT * FROM users WHERE name={name}'\n"
        with open(sample_file, "w", encoding="utf-8") as f:
            f.write(vulnerable_code)

        result = apply_code_fix(
            root_dir=temp_dir,
            file_path="vulnerable.py",
            line_number=1,
            target_snippet="query = f'SELECT * FROM users WHERE name={name}'",
            replacement_code="query = 'SELECT * FROM users WHERE name=%s'",
        )
        assert result is True

        with open(sample_file, "r", encoding="utf-8") as f:
            updated_content = f.read()
        assert "%s" in updated_content
        assert "f'SELECT" not in updated_content
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_apply_fix_api_endpoint():
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
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["modified"] is True

        with open(sample_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert "parse_user_input" in content
        assert "eval(" not in content
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_websocket_streaming_updates():
    with client.websocket_connect("/ws/review") as websocket:
        websocket.send_json({"target_path": "."})
        received_types = []
        while True:
            try:
                data = websocket.receive_json()
                msg_type = data.get("type")
                if msg_type:
                    received_types.append(msg_type)
                if msg_type == "review_completion" or data.get("status") in ("COMPLETED", "FAILED"):
                    break
            except Exception:
                break
        assert len(received_types) > 0
