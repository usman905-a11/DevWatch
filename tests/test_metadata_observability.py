"""Optional telemetry never receives source, prompts, evidence bodies or credentials."""
import asyncio
import importlib
import json
import time
from uuid import uuid4

from devwatch.review.jobs import EventStore, PersistedEvent


def test_metadata_export_is_opt_in_durable_bounded_and_payload_free(tmp_path):
    api = importlib.import_module("devwatch.review.observability")
    store = EventStore(tmp_path / "events.sqlite")
    event = PersistedEvent(event_id=uuid4().hex, job_id=uuid4().hex, sequence=1,
        kind="agent_completed", timestamp=time.time(), payload={"agent_id": "bug_reliability", "total_tokens": 42})
    store.append(event)
    calls = []
    class Client:
        def create_run(self, **kwargs):
            calls.append(kwargs)
    async def scenario():
        assert api.MetadataExporter(store).enabled is False
        assert await api.MetadataExporter(store).export_once() == 0
        exporter = api.MetadataExporter(store, client=Client(), project="local-tests")
        assert await exporter.export_once(limit=1) == 1
        assert await exporter.export_once(limit=1) == 0
        assert await api.MetadataExporter(store, client=Client(), project="local-tests").export_once() == 0
    asyncio.run(scenario())
    assert len(calls) == 1
    sent = calls[0]
    assert sent["inputs"] == sent["outputs"] == {}
    assert sent["extra"]["metadata"]["total_tokens"] == 42
    assert "evidence_ref" not in sent["extra"]["metadata"]
    assert "job_id" not in sent["extra"]["metadata"]
    assert sent["id"] == str(uuid4().__class__(event.event_id))
    assert json.dumps(sent, default=str)


def test_export_failure_is_classified_without_replaying_review_or_logging_error_text(tmp_path, caplog):
    api = importlib.import_module("devwatch.review.observability")
    store = EventStore(tmp_path / "events.sqlite")
    store.append(PersistedEvent(event_id=uuid4().hex, job_id=uuid4().hex, sequence=1,
        kind="tool_result", timestamp=time.time(), payload={"tool": "read_source", "evidence_ref": "private-evidence"}))
    class Client:
        def create_run(self, **kwargs):
            raise RuntimeError("secret-provider-detail")
    exporter = api.MetadataExporter(store, client=Client(), project="test")
    assert asyncio.run(exporter.export_once()) == 1
    assert asyncio.run(exporter.export_once()) == 0
    assert "telemetry_export_failed" in caplog.text
    assert "secret-provider-detail" not in caplog.text


def test_service_exports_only_when_explicitly_enabled(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from tests.test_review_service import app, submit, completed
    from devwatch.review import observability
    calls = []
    class Client:
        def create_run(self, **kwargs):
            calls.append(kwargs)
    monkeypatch.setattr(observability, "configured_metadata_client", lambda: Client())
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    with TestClient(app(tmp_path / "disabled")) as client:
        identity, _ = submit(client)
        completed(client, identity)
    assert calls == []
    with TestClient(app(tmp_path / "enabled", langsmith_metadata=True)) as client:
        identity, _ = submit(client)
        completed(client, identity)
        deadline = time.monotonic() + 3
        while not calls and time.monotonic() < deadline:
            time.sleep(.02)
    assert calls and all(call["inputs"] == call["outputs"] == {} for call in calls)
