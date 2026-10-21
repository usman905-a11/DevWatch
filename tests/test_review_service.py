"""Real local-service transports over the canonical durable graph and stores."""
import importlib
import threading
import time

import pytest
from fastapi.testclient import TestClient

from tests.test_canonical_workflow import ReviewProvider
from tests.test_control_agents import MODELS


ALICE = {"X-API-Key": "alice-test-key"}
BOB = {"X-API-Key": "bob-test-key"}


def app(tmp_path, provider=None, **settings):
    service = importlib.import_module("devwatch.review.service")
    return service.create_app(provider=provider or ReviewProvider(), settings=service.ServiceSettings(
        runtime_root=tmp_path / "runtime", models=MODELS,
        api_keys=frozenset({ALICE["X-API-Key"], BOB["X-API-Key"]}), **settings))


def submit(client, *, key="job-one", snapshot=None, headers=ALICE):
    if snapshot is None:
        response = client.post("/api/snapshots", headers=headers,
                               json={"files": {"service.py": "def first(items):\n    return items[0]\n"}})
        assert response.status_code == 201, response.text
        snapshot = response.json()["snapshot_id"]
    response = client.post("/api/jobs", headers={**headers, "Idempotency-Key": key},
                           json={"snapshot_id": snapshot})
    assert response.status_code == 202, response.text
    return response.json()["job_id"], snapshot


def completed(client, identity):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{identity}", headers=ALICE)
        assert response.status_code == 200
        if response.json()["status"] not in {"running", "queued"}:
            return response.json()
        time.sleep(.01)
    history = client.get(f"/api/jobs/{identity}/events?limit=1000", headers=ALICE).json()
    kinds = [event["kind"] for event in history.get("events", [])][-10:]
    pytest.fail(f"durable job did not complete: status={response.json()['status']}; recent event kinds={kinds}")


def test_submit_is_idempotent_and_reports_are_deterministic(tmp_path):
    provider = ReviewProvider()
    with TestClient(app(tmp_path, provider)) as client:
        identity, snapshot = submit(client)
        repeated, _ = submit(client, snapshot=snapshot)
        assert identity == repeated
        status = completed(client, identity)
        assert status["status"] == "completed"
        assert status["limits"]["review_seconds"] == 600
        assert "owner" not in status
        first = client.get(f"/api/jobs/{identity}/report", headers=ALICE)
        assert first.status_code == 200
        assert first.json()["snapshot_id"] == snapshot
        assert client.get(f"/api/jobs/{identity}/report", headers=ALICE).content == first.content
        markdown = client.get(f"/api/jobs/{identity}/report?format=markdown", headers=ALICE)
        assert "text/markdown" in markdown.headers["content-type"]
        assert "Uncertain" in markdown.text
        assert len(provider.requests) == 4
        assert len(list((tmp_path / "runtime").glob("*.sqlite"))) == 4


def test_pdf_download_is_finalized_owned_and_persisted_as_an_artifact(tmp_path):
    import pymupdf
    with TestClient(app(tmp_path)) as client:
        identity, snapshot = submit(client)
        assert completed(client, identity)["status"] == "completed"
        pdf = client.get(f"/api/jobs/{identity}/report?format=pdf", headers=ALICE)
        assert pdf.status_code == 200, pdf.text
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.headers["cache-control"] == "no-store"
        assert pdf.headers["x-content-type-options"] == "nosniff"
        assert pdf.headers["content-disposition"] == f'attachment; filename="devwatch-{identity}.pdf"'
        assert client.get(f"/api/jobs/{identity}/report?format=pdf", headers=ALICE).content == pdf.content
        assert client.get(f"/api/jobs/{identity}/report?format=pdf", headers=BOB).status_code == 404
        with pymupdf.open(stream=pdf.content, filetype="pdf") as document:
            text = "".join(page.get_text() for page in document)
            assert snapshot in text and "Uncertain high-impact candidates (1)" in text
            assert all(any(block[1] < page.rect.height - 48 for block in page.get_text("blocks")) for page in document), "PDF has an empty body page"
        files = list((tmp_path / "runtime" / "artifacts" / "reports").glob("**/*.pdf"))
        assert len(files) == 1 and files[0].read_bytes() == pdf.content


def test_owner_checks_cover_job_report_events_source_and_snapshot(tmp_path):
    with TestClient(app(tmp_path)) as client:
        identity, snapshot = submit(client)
        completed(client, identity)
        for suffix in ("", "/snapshot", "/report", "/events", "/stream", "/source?file_path=service.py", "/cancel", "/resume"):
            method = client.post if suffix in {"/cancel", "/resume"} else client.get
            assert method(f"/api/jobs/{identity}{suffix}", headers=BOB).status_code == 404
        response = client.post("/api/jobs", headers={**BOB, "Idempotency-Key": "alien"}, json={"snapshot_id": snapshot})
        assert response.status_code == 404
        assert client.get(f"/api/jobs/{identity}").status_code == 401


