import os
import pytest
from fastapi.testclient import TestClient
from devwatch.config import Config
from devwatch.server import app
from devwatch.rate_limiter import rate_limiter
from devwatch.auth import verify_report_access

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_security_env(monkeypatch):
    orig_env = Config.ENV
    orig_key = Config.API_KEY
    rate_limiter.reset()
    yield
    monkeypatch.setattr(Config, "ENV", orig_env)
    monkeypatch.setattr(Config, "API_KEY", orig_key)
    rate_limiter.reset()


def test_production_fails_closed_when_api_key_missing(monkeypatch):
    monkeypatch.setattr(Config, "ENV", "production")
    monkeypatch.setattr(Config, "API_KEY", None)
    monkeypatch.delenv("DEVWATCH_API_KEY", raising=False)
    monkeypatch.setenv("DEVWATCH_ENV", "production")

    with pytest.raises(RuntimeError) as exc_info:
        Config.validate_security_config()
    assert "CRITICAL SECURITY FAILURE" in str(exc_info.value)


def test_missing_credentials_returns_401(monkeypatch):
    monkeypatch.setattr(Config, "ENV", "production")
    monkeypatch.setattr(Config, "API_KEY", "secret_key_123")

    response = client.get("/api/fs/tree")
    assert response.status_code == 401
    assert "Invalid or missing" in response.json()["detail"]


def test_invalid_credentials_returns_401(monkeypatch):
    monkeypatch.setattr(Config, "ENV", "development")
    monkeypatch.setattr(Config, "API_KEY", "valid_secret_key")

    response = client.get("/api/fs/tree", headers={"x-api-key": "wrong_key"})
    assert response.status_code == 401
    assert "Invalid or missing" in response.json()["detail"]


def test_valid_x_api_key_header(monkeypatch):
    monkeypatch.setattr(Config, "ENV", "development")
    monkeypatch.setattr(Config, "API_KEY", "valid_secret_key")

    response = client.get("/api/fs/tree?root=.", headers={"x-api-key": "valid_secret_key"})
    assert response.status_code == 200
    assert "tree" in response.json()


def test_valid_bearer_token_authorization_header(monkeypatch):
    monkeypatch.setattr(Config, "ENV", "development")
    monkeypatch.setattr(Config, "API_KEY", "valid_secret_key")

    response = client.get("/api/fs/tree?root=.", headers={"Authorization": "Bearer valid_secret_key"})
    assert response.status_code == 200
    assert "tree" in response.json()


def test_rate_limiting_enforcement(monkeypatch):
    monkeypatch.setattr(Config, "ENV", "development")
    monkeypatch.setattr(Config, "API_KEY", None)
    monkeypatch.setattr(Config, "RATE_LIMIT_RPM", 3)

    # First 3 requests succeed
    for _ in range(3):
        res = client.get("/api/fs/tree?root=.")
        assert res.status_code == 200

    # 4th request triggers rate limit HTTP 429
    res = client.get("/api/fs/tree?root=.")
    assert res.status_code == 429
    assert "Rate limit exceeded" in res.json()["detail"]
    assert "Retry-After" in res.headers


def test_unauthorized_websocket_closed(monkeypatch):
    monkeypatch.setattr(Config, "ENV", "production")
    monkeypatch.setattr(Config, "API_KEY", "secret_key_123")

    with pytest.raises(Exception):
        with client.websocket_connect("/ws/review") as websocket:
            pass


def test_authorized_websocket_connects(monkeypatch):
    monkeypatch.setattr(Config, "ENV", "development")
    monkeypatch.setattr(Config, "API_KEY", "valid_secret_key")

    with client.websocket_connect("/ws/review", headers={"x-api-key": "valid_secret_key"}) as websocket:
        assert websocket is not None


def test_report_authorization_ownership_check(monkeypatch):
    monkeypatch.setattr(Config, "ENV", "production")

    report_data = {"report_id": "rep_123", "owner": "user:owner_1"}
    
    # Same owner passes
    verify_report_access(report_data, "user:owner_1")

    # Different owner in production raises HTTP 403
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        verify_report_access(report_data, "user:attacker_2")
    assert exc_info.value.status_code == 403
    assert "Access denied" in exc_info.value.detail
