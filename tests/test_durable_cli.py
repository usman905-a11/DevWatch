"""CLI cutover uses real capture, service, storage and graph, with scripted models."""
import json

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from devwatch.cli import app as cli
from devwatch.review.client import ReviewClient
from tests.test_review_client import Transport
from tests.test_review_service import ALICE, app

runner = CliRunner()


def connect(monkeypatch, http):
    transport = Transport(http)
    client = ReviewClient("http://testserver", api_key=ALICE["X-API-Key"], opener=transport)
    monkeypatch.setattr("devwatch.cli.ReviewClient", lambda *args, **kwargs: client, raising=False)
    return client, transport


def test_cli_captures_submits_waits_and_saves_only_generated_report(tmp_path, monkeypatch):
    source = tmp_path / "repo"
    source.mkdir()
    (source / "service.py").write_text("def first(items):\n    return items[0]\n")
    output = tmp_path / "report.md"
    with TestClient(app(tmp_path)) as http:
        client, transport = connect(monkeypatch, http)
        result = runner.invoke(cli, ["review", str(source), "--output", str(output)])
        assert result.exit_code == 0, result.output
        assert "Job ID:" in result.output
        assert "Uncertain" in output.read_text(encoding="utf-8")
        assert sum(r.full_url.endswith("/api/jobs") for r in transport.requests) == 1
        assert (source / "service.py").read_text() == "def first(items):\n    return items[0]\n"


def test_cli_saves_pdf_as_binary_without_changing_reviewed_source(tmp_path, monkeypatch):
    import pymupdf
    source = tmp_path / "service.py"
    source.write_text("def first(items):\n    return items[0]\n")
    output = tmp_path / "review.pdf"
    with TestClient(app(tmp_path)) as http:
        connect(monkeypatch, http)
        result = runner.invoke(cli, ["review", str(source), "--format", "pdf", "--output", str(output)])
        assert result.exit_code == 0, result.output
        with pymupdf.open(output) as document:
            assert "Uncertain high-impact candidates (1)" in "".join(page.get_text() for page in document)
        assert source.read_text() == "def first(items):\n    return items[0]\n"


def test_cli_requires_pdf_destination_before_any_submission(tmp_path, monkeypatch):
    source = tmp_path / "service.py"
    source.write_text("pass\n")
    with TestClient(app(tmp_path)) as http:
        _, transport = connect(monkeypatch, http)
        result = runner.invoke(cli, ["review", str(source), "--format", "pdf"])
        assert result.exit_code != 0 and "PDF requires --output" in result.output
        assert not transport.requests