def test_job_snapshot_catalog_is_owned_immutable_and_contains_no_source(tmp_path):
    with TestClient(app(tmp_path)) as client:
        identity, snapshot = submit(client)
        response = client.get(f"/api/jobs/{identity}/snapshot", headers=ALICE)
        assert response.status_code == 200
        manifest = response.json()
        assert manifest["snapshot_id"] == snapshot
        assert manifest["entries"]["service.py"]["line_count"] == 2
        assert "return items[0]" not in response.text
        completed(client, identity)
        assert client.get(f"/api/jobs/{identity}/snapshot", headers=ALICE).json() == manifest


def test_sse_and_websocket_replay_identical_persisted_stream(tmp_path):
    with TestClient(app(tmp_path)) as client:
        identity, _ = submit(client)
        completed(client, identity)
        page = client.get(f"/api/jobs/{identity}/events?after=1&limit=100", headers=ALICE).json()
        events = page["events"]
        assert events and all(event["sequence"] > 1 for event in events)
        stream = client.get(f"/api/jobs/{identity}/stream", headers={**ALICE, "Last-Event-ID": "1"})
        assert stream.status_code == 200
        assert "text/event-stream" in stream.headers["content-type"]
        assert "id: 1\n" not in stream.text
        for event in events:
            assert f"id: {event['sequence']}\n" in stream.text
            assert f"event: {event['kind']}\n" in stream.text
        with client.websocket_connect(f"/api/jobs/{identity}/ws?after=1", headers=ALICE) as socket:
            replayed = [socket.receive_json() for _ in events]
            assert replayed == events


def test_websocket_disconnect_does_not_cancel_durable_job(tmp_path):
    import asyncio
    entered, release = threading.Event(), threading.Event()
    class PausedProvider(ReviewProvider):
        async def generate_completion(self, request):
            entered.set()
            while not release.is_set():
                await asyncio.sleep(.01)
            return await super().generate_completion(request)
    with TestClient(app(tmp_path, PausedProvider())) as client:
        identity, _ = submit(client)
        assert entered.wait(3)
        with client.websocket_connect(f"/api/jobs/{identity}/ws", headers=ALICE) as socket:
            assert socket.receive_json()["kind"] == "job_queued"
        assert client.get(f"/api/jobs/{identity}", headers=ALICE).json()["status"] == "running"
        assert client.get(f"/api/jobs/{identity}/report?format=pdf", headers=ALICE).status_code == 409
        release.set()
        assert completed(client, identity)["status"] == "completed"


def test_invalid_requests_and_paths_have_safe_bounded_errors(tmp_path):
    with TestClient(app(tmp_path)) as client:
        identity, snapshot = submit(client)
        completed(client, identity)
        assert client.get(f"/api/jobs/{identity}/events?after=-1", headers=ALICE).status_code == 422
        assert client.get(f"/api/jobs/{identity}/events?after={2**63}", headers=ALICE).status_code == 422
        assert client.get(f"/api/jobs/{identity}/stream?after={2**63}", headers=ALICE).status_code == 422
        assert client.get(f"/api/jobs/{identity}/stream", headers={**ALICE, "Last-Event-ID": "secret-invalid"}).status_code == 422
        assert client.get(f"/api/jobs/{identity}/source?file_path=../secret", headers=ALICE).status_code == 422
        assert client.get(f"/api/jobs/{identity}/source?file_path=service.py&end_line=500", headers=ALICE).status_code == 422
        source = client.get(f"/api/jobs/{identity}/source?file_path=service.py", headers=ALICE)
        assert source.status_code == 200 and "return items[0]" in source.text
        assert client.post("/api/jobs", headers=ALICE, json={"snapshot_id": snapshot}).status_code == 422
        assert client.post("/api/jobs", headers={**ALICE, "Idempotency-Key": "job-one"},
            json={"snapshot_id": snapshot, "changed_files": []}).status_code == 409
        bad = client.post("/api/snapshots", headers=ALICE, json={"files": {".env": "secret-value"}})
        assert bad.status_code == 422 and "secret-value" not in bad.text


def test_explicit_cancel_and_shutdown_resume_preserve_job_identity(tmp_path):
    import asyncio
    entered = threading.Event()
    class PausedProvider(ReviewProvider):
        async def generate_completion(self, request):
            entered.set()
            await asyncio.Event().wait()
    application = app(tmp_path, PausedProvider())
    with TestClient(application) as client:
        identity, _ = submit(client)
        assert entered.wait(3)
    with TestClient(app(tmp_path)) as client:
        before = client.get(f"/api/jobs/{identity}", headers=ALICE).json()
        assert before["status"] == "interrupted"
        assert before["ledger"]["task_iterations"]["__planner"] == 1
        response = client.post(f"/api/jobs/{identity}/resume", headers=ALICE)
        assert response.status_code == 202
        assert completed(client, identity)["status"] == "completed"
        assert client.post(f"/api/jobs/{identity}/resume", headers=ALICE).status_code == 409
        next_job, _ = submit(client, key="cancel")
        cancelled = client.post(f"/api/jobs/{next_job}/cancel", headers=ALICE)
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"


