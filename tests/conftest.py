import pytest


@pytest.fixture(autouse=True)
def disable_external_telemetry(monkeypatch):
    """Review providers are injected; ambient credentials must not export test data."""
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
