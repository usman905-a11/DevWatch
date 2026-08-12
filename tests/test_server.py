import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from devwatch.server import app
from devwatch.models import ReviewReport, CodeIssue, IssueSeverity

from devwatch.config import Config

client = TestClient(app)


@pytest.fixture(autouse=True)
def disable_api_key_for_tests(monkeypatch):
    monkeypatch.setattr(Config, "API_KEY", None)
    monkeypatch.delenv("DEVWATCH_API_KEY", raising=False)


mock_report = ReviewReport(
    target_path="test_path",
    issues=[
        CodeIssue(
            file_path="test.py",
            line_number=1,
            title="Hardcoded API Key",
            description="Found hardcoded secret key",
            severity=IssueSeverity.CRITICAL,
            category="SECURITY",
            suggestion="Use environment variable",
        )
    ]
)

def test_health_check_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

@patch("devwatch.routers.review.ReviewPipeline.execute", new_callable=AsyncMock)
def test_trigger_review_endpoint(mock_execute, tmp_path):
    mock_execute.return_value = mock_report
    (tmp_path / "test.py").write_text("SECRET_KEY = 'sk_live_1234567890abcdef'\n")
    
    response = client.post("/api/review", json={"target_path": str(tmp_path)})
    assert response.status_code == 200
    data = response.json()
    assert "report_id" in data
    assert data["status"] == "completed"
    assert data["report"]["total_issues"] >= 1

@patch("devwatch.routers.review.ReviewPipeline.execute", new_callable=AsyncMock)
def test_get_report_by_id(mock_execute, tmp_path):
    mock_execute.return_value = mock_report
    (tmp_path / "test.py").write_text("SECRET_KEY = 'sk_live_1234567890abcdef'\n")
    
    res = client.post("/api/review", json={"target_path": str(tmp_path)})
    report_id = res.json()["report_id"]
    
    res2 = client.get(f"/api/reports/{report_id}")
    assert res2.status_code == 200
    assert res2.json()["report_id"] == report_id