def test_websocket_auth_is_header_or_first_message_never_url(tmp_path):
    from starlette.websockets import WebSocketDisconnect
    with TestClient(app(tmp_path)) as client:
        identity, _ = submit(client)
        completed(client, identity)
        with client.websocket_connect(f"/api/jobs/{identity}/ws") as socket:
            socket.send_json({"api_key": ALICE["X-API-Key"]})
            assert socket.receive_json()["kind"] == "job_queued"
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/api/jobs/{identity}/ws?api_key={ALICE['X-API-Key']}") as socket:
                socket.receive_json()
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/api/jobs/{identity}/ws", headers={**ALICE, "Origin": "https://alien.invalid"}) as socket:
                socket.receive_json()
        with pytest.raises(WebSocketDisconnect) as rejected:
            with client.websocket_connect(f"/api/jobs/{identity}/ws") as socket:
                socket.send_bytes(b"binary credentials")
                socket.receive_json()
        assert rejected.value.code == 1008


def test_service_requires_explicit_model_tiers_and_production_auth(tmp_path, monkeypatch):
    service = importlib.import_module("devwatch.review.service")
    with pytest.raises(ValueError):
        service.ServiceSettings(runtime_root=tmp_path, models={})
    with pytest.raises(ValueError):
        service.ServiceSettings(runtime_root=tmp_path, models=MODELS, production=True)
    for tier in ("SMALL", "MEDIUM", "STRONG"):
        monkeypatch.setenv(f"DEVWATCH_MODEL_{tier}", tier.lower() + "-configured")
    monkeypatch.setenv("DEVWATCH_ENV", "development")
    settings = service.ServiceSettings.from_env()
    assert all(name.endswith("-configured") for name in settings.models.values())


def test_chunked_body_is_bounded_and_unicode_credentials_are_rejected(tmp_path):
    with TestClient(app(tmp_path, max_request_bytes=128)) as client:
        too_large = client.post("/api/snapshots", headers=ALICE,
            content=(part for part in (b'{"files": {"service.py": "', b"x" * 150, b'"}}')))
        assert too_large.status_code == 413
        malformed = client.get("/api/jobs/missing", headers={"X-API-Key": b"\xc3\xa9"})
        assert malformed.status_code == 401


def test_event_store_rejects_oversized_cursor_before_sqlite_binding(tmp_path):
    from devwatch.review.jobs import EventStore
    store = EventStore(tmp_path / "events.sqlite")
    with pytest.raises(ValueError):
        store.replay("missing", after=2**63)


def test_asgi_disconnect_drains_viewer_without_waiting_for_job(tmp_path):
    import asyncio
    async def scenario():
        service = importlib.import_module("devwatch.review.service")
        settings = service.ServiceSettings(runtime_root=tmp_path, models=MODELS, api_keys=frozenset({ALICE["X-API-Key"]}))
        class PausedProvider(ReviewProvider):
            async def generate_completion(self, request):
                await asyncio.Event().wait()
        application = service.create_app(settings=settings, provider=PausedProvider())
        async with application.router.lifespan_context(application):
            owner = settings.principal({"x-api-key": ALICE["X-API-Key"]}, client_host="127.0.0.1")
            snapshot = application.state.artifacts.capture(owner=owner, files={"service.py": "pass\n"})
            job = await application.state.manager.submit(owner=owner, request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="disconnect")
            incoming, outgoing = asyncio.Queue(), asyncio.Queue()
            await incoming.put({"type": "websocket.connect"})
            scope = {"type": "websocket", "asgi": {"version": "3.0"}, "scheme": "ws", "path": f"/api/jobs/{job.job_id}/ws",
                "raw_path": b"", "query_string": b"", "root_path": "", "headers": [(b"x-api-key", ALICE["X-API-Key"].encode())],
                "client": ("127.0.0.1", 1234), "server": ("127.0.0.1", 8000), "subprotocols": [], "state": {}}
            connection = asyncio.create_task(application(scope, incoming.get, outgoing.put))
            assert (await asyncio.wait_for(outgoing.get(), 2))["type"] == "websocket.accept"
            assert (await asyncio.wait_for(outgoing.get(), 2))["type"] == "websocket.send"
            await incoming.put({"type": "websocket.disconnect", "code": 1000})
            done, _ = await asyncio.wait({connection}, timeout=.5)
            if not done:
                connection.cancel()
                await asyncio.gather(connection, return_exceptions=True)
            assert done, "Viewer did not terminate on disconnect"
            assert application.state.jobs.get(job.job_id, owner=owner).status == "running"
    asyncio.run(scenario())
