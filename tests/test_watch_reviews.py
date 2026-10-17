"""Watch uses real captures, owned durable jobs and one pending source version."""
import asyncio
import importlib
import json
import threading
from urllib.error import URLError

import pytest
from fastapi.testclient import TestClient

from devwatch.review.capture import capture_source
from devwatch.review.client import ClientError, ReviewClient
from tests.test_canonical_workflow import ReviewProvider
from tests.test_review_client import Transport
from tests.test_review_service import ALICE, app
from tests.test_source_capture import commit, git, repository


def watcher(client, **options):
    assert importlib.util.find_spec("devwatch.review.watch"), "Canonical watcher is missing"
    return importlib.import_module("devwatch.review.watch").WatchReviewer(client, **options)


def client(http):
    transport = Transport(http)
    return ReviewClient("http://testserver", api_key=ALICE["X-API-Key"], opener=transport), transport


def test_debounce_submits_only_the_latest_stable_bytes(tmp_path):
    source = tmp_path / "service.py"
    source.write_text("def first(items):\n    return items[0]\n")
    with TestClient(app(tmp_path)) as http:
        api, transport = client(http)
        watch = watcher(api, debounce_seconds=.5)
        assert watch.poll(capture_source(source), now=0) is None
        source.write_text("def first(items):\n    return items[-1]\n")
        assert watch.poll(capture_source(source), now=.2) is None
        assert watch.poll(capture_source(source), now=.6) is None
        assert not transport.requests
        job = watch.poll(capture_source(source), now=.8)
        assert job is not None
        excerpt = http.get(f"/api/jobs/{job.job_id}/source?file_path=service.py", headers=ALICE).json()
        assert "return items[-1]" in excerpt["data"]
        assert sum(request.full_url.endswith("/api/jobs") for request in transport.requests) == 1


def test_running_job_coalesces_edits_without_cancellation_or_duplicate_submission(tmp_path):
    release, entered = threading.Event(), threading.Event()
    class HeldProvider(ReviewProvider):
        async def generate_completion(self, request):
            entered.set()
            while not release.is_set():
                await asyncio.sleep(.01)
            return await super().generate_completion(request)
    source = tmp_path / "service.py"
    source.write_text("def first(items):\n    return items[0]\n")
    with TestClient(app(tmp_path, HeldProvider())) as http:
        api, transport = client(http)
        watch = watcher(api, debounce_seconds=0)
        first = watch.poll(capture_source(source), now=0)
        assert first and entered.wait(3)
        try:
            source.write_text("def first(items):\n    return items[-1]\n")
            assert watch.poll(capture_source(source), now=1) is None
            source.write_text("def first(items):\n    return items[2]\n")
            assert watch.poll(capture_source(source), now=2) is None
            assert sum(request.full_url.endswith("/api/jobs") for request in transport.requests) == 1
        finally:
            release.set()
        assert api.wait(first.job_id, wait_seconds=8, poll_seconds=.01).status == "completed"
        second = watch.poll(capture_source(source), now=3)
        assert second and second.job_id != first.job_id
        new = http.get(f"/api/jobs/{second.job_id}/source?file_path=service.py", headers=ALICE).json()
        old = http.get(f"/api/jobs/{first.job_id}/source?file_path=service.py", headers=ALICE).json()
        assert "return items[2]" in new["data"] and "return items[0]" in old["data"]
        assert watch.poll(capture_source(source), now=4) is None
        assert sum(request.full_url.endswith("/api/jobs") for request in transport.requests) == 2
        assert not any(request.full_url.endswith(("/cancel", "/resume")) for request in transport.requests)


