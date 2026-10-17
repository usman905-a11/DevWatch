"""Bounded synchronous client for the canonical job API, independent of workers."""
from hashlib import sha256
import json
import re
import time
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import ValidationError

from devwatch.review.contracts import ReportDraft
from devwatch.review.jobs import JobView
from devwatch.review.stores import SnapshotManifest


class ClientError(RuntimeError):
    pass


class ClientWaitTimeout(ClientError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


def _identity(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise ValueError("invalid job or snapshot identity")
    return value


class ReviewClient:
    def __init__(self, service_url="http://127.0.0.1:8000", *, api_key=None, opener=None):
        parts = urlsplit(service_url)
        if (parts.scheme not in {"http", "https"} or not parts.hostname or parts.username is not None
                or parts.password is not None or parts.query or parts.fragment):
            raise ValueError("service URL must be HTTP(S), without credentials, query or fragment")
        if api_key is not None and (not api_key or not api_key.isascii() or len(api_key) > 256 or any(c.isspace() for c in api_key)):
            raise ValueError("API key must be bounded and contain no whitespace")
        self.service_url, self.api_key = service_url.rstrip("/"), api_key
        self.opener = opener or build_opener(_NoRedirect()).open

    def _request(self, method, path, *, payload=None, key=None, limit=1_000_000, timeout=10):
        data = None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if data is not None and len(data) > 11_000_000:
            raise ClientError("Snapshot request exceeds the service body limit")
        headers = {"Accept": "application/json, text/markdown, application/pdf", "Content-Type": "application/json"}
        if self.api_key is not None:
            headers["X-API-Key"] = self.api_key
        if key is not None:
            if not key or len(key) > 256 or not key.isascii() or any(c.isspace() for c in key):
                raise ValueError("bounded idempotency key required")
            headers["Idempotency-Key"] = key
        request = Request(self.service_url + path, data=data, headers=headers, method=method)
        try:
            with self.opener(request, timeout=timeout) as response:
                if response.status != 200 and not 200 <= response.status < 300:
                    raise ClientError(f"Service rejected request (HTTP {response.status})")
                raw = response.read(limit + 1)
                if len(raw) > limit:
                    raise ClientError("Service response exceeds its byte limit")
                return raw, response.headers.get("content-type", "").split(";")[0]
        except HTTPError as exc:
            exc.close()
            raise ClientError(f"Service rejected request (HTTP {exc.code})") from None
        except (URLError, OSError, TimeoutError):
            raise ClientError("Service request failed; outcome may be unknown. No retry or cancellation was issued.") from None

    def _json(self, method, path, **kwargs):
        raw, content_type = self._request(method, path, **kwargs)
        try:
            if content_type != "application/json":
                raise ValueError("unexpected content type")
            return json.loads(raw)
        except (ValueError, UnicodeError):
            raise ClientError("Service returned an invalid structured response") from None

    def capture(self, capture):
        body = self._json("POST", "/api/snapshots", payload={"files": capture.files,
            "capture_coverage": capture.coverage.model_dump(mode="json"), "git_metadata": capture.git_metadata.model_dump(mode="json")})
        try:
            manifest = SnapshotManifest.model_validate(body)
            from devwatch.review.stores import _capture_hash, _git_hash
            if manifest.capture_hash != _capture_hash(capture.coverage) or manifest.git_hash != _git_hash(capture.git_metadata):
                raise ValueError("snapshot metadata provenance differs")
            _identity(manifest.snapshot_id)
            if set(manifest.entries) != set(capture.files):
                raise ValueError("snapshot source set differs")
            for path, source in capture.files.items():
                entry, encoded = manifest.entries[path], source.encode("utf-8")
                if entry.content_hash != sha256(encoded).hexdigest() or entry.byte_count != len(encoded):
                    raise ValueError("snapshot source hash differs")
            return manifest
        except (ValueError, ValidationError):
            raise ClientError("Service returned an invalid snapshot response") from None

    def _job(self, method, path, *, expected=None, **kwargs):
        body = self._json(method, path, **kwargs)
        try:
            job = JobView.model_validate(body)
            if expected is not None and job.job_id != expected:
                raise ValueError("wrong job identity")
            return job
        except (ValueError, ValidationError):
            raise ClientError("Service returned an invalid job response") from None

    def submit(self, snapshot_id, changed_files=None, *, idempotency_key):
        body = {"snapshot_id": _identity(snapshot_id)}
        if changed_files is not None:
            body["changed_files"] = changed_files
        job = self._job("POST", "/api/jobs", payload=body, key=idempotency_key)
        if job.snapshot_id != snapshot_id:
            raise ClientError("Service returned a job for another snapshot")
        return job

    def status(self, job_id, *, timeout=10):
        return self._job("GET", f"/api/jobs/{_identity(job_id)}", expected=job_id, timeout=timeout)

    def cancel(self, job_id):
        return self._job("POST", f"/api/jobs/{_identity(job_id)}/cancel", expected=job_id)

    def resume(self, job_id):
        return self._job("POST", f"/api/jobs/{_identity(job_id)}/resume", expected=job_id)

    def snapshot(self, job):
        from devwatch.review.stores import _capture_hash, _git_hash
        manifest = SnapshotManifest.model_validate(self._json("GET", f"/api/jobs/{_identity(job.job_id)}/snapshot"))
        if (manifest.snapshot_id != job.snapshot_id or manifest.capture_hash != _capture_hash(manifest.capture_coverage)
                or manifest.git_hash != _git_hash(manifest.git_metadata)):
            raise ClientError("Service returned an invalid snapshot")
        return manifest

    def events(self, job_id, *, after=0):
        from devwatch.review.jobs import PersistedEvent, MAX_EVENT_CURSOR
        if type(after) is not int or not 0 <= after <= MAX_EVENT_CURSOR:
            raise ValueError("invalid replay cursor")
        data = self._json("GET", f"/api/jobs/{_identity(job_id)}/events?after={after}&limit=100")
        if not isinstance(data, dict) or set(data) != {"events", "next_cursor"} or not isinstance(data["events"], list) or len(data["events"]) > 100:
            raise ClientError("Service returned an invalid event page")
        try:
            parsed = [PersistedEvent.model_validate(event) for event in data["events"]]
        except ValidationError:
            raise ClientError("Service returned invalid event metadata") from None
        cursor = after
        for event in parsed:
            if event.job_id != job_id or event.sequence <= cursor:
                raise ClientError("Service returned invalid event ordering")
            cursor = event.sequence
        if type(data["next_cursor"]) is not int or data["next_cursor"] != cursor:
            raise ClientError("Service returned an invalid replay cursor")
        return {"events": [event.model_dump(mode="json") for event in parsed], "next_cursor": cursor}

    def evidence(self, job, reference):
        import re
        if not isinstance(reference, str) or not re.fullmatch(r"evidence-[0-9a-f]{64}", reference):
            raise ValueError("invalid evidence reference")
        manifest = self.snapshot(job)
        record = self._json("GET", f"/api/jobs/{_identity(job.job_id)}/evidence/{reference}")
        if (not isinstance(record, dict) or record.get("snapshot_id") != job.snapshot_id or record.get("snapshot_hash") != manifest.content_hash
                or not isinstance(record.get("source_scope"), list) or len(record["source_scope"]) > 100
                or any(path not in manifest.entries for path in record["source_scope"])):
            raise ClientError("Service returned invalid scoped evidence")
        return record

    def source(self, job, file_path, start_line=1, end_line=None):
        from devwatch.review.stores import validate_source_path
        path = validate_source_path(file_path)
        manifest = self.snapshot(job)
        if path not in manifest.entries or type(start_line) is not int or start_line < 1:
            raise ValueError("source outside the immutable snapshot")
        end_line = min(start_line + 19, manifest.entries[path].line_count) if end_line is None else end_line
        if type(end_line) is not int or end_line < start_line or end_line - start_line >= 200:
            raise ValueError("invalid source range")
        query = urlencode({"file_path": path, "start_line": start_line, "end_line": end_line})
        record = self._json("GET", f"/api/jobs/{_identity(job.job_id)}/source?{query}")
        if (not isinstance(record, dict) or record.get("snapshot_id") != job.snapshot_id or record.get("snapshot_hash") != manifest.content_hash
                or record.get("source_scope") != [path] or record.get("file_path") != path
                or record.get("start_line") != start_line or record.get("end_line") != end_line
                or record.get("content_hash") != manifest.entries[path].content_hash or record.get("tool") != "read_source"
                or not isinstance(record.get("data"), str) or len(record["data"].encode()) > 6000):
            raise ClientError("Service returned an invalid source excerpt")
        return record

    def wait(self, job_id, *, wait_seconds=610, poll_seconds=.2):
        if wait_seconds <= 0 or poll_seconds <= 0:
            raise ValueError("positive polling bounds required")
        deadline = time.monotonic() + wait_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ClientWaitTimeout("Client wait ended; the durable job continues. Use the job ID to check status.")
            job = self.status(job_id, timeout=min(10, remaining))
            if job.status not in {"queued", "running"}:
                return job
            time.sleep(min(poll_seconds, max(0, deadline - time.monotonic())))

    def report(self, job: JobView, *, format: Literal["json", "markdown", "pdf"] = "markdown") -> str | bytes:
        if job.status != "completed" or format not in {"json", "markdown", "pdf"}:
            raise ClientError("A finalized job and supported report format are required")
        raw, content_type = self._request("GET", f"/api/jobs/{_identity(job.job_id)}/report?" + urlencode({"format": "json"}), limit=10_000_000)
        try:
            report = ReportDraft.model_validate_json(raw)
            if content_type != "application/json" or report.snapshot_id != job.snapshot_id:
                raise ValueError("report belongs to another snapshot")
        except (ValueError, ValidationError):
            raise ClientError("Service returned an invalid report") from None
        if format == "pdf":
            raw, content_type = self._request("GET", f"/api/jobs/{job.job_id}/report?format=pdf", limit=10_000_000)
            if content_type != "application/pdf" or not raw.startswith(b"%PDF-") or not raw.rstrip().endswith(b"%%EOF"):
                raise ClientError("Service returned an invalid PDF report")
            return raw
        if format == "markdown":
            raw, content_type = self._request("GET", f"/api/jobs/{job.job_id}/report?format=markdown", limit=10_000_000)
            if content_type != "text/markdown":
                raise ClientError("Service returned an invalid Markdown report")
        try:
            return raw.decode("utf-8")
        except UnicodeError:
            raise ClientError("Service returned invalid report encoding") from None
