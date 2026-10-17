"""Command-line consumer of the canonical durable local review service."""
import json
import math
import time
from pathlib import Path
from typing import Optional
from uuid import uuid4

import typer
from rich.console import Console

from devwatch import __version__
from devwatch.review.capture import capture_source
from devwatch.review.client import ClientError, ReviewClient
from devwatch.review.watch import WatchReviewer

app = typer.Typer(name="DevWatch", help="Durable seven-agent code reviews", add_completion=False)
console = Console()


def version_callback(value: bool):
    if value:
        console.print(f"DevWatch v{__version__}")
        raise typer.Exit()


@app.callback()
def main(version: Optional[bool] = typer.Option(None, "--version", "-v", callback=version_callback, is_eager=True)):
    """Submit and observe durable reviews. Start the service with `devwatch serve`."""


def _client(service_url):
    import os
    return ReviewClient(service_url, api_key=os.getenv("DEVWATCH_API_KEY") or None)


def _output_path(output, format):
    if format not in {"markdown", "json", "pdf"}:
        raise ValueError("Report format must be markdown, json or pdf")
    if output is None:
        if format == "pdf":
            raise ValueError("PDF requires --output to a new .pdf file")
        return None
    path = Path(output).absolute()
    if path.suffix.lower() != {"markdown": ".md", "json": ".json", "pdf": ".pdf"}[format]:
        raise ValueError("Output must be a generated .md, .json or .pdf report")
    if path.exists() or path.is_symlink() or not path.parent.is_dir():
        raise ValueError("Output must be a new file in an existing directory")
    return path


def _publish(client, job, format, output):
    text = client.report(job, format=format)
    if output is None:
        typer.echo(text)
    else:
        # Exclusive creation refuses existing source, including after preflight.
        if format == "pdf":
            with output.open("xb") as stream:
                stream.write(text)
        else:
            with output.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
        typer.echo(f"Report saved: {output}")


def _error(error):
    message = str(error) if isinstance(error, (ClientError, ValueError)) else "Local capture or report file operation failed"
    typer.echo(message, err=True)
    raise typer.Exit(1)


@app.command()
def review(
    path: str = typer.Argument(".", help="Codebase directory or source file"),
    output: Optional[str] = typer.Option(None, "--output", "-o"),
    format: str = typer.Option("markdown", "--format"),
    service_url: str = typer.Option("http://127.0.0.1:8000", "--service-url", envvar="DEVWATCH_SERVICE_URL"),
    no_wait: bool = typer.Option(False, "--no-wait", help="Return after submission; the service keeps running"),
):
    """Capture immutable source, submit once, then optionally wait for its report."""
    try:
        destination = _output_path(output, format)
        if no_wait and destination:
            raise ValueError("Use job --report --output after a no-wait submission")
        capture = capture_source(path)
        client = _client(service_url)
        snapshot = client.capture(capture)
        key = uuid4().hex
        # Printed before submission so unknown outcomes retain their original intent.
        typer.echo("Submission intent: " + json.dumps({"snapshot_id": snapshot.snapshot_id,
            "changed_files": capture.changed_files, "idempotency_key": key}, ensure_ascii=True))
        current = client.submit(snapshot.snapshot_id, capture.changed_files, idempotency_key=key)
        typer.echo(f"Job ID: {current.job_id}")
        if no_wait:
            return
        current = client.wait(current.job_id)
        if current.status != "completed":
            raise ClientError(f"Job is {current.status}; use job, resume or cancel with the printed job ID")
        _publish(client, current, format, destination)
    except KeyboardInterrupt:
        typer.echo("Client disconnected; no job cancellation was issued.", err=True)
        raise typer.Exit(130)
    except (ClientError, ValueError, OSError) as error:
        _error(error)


@app.command()
def submit(
    snapshot_id: str,
    idempotency_key: str = typer.Option(..., "--idempotency-key"),
    changed_file: Optional[list[str]] = typer.Option(None, "--changed-file", help="Repeat for the original selected paths"),
    empty_scope: bool = typer.Option(False, "--empty-scope", help="Explicitly select zero changed files"),
    service_url: str = typer.Option("http://127.0.0.1:8000", "--service-url", envvar="DEVWATCH_SERVICE_URL"),
):
    """Submit/retry the same snapshot, scope and key without recapturing source."""
    try:
        if empty_scope and changed_file:
            raise ValueError("Choose changed files or empty scope")
        current = _client(service_url).submit(snapshot_id, [] if empty_scope else changed_file, idempotency_key=idempotency_key)
        typer.echo(current.model_dump_json())
    except (ClientError, ValueError, OSError) as error:
        _error(error)


@app.command()
def job(
    job_id: str,
    report: bool = typer.Option(False, "--report"),
    output: Optional[str] = typer.Option(None, "--output", "-o"),
    format: str = typer.Option("markdown", "--format"),
    service_url: str = typer.Option("http://127.0.0.1:8000", "--service-url", envvar="DEVWATCH_SERVICE_URL"),
):
    """Show persisted status or download a completed, accepted report."""
    try:
        destination = _output_path(output, format)
        if output and not report:
            raise ValueError("Output requires --report")
        client = _client(service_url)
        current = client.status(job_id)
        if report:
            _publish(client, current, format, destination)
        else:
            typer.echo(current.model_dump_json())
    except (ClientError, ValueError, OSError) as error:
        _error(error)