def test_unknown_accepted_post_blocks_recapture_and_preserves_exact_retry_intent(tmp_path):
    source = tmp_path / "service.py"
    source.write_text("pass\n")
    with TestClient(app(tmp_path)) as http:
        transport = Transport(http)
        accepted = []
        def lost_response(request, timeout):
            response = transport(request, timeout)
            if request.method == "POST" and request.full_url.endswith("/api/jobs"):
                accepted.append(json.loads(response.read()))
                response.close()
                raise URLError("lost response after acceptance")
            return response
        api = ReviewClient("http://testserver", api_key=ALICE["X-API-Key"], opener=lost_response)
        intents = []
        watch = watcher(api, debounce_seconds=0, on_intent=intents.append)
        with pytest.raises(ClientError):
            watch.poll(capture_source(source), now=0)
        intent = dict(watch.intent)
        assert intents == [intent]
        source.write_text("changed = True\n")
        with pytest.raises(ClientError):
            watch.poll(capture_source(source), now=1)
        assert watch.intent == intent
        assert len(transport.requests) == 2  # One capture, one accepted POST; no automatic retry.
        recovery = ReviewClient("http://testserver", api_key=ALICE["X-API-Key"], opener=transport)
        job = recovery.submit(intent["snapshot_id"], intent["changed_files"], idempotency_key=intent["idempotency_key"])
        assert job.job_id == accepted[0]["job_id"]


