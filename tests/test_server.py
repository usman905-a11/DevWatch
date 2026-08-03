import pytest
from fastapi.testclient import TestClient
from devwatch.server import app

client = TestClient(app)

def test_health_check_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_trigger_review_endpoint(tmp_path):
    (tmp_path / "test.py").write_text("SECRET_KEY = 'sk_live_1234567890abcdef'\n")
    
    response = client.post("/api/review", json={"target_path": str(tmp_path)})
    assert response.status_code == 200
    data = response.json()
    assert "report_id" in data
    assert data["status"] == "completed"
    assert data["report"]["total_issues"] >= 1

def test_get_report_by_id(tmp_path):
    (tmp_path / "test.py").write_text("SECRET_KEY = 'sk_live_1234567890abcdef'\n")
    
    # Run review first
    res = client.post("/api/review", json={"target_path": str(tmp_path)})
    report_id = res.json()["report_id"]
    
    # Fetch report
    res2 = client.get(f"/api/reports/{report_id}")
    assert res2.status_code == 200
    assert res2.json()["report_id"] == report_id