@app.command()
def events(
    job_id: str,
    after: int = typer.Option(0, "--after", min=0, help="Replay after this persisted sequence number"),
    follow: bool = typer.Option(False, "--follow", help="Poll durable events until the job stops"),
    service_url: str = typer.Option("http://127.0.0.1:8000", "--service-url", envvar="DEVWATCH_SERVICE_URL"),
):
    """Print one metadata-only JSON event per line; observing never controls a job."""
    try:
        client, terminal = _client(service_url), False
        while True:
            page = client.events(job_id, after=after)
            for event in page["events"]:
                typer.echo(json.dumps(event, ensure_ascii=True))
            after = page["next_cursor"]
            if page["events"]:
                continue
            if not follow or terminal:
                return
            terminal = client.status(job_id).status not in {"queued", "running"}
            if not terminal:
                time.sleep(.2)
    except KeyboardInterrupt:
        typer.echo("Observer disconnected; no job cancellation was issued.", err=True)
        raise typer.Exit(130)
    except (ClientError, ValueError, OSError) as error:
        _error(error)


@app.command()
def events(
    job_id: str,
    after: int = typer.Option(0, "--after", min=0, help="Replay after this persisted sequence number"),
    follow: bool = typer.Option(False, "--follow", help="Poll durable events until the job stops"),
    service_url: str = typer.Option("http://127.0.0.1:8000", "--service-url", envvar="DEVWATCH_SERVICE_URL"),
):
    """Print one metadata-only JSON event per line; observing never controls a job."""
    try:
        client, terminal = _client(service_url), False
        while True:
            page = client.events(job_id, after=after)
            for event in page["events"]:
                typer.echo(json.dumps(event, ensure_ascii=True))
            after = page["next_cursor"]
            if page["events"]:
                continue
            if not follow or terminal:
                return
            terminal = client.status(job_id).status not in {"queued", "running"}
            if not terminal:
                time.sleep(.2)
    except KeyboardInterrupt:
        typer.echo("Observer disconnected; no job cancellation was issued.", err=True)
        raise typer.Exit(130)
    except (ClientError, ValueError, OSError) as error:
        _error(error)


@app.command()
def resume(job_id: str, service_url: str = typer.Option("http://127.0.0.1:8000", "--service-url", envvar="DEVWATCH_SERVICE_URL")):
    """Explicitly resume an interrupted job with its original cumulative limits."""
    try:
        typer.echo(_client(service_url).resume(job_id).model_dump_json())
    except (ClientError, ValueError, OSError) as error:
        _error(error)


@app.command()
def cancel(job_id: str, service_url: str = typer.Option("http://127.0.0.1:8000", "--service-url", envvar="DEVWATCH_SERVICE_URL")):
    """Explicitly request cancellation of the specified durable job."""
    try:
        typer.echo(_client(service_url).cancel(job_id).model_dump_json())
    except (ClientError, ValueError, OSError) as error:
        _error(error)


@app.command()
def watch(
    path: str = typer.Argument(".", help="Source file or directory to observe"),
    interval: float = typer.Option(1., "--interval", min=.1, max=60, help="Seconds between bounded captures"),
    debounce: float = typer.Option(1., "--debounce", min=0, max=60, help="Stable seconds before submission"),
    max_reviews: Optional[int] = typer.Option(None, "--max-reviews", min=1, help="Stop after this many submissions"),
    service_url: str = typer.Option("http://127.0.0.1:8000", "--service-url", envvar="DEVWATCH_SERVICE_URL"),
):
    """Debounce source changes into durable jobs; closing watch never cancels them."""
    try:
        if not math.isfinite(interval):
            raise ValueError("Watch interval must be finite")
        client = _client(service_url)
        def status(current):
            command = f"devwatch job {current.job_id}" + (" --report" if current.status == "completed" else "")
            typer.echo(f"Job {current.job_id}: {current.status}; {command}")
        session = WatchReviewer(client, debounce_seconds=debounce,
            on_intent=lambda intent: typer.echo("Submission intent: " + json.dumps(intent, ensure_ascii=True)),
            on_job=lambda current: typer.echo(f"Job ID: {current.job_id}"),
            on_status=status)
        typer.echo("Watching eligible source and capture coverage. Press Ctrl+C to stop watching; submitted jobs keep running.")
        while max_reviews is None or session.submissions < max_reviews:
            session.poll(capture_source(path), now=time.monotonic())
            if max_reviews is not None and session.submissions >= max_reviews:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        typer.echo("Watcher disconnected; no job cancellation was issued.", err=True)
        raise typer.Exit(130)
    except (ClientError, ValueError, OSError) as error:
        _error(error)


@app.command()
def serve(port: int = typer.Option(8000, "--port", min=1, max=65535)):
    """Run the canonical local review service on loopback."""
    import uvicorn
    uvicorn.run("devwatch.review.service:create_app", factory=True, host="127.0.0.1", port=port)


if __name__ == "__main__":
    app()