def test_clean_git_skips_jobs_but_deleted_only_scope_reports_omissions_without_models(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    repository(root)
    (root / "service.py").write_text("pass\n")
    commit(root)
    provider = ReviewProvider()
    with TestClient(app(tmp_path, provider)) as http:
        api, transport = client(http)
        watch = watcher(api, debounce_seconds=0)
        assert watch.poll(capture_source(root), now=0) is None
        assert not transport.requests
        git(root, "rm", "service.py")
        job = watch.poll(capture_source(root), now=1)
        assert job is not None
        complete = api.wait(job.job_id, wait_seconds=8, poll_seconds=.01)
        report = json.loads(api.report(complete, format="json"))
        assert report["coverage"]["skipped"]["service.py"] == "deleted_source_unavailable"
        assert report["coverage"]["inspected_files"] == []
        assert not provider.requests


def test_directory_deletion_survives_debounce_and_is_reported_once(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    source = root / "service.py"
    source.write_text("def first(items):\n    return items[0]\n")
    provider = ReviewProvider()
    with TestClient(app(tmp_path, provider)) as http:
        api, transport = client(http)
        watch = watcher(api, debounce_seconds=.1)
        assert watch.poll(capture_source(root), now=0) is None
        first = watch.poll(capture_source(root), now=.2)
        api.wait(first.job_id, wait_seconds=8, poll_seconds=.01)
        calls = len(provider.requests)
        source.unlink()
        assert watch.poll(capture_source(root), now=1) is None
        second = watch.poll(capture_source(root), now=1.2)
        complete = api.wait(second.job_id, wait_seconds=8, poll_seconds=.01)
        report = json.loads(api.report(complete, format="json"))
        assert report["coverage"]["skipped"]["service.py"] == "deleted_source_unavailable"
        assert len(provider.requests) == calls
        assert watch.poll(capture_source(root), now=2) is None
        assert sum(request.full_url.endswith("/api/jobs") for request in transport.requests) == 2


def test_sensitive_or_generated_content_edits_do_not_trigger_new_source_versions(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "service.py").write_text("def first(items):\n    return items[0]\n")
    (root / ".env").write_text("PRIVATE_KEY=first-secret")
    (root / "dist").mkdir()
    (root / "dist" / "bundle.js").write_text("generated one")
    with TestClient(app(tmp_path)) as http:
        api, transport = client(http)
        watch = watcher(api, debounce_seconds=0)
        job = watch.poll(capture_source(root), now=0)
        api.wait(job.job_id, wait_seconds=8, poll_seconds=.01)
        (root / ".env").write_text("PRIVATE_KEY=second-secret")
        (root / "dist" / "bundle.js").write_text("generated two")
        assert watch.poll(capture_source(root), now=1) is None
        assert sum(request.full_url.endswith("/api/jobs") for request in transport.requests) == 1
        assert all(b"second-secret" not in (request.data or b"") for request in transport.requests)


def test_interrupted_job_stops_watch_until_explicit_operator_action(tmp_path):
    entered = threading.Event()
    class HeldProvider(ReviewProvider):
        async def generate_completion(self, request):
            entered.set()
            await asyncio.Event().wait()
    source = tmp_path / "service.py"
    source.write_text("pass\n")
    with TestClient(app(tmp_path, HeldProvider())) as http:
        api, _ = client(http)
        watch = watcher(api, debounce_seconds=0)
        job = watch.poll(capture_source(source), now=0)
        assert entered.wait(3)
    with TestClient(app(tmp_path)) as restarted:
        api, transport = client(restarted)
        watch.client = api
        source.write_text("updated = True\n")
        with pytest.raises(ClientError, match="interrupted"):
            watch.poll(capture_source(source), now=1)
        assert watch.active_job.job_id == job.job_id
        assert all(request.method == "GET" for request in transport.requests)


def test_deletion_is_retained_after_an_intermediate_capture_omission(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    source = root / "service.py"
    source.write_text("def first(items):\n    return items[0]\n")
    with TestClient(app(tmp_path)) as http:
        api, _ = client(http)
        watch = watcher(api, debounce_seconds=0)
        first = watch.poll(capture_source(root), now=0)
        api.wait(first.job_id, wait_seconds=8, poll_seconds=.01)
        source.write_bytes(b"\xff invalid source")
        failed = watch.poll(capture_source(root), now=1)
        complete = api.wait(failed.job_id, wait_seconds=8, poll_seconds=.01)
        assert json.loads(api.report(complete, format="json"))["coverage"]["failed"]["service.py"] == "invalid_text_source"
        source.unlink()
        deletion = watch.poll(capture_source(root), now=2)
        assert deletion is not None, "A previously captured path was forgotten after an omission"
        complete = api.wait(deletion.job_id, wait_seconds=8, poll_seconds=.01)
        assert json.loads(api.report(complete, format="json"))["coverage"]["skipped"]["service.py"] == "deleted_source_unavailable"
        assert watch.poll(capture_source(root), now=3) is None


def test_full_omission_list_still_emits_a_truncated_deletion_report(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    source = root / "service.py"
    source.write_text("def first(items):\n    return items[0]\n")
    for index in range(1000):
        (root / f"excluded-{index:04d}.bin").write_bytes(b"excluded")
    provider = ReviewProvider()
    with TestClient(app(tmp_path, provider)) as http:
        api, transport = client(http)
        watch = watcher(api, debounce_seconds=0)
        first = watch.poll(capture_source(root), now=0)
        api.wait(first.job_id, wait_seconds=8, poll_seconds=.01)
        model_calls = len(provider.requests)
        source.unlink()
        capture = capture_source(root)
        assert len(capture.coverage.skipped) == 1000
        deletion = watch.poll(capture, now=1)
        assert deletion is not None, "A full omission list suppressed the deletion report"
        complete = api.wait(deletion.job_id, wait_seconds=8, poll_seconds=.01)
        report = json.loads(api.report(complete, format="json"))
        assert any("deletion" in text and "unlisted" in text for text in report["coverage"]["limitations"])
        assert report["coverage"]["inspected_files"] == []
        assert len(report["coverage"]["skipped"]) <= 1000
        assert len(provider.requests) == model_calls
        assert watch.poll(capture_source(root), now=2) is None
        assert sum(request.full_url.endswith("/api/jobs") for request in transport.requests) == 2


def test_watch_callbacks_cannot_mutate_original_submission_or_owned_job(tmp_path):
    source = tmp_path / "service.py"
    source.write_text("def first(items):\n    return items[0]\n")
    def alter_intent(intent):
        intent["changed_files"].clear()
        intent["snapshot_id"] = "0" * 32
    def alter_job(job):
        job.job_id = "0" * 32
        job.ledger.task_tools["injected"] = 12
    with TestClient(app(tmp_path)) as http:
        api, _ = client(http)
        watch = watcher(api, debounce_seconds=0, on_intent=alter_intent, on_job=alter_job)
        returned = watch.poll(capture_source(source), now=0)
        assert returned.job_id != "0" * 32
        assert watch.intent["changed_files"] == ["service.py"]
        assert "injected" not in watch.active_job.ledger.task_tools
        returned.job_id = "f" * 32
        assert watch.active_job.job_id != returned.job_id
        api.wait(watch.active_job.job_id, wait_seconds=8, poll_seconds=.01)