def test_cli_no_wait_leaves_job_running_and_job_command_fetches_report(tmp_path, monkeypatch):
    (tmp_path / "service.py").write_text("def first(items):\n    return items[0]\n")
    with TestClient(app(tmp_path)) as http:
        client, transport = connect(monkeypatch, http)
        result = runner.invoke(cli, ["review", str(tmp_path / "service.py"), "--no-wait"])
        assert result.exit_code == 0, result.output
        submitted = [r for r in transport.requests if r.full_url.endswith("/api/jobs")][0]
        request = json.loads(submitted.data)
        key = submitted.get_header("Idempotency-key")
        job = client.submit(request["snapshot_id"], request["changed_files"], idempotency_key=key)
        complete = client.wait(job.job_id, wait_seconds=5, poll_seconds=.01)
        result = runner.invoke(cli, ["job", complete.job_id, "--report", "--format", "json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["snapshot_id"] == request["snapshot_id"]
        assert not any(r.full_url.endswith("/cancel") for r in transport.requests)
        status = runner.invoke(cli, ["job", complete.job_id])
        assert json.loads(status.output)["status"] == "completed"


def test_cli_rejects_source_output_or_overwrite_before_submission(tmp_path, monkeypatch):
    source = tmp_path / "service.py"
    source.write_text("pass\n")
    report = tmp_path / "existing.md"
    report.write_text("keep")
    with TestClient(app(tmp_path)) as http:
        _, transport = connect(monkeypatch, http)
        for output in (source, report):
            result = runner.invoke(cli, ["review", str(source), "-o", str(output)])
            assert result.exit_code != 0
        assert not transport.requests
        assert source.read_text() == "pass\n" and report.read_text() == "keep"


def test_cli_submit_replays_exact_intent_without_recapture(tmp_path, monkeypatch):
    snapshot = None
    with TestClient(app(tmp_path)) as http:
        client, transport = connect(monkeypatch, http)
        snapshot = http.post("/api/snapshots", headers=ALICE, json={"files": {"service.py": "pass\n"}}).json()
        args = ["submit", snapshot["snapshot_id"], "--idempotency-key", "retry-intent", "--empty-scope"]
        first, second = runner.invoke(cli, args), runner.invoke(cli, args)
        assert first.exit_code == second.exit_code == 0, first.output + second.output
        assert json.loads(first.output)["job_id"] == json.loads(second.output)["job_id"]
        assert not any(r.full_url.endswith("/api/snapshots") for r in transport.requests)


def test_cli_resume_cancel_use_explicit_job_api(tmp_path, monkeypatch):
    with TestClient(app(tmp_path)) as http:
        client, _ = connect(monkeypatch, http)
        snapshot = http.post("/api/snapshots", headers=ALICE, json={"files": {}}).json()
        job = client.submit(snapshot["snapshot_id"], [], idempotency_key="controls")
        result = runner.invoke(cli, ["cancel", job.job_id])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["status"] in {"cancelled", "completed"}
        invalid = runner.invoke(cli, ["resume", "bad-id"])
        assert invalid.exit_code != 0


def test_cli_watch_stops_at_review_limit_without_cancelling_submitted_job(tmp_path, monkeypatch):
    source = tmp_path / "service.py"
    source.write_text("def first(items):\n    return items[0]\n")
    with TestClient(app(tmp_path)) as http:
        client, transport = connect(monkeypatch, http)
        result = runner.invoke(cli, ["watch", str(source), "--debounce", "0", "--max-reviews", "1"])
        assert result.exit_code == 0, result.output
        assert "Submission intent:" in result.output and "Job ID:" in result.output
        identity = next(line.split(": ")[1] for line in result.output.splitlines() if line.startswith("Job ID:"))
        assert client.wait(identity, wait_seconds=8, poll_seconds=.01).status == "completed"
        assert sum(request.full_url.endswith("/api/jobs") for request in transport.requests) == 1
        assert not any(request.full_url.endswith(("/cancel", "/resume")) for request in transport.requests)


def test_cli_watch_keyboard_interrupt_leaves_durable_job_running(tmp_path, monkeypatch):
    source = tmp_path / "service.py"
    source.write_text("def first(items):\n    return items[0]\n")
    with TestClient(app(tmp_path)) as http:
        client, transport = connect(monkeypatch, http)
        def disconnect(_seconds):
            raise KeyboardInterrupt
        with monkeypatch.context() as patch:
            patch.setattr("devwatch.cli.time.sleep", disconnect)
            result = runner.invoke(cli, ["watch", str(source), "--debounce", "0"])
        assert result.exit_code == 130, result.output
        identity = next(line.split(": ")[1] for line in result.output.splitlines() if line.startswith("Job ID:"))
        assert client.wait(identity, wait_seconds=8, poll_seconds=.01).status == "completed"
        assert not any(request.full_url.endswith(("/cancel", "/resume")) for request in transport.requests)


def test_cli_watch_rejects_nonfinite_interval_before_submission(tmp_path, monkeypatch):
    source = tmp_path / "service.py"
    source.write_text("pass\n")
    with TestClient(app(tmp_path)) as http:
        _, transport = connect(monkeypatch, http)
        result = runner.invoke(cli, ["watch", str(source), "--interval", "nan", "--debounce", "0", "--max-reviews", "1"])
        assert result.exit_code != 0
        assert not transport.requests
