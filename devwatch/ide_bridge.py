"""Bounded stdin/stdout client bridge shared by the two IDE adapters.

Run installed DevWatch with `python -I -m devwatch.ide_bridge`. Credentials belong
only in stdin. This process submits/observes owned durable jobs; it never executes
an agent, writes reviewed source, chooses an export destination or auto-resumes.
"""
import base64
import json
import sys
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator, field_validator

from devwatch.review.capture import capture_source
from devwatch.review.client import ReviewClient
from devwatch.review.contracts import ContractModel
from devwatch.review.jobs import MAX_EVENT_CURSOR
from devwatch.review.stores import validate_source_path


class SubmissionIntent(ContractModel):
    snapshot_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    changed_files: list[str] | None = Field(default=None, max_length=100)
    idempotency_key: str = Field(pattern=r"^[\x21-\x7e]{1,256}$")

    @field_validator("changed_files")
    @classmethod
    def paths(cls, values):
        return None if values is None else [validate_source_path(value) for value in values]


class BridgeRequest(ContractModel):
    version: Literal[1] = 1
    action: Literal["capture", "submit", "status", "events", "snapshot", "source", "evidence", "report", "cancel", "resume"]
    service_url: str = Field(default="http://127.0.0.1:8000", max_length=2048)
    api_key: str | None = Field(default=None, max_length=256)
    root: str | None = Field(default=None, min_length=1, max_length=4096)
    intent: SubmissionIntent | None = None
    job_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    after: int = Field(default=0, ge=0, le=MAX_EVENT_CURSOR, strict=True)
    file_path: str | None = None
    evidence_ref: str | None = Field(default=None, pattern=r"^evidence-[0-9a-f]{64}$")
    start_line: int = Field(default=1, ge=1, strict=True)
    end_line: int | None = Field(default=None, ge=1, strict=True)
    format: Literal["json", "markdown", "pdf"] = "json"

    @field_validator("file_path")
    @classmethod
    def source_path(cls, value):
        return None if value is None else validate_source_path(value)

    @model_validator(mode="after")
    def action_arguments(self):
        allowed = {"capture": {"root"}, "submit": {"intent"}, "status": {"job_id"}, "events": {"job_id", "after"},
            "snapshot": {"job_id"}, "source": {"job_id", "file_path", "start_line", "end_line"}, "evidence": {"job_id", "evidence_ref"}, "report": {"job_id", "format"},
            "cancel": {"job_id"}, "resume": {"job_id"}}[self.action]
        supplied = self.model_fields_set - {"version", "action", "service_url", "api_key"}
        if not supplied.issubset(allowed):
            raise ValueError("Arguments do not belong to the requested action")
        required = {"root"} if self.action == "capture" else {"intent"} if self.action == "submit" else {"job_id"}
        if self.action == "source":
            required.add("file_path")
        if self.action == "evidence":
            required.add("evidence_ref")
        if any(getattr(self, key) is None for key in required):
            raise ValueError("Action argument missing")
        if self.end_line is not None and (self.end_line < self.start_line or self.end_line - self.start_line >= 200):
            raise ValueError("Invalid source range")
        return self


def dispatch(payload, *, client=None):
    request = BridgeRequest.model_validate(payload)
    client = client or ReviewClient(request.service_url, api_key=request.api_key)
    if request.action == "capture":
        captured = capture_source(request.root)
        snapshot = client.capture(captured)
        return {"manifest": snapshot.model_dump(mode="json"), "intent": SubmissionIntent(snapshot_id=snapshot.snapshot_id,
            changed_files=list(captured.changed_files), idempotency_key=uuid4().hex).model_dump(mode="json")}
    if request.action == "submit":
        intent = request.intent
        return client.submit(intent.snapshot_id, intent.changed_files, idempotency_key=intent.idempotency_key).model_dump(mode="json")
    if request.action == "events":
        return client.events(request.job_id, after=request.after)
    if request.action in {"cancel", "resume"}:
        return getattr(client, request.action)(request.job_id).model_dump(mode="json")
    job = client.status(request.job_id)
    if request.action == "status":
        return job.model_dump(mode="json")
    if request.action == "snapshot":
        return client.snapshot(job).model_dump(mode="json")
    if request.action == "source":
        return client.source(job, request.file_path, request.start_line, request.end_line)
    if request.action == "evidence":
        return client.evidence(job, request.evidence_ref)
    data = client.report(job, format=request.format)
    return {"format": request.format, "base64": base64.b64encode(data).decode()} if isinstance(data, bytes) else {"format": request.format, "text": data}


def main():
    try:
        raw = sys.stdin.buffer.read(200_001)
        if len(raw) > 200_000:
            raise ValueError("Bridge request too large")
        result = dispatch(json.loads(raw))
        encoded = json.dumps({"version": 1, "ok": True, "result": result}, ensure_ascii=True, allow_nan=False)
        if len(encoded.encode()) > 15_000_000:
            raise ValueError("Bridge response too large")
        print(encoded)
    except Exception:
        # Never echo source, credentials, paths or provider/server exception text.
        print(json.dumps({"version": 1, "ok": False, "error_code": "bridge_request_failed"}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
