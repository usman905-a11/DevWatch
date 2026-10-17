"""The job client validates service responses and never owns worker lifetime."""
import importlib
import io
import json
from urllib.error import URLError

import pytest
from fastapi.testclient import TestClient

from tests.test_review_service import ALICE, app


class Transport:
    def __init__(self, client):
        self.client, self.requests = client, []
    def __call__(self, request, timeout):
        self.requests.append(request)
        response = self.client.request(request.method, request.full_url, headers=dict(request.header_items()), content=request.data)
        stream = io.BytesIO(response.content)
        stream.status, stream.headers = response.status_code, response.headers
        return stream


def client_api():
    return importlib.import_module("devwatch.review.client")


def test_client_submits_snapshot_once_polls_and_downloads_validated_report(tmp_path):
    capture = importlib.import_module("devwatch.review.capture").CapturedSource(
        root=tmp_path, files={"service.py": "def first(items):\n    return items[0]\n"},
        changed_files=["service.py"], scope_kind="directory")
    api = client_api()
    with TestClient(app(tmp_path)) as http:
        transport = Transport(http)
        client = api.ReviewClient("http://testserver", api_key=ALICE["X-API-Key"], opener=transport)
        snapshot = client.capture(capture)
        pending = client.submit(snapshot.snapshot_id, capture.changed_files, idempotency_key="stable-intent")
        duplicate = client.submit(snapshot.snapshot_id, capture.changed_files, idempotency_key="stable-intent")
        assert duplicate.job_id == pending.job_id
        complete = client.wait(pending.job_id, wait_seconds=5, poll_seconds=.01)
        assert complete.status == "completed"
        report = client.report(complete, format="json")
        assert json.loads(report)["snapshot_id"] == snapshot.snapshot_id
        assert "Uncertain" in client.report(complete, format="markdown")
        assert sum(request.full_url.endswith("/api/snapshots") for request in transport.requests) == 1
        assert all("api_key=" not in request.full_url for request in transport.requests)
        assert client.status(pending.job_id).job_id == pending.job_id
        assert client.cancel(pending.job_id).status == "completed"


def test_client_errors_do_not_echo_server_payload_or_credentials(tmp_path):
    api = client_api()
    def failure(request, timeout):
        stream = io.BytesIO(b'{"detail":"raw-secret-source"}')
        stream.status, stream.headers = 401, {"content-type": "application/json"}
        return stream
    client = api.ReviewClient("http://localhost:8000", api_key="private-key", opener=failure)
    with pytest.raises(api.ClientError) as error:
        client.status("a" * 32)
    assert "raw-secret" not in str(error.value) and "private-key" not in str(error.value)


def test_unknown_submission_is_not_retried(tmp_path):
    api, attempts = client_api(), []
    def unknown(request, timeout):
        attempts.append(request)
        raise URLError("raw-secret-in-transport-error")
    client = api.ReviewClient("http://localhost:8000", opener=unknown)
    with pytest.raises(api.ClientError) as error:
        client.submit("a" * 32, [], idempotency_key="stable-key")
    assert len(attempts) == 1
    assert "raw-secret" not in str(error.value)


def test_service_urls_and_identifiers_are_validated_before_io():
    api = client_api()
    for url in ("ftp://localhost", "http://user:secret@localhost", "http://localhost?key=secret", "http://localhost/#secret"):
        with pytest.raises(ValueError):
            api.ReviewClient(url)
    client = api.ReviewClient("http://localhost:8000", opener=lambda *args: pytest.fail("invalid ID reached I/O"))
    for identity in ("../other", "?api_key=secret", "not-a-uuid"):
        with pytest.raises(ValueError):
            client.status(identity)


@pytest.mark.parametrize("body", [b"not-json", b'{"job_id":"wrong"}', b"x" * 1_000_001], ids=["bad-json", "bad-schema", "oversized"])
def test_invalid_or_unbounded_service_response_is_rejected(body):
    api = client_api()
    def response(request, timeout):
        stream = io.BytesIO(body)
        stream.status, stream.headers = 200, {"content-type": "application/json"}
        return stream
    with pytest.raises(api.ClientError):
        api.ReviewClient("http://localhost:8000", opener=response).status("a" * 32)


def test_poll_timeout_leaves_job_running_and_does_not_cancel_it(tmp_path):
    import asyncio
    from tests.test_canonical_workflow import ReviewProvider
    api = client_api()
    class PausedProvider(ReviewProvider):
        async def generate_completion(self, request):
            await asyncio.Event().wait()
    with TestClient(app(tmp_path, PausedProvider())) as http:
        transport = Transport(http)
        client = api.ReviewClient("http://testserver", api_key=ALICE["X-API-Key"], opener=transport)
        snapshot = http.post("/api/snapshots", headers=ALICE, json={"files": {"service.py": "pass\n"}}).json()
        job = client.submit(snapshot["snapshot_id"], ["service.py"], idempotency_key="wait-timeout")
        with pytest.raises(api.ClientWaitTimeout):
            client.wait(job.job_id, wait_seconds=.05, poll_seconds=.01)
        assert client.status(job.job_id).status == "running"
        assert all(not request.full_url.endswith("/cancel") for request in transport.requests)
