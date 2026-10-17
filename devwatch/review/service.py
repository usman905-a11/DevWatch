"""Canonical local job API. Run with uvicorn devwatch.review.service:create_app --factory.

The service owns workers; transports only submit, observe or explicitly cancel.
This entry point has no dependency on the legacy review engines or report schema.
"""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import Field

from devwatch.review.contracts import AgentId, AgentWorkItem, ContractModel, ModelTier
from devwatch.review.jobs import DurableJobManager, EventStore, JobConflict, JobNotFound, JobStore, MAX_EVENT_CURSOR
from devwatch.review.repository import RepositoryContext
from devwatch.review.stores import ArtifactStore, CaptureCoverage, GitMetadata, RepoCache, StoreLayout
from devwatch.review.workflow import CanonicalReviewExecutor
from devwatch.review.tool_runtime import TrustedCommand
from devwatch.review.database_tools import DatabasePolicy


@dataclass(frozen=True)
class ServiceSettings:
    runtime_root: Path
    models: dict[ModelTier, str]
    api_keys: frozenset[str] = frozenset()
    production: bool = False
    allowed_origins: tuple[str, ...] = ("http://localhost:3000", "http://localhost:5173",
                                      "http://127.0.0.1:3000", "http://127.0.0.1:5173")
    max_request_bytes: int = 11_000_000
    trusted_commands: tuple[TrustedCommand, ...] = ()
    databases: tuple[DatabasePolicy, ...] = ()
    langsmith_metadata: bool = False
    langsmith_project: str = "devwatch-metadata"

    def __post_init__(self):
        if set(self.models) != set(ModelTier) or any(not name.strip() for name in self.models.values()):
            raise ValueError("explicit small, medium and strong model names are required")
        if self.production and not self.api_keys:
            raise ValueError("production requires an API key")
        if any(not key or not key.isascii() or len(key) > 256 for key in self.api_keys) or "*" in self.allowed_origins:
            raise ValueError("bounded credentials and explicit origins are required")
        if self.max_request_bytes < 1:
            raise ValueError("request size must be bounded")
        if len(self.trusted_commands) > 100 or len({command.command_id for command in self.trusted_commands}) != len(self.trusted_commands):
            raise ValueError("Trusted command definitions must be bounded and unique")
        if len(self.databases) > 20 or len({policy.database_id for policy in self.databases}) != len(self.databases):
            raise ValueError("Database policy definitions must be bounded and unique")
        if not self.langsmith_project or len(self.langsmith_project) > 128:
            raise ValueError("bounded telemetry project required")

    @classmethod
    def from_env(cls):
        key = os.getenv("DEVWATCH_API_KEY", "")
        definitions = ()
        databases = ()
        if configured := os.getenv("DEVWATCH_TRUSTED_TOOLS_FILE"):
            data = Path(configured).read_bytes()
            if len(data) > 200_000:
                raise ValueError("Trusted tool configuration too large")
            definitions = tuple(TrustedCommand.model_validate(item) for item in json.loads(data))
        if configured := os.getenv("DEVWATCH_DATABASE_POLICIES_FILE"):
            data = Path(configured).read_bytes()
            if len(data) > 200_000:
                raise ValueError("Database policy configuration too large")
            databases = tuple(DatabasePolicy.model_validate(item) for item in json.loads(data))
        return cls(runtime_root=Path(os.getenv("DEVWATCH_RUNTIME_DIR", ".devwatch/runtime")),
            models={tier: os.getenv(f"DEVWATCH_MODEL_{tier.value.upper()}", "") for tier in ModelTier},
            api_keys=frozenset({key}) if key else frozenset(),
            production=os.getenv("DEVWATCH_ENV", "development").lower() == "production", trusted_commands=definitions, databases=databases,
            langsmith_metadata=os.getenv("DEVWATCH_LANGSMITH_METADATA", "false").lower() == "true",
            langsmith_project=os.getenv("DEVWATCH_LANGSMITH_PROJECT", "devwatch-metadata"))

    def principal(self, headers, *, client_host):
        key = headers.get("x-api-key")
        authorization = headers.get("authorization")
        if authorization:
            if not authorization.startswith("Bearer ") or key is not None:
                raise HTTPException(401, "Authentication required")
            key = authorization[7:]
        if not self.api_keys:
            if key is not None or client_host not in {"127.0.0.1", "::1", "localhost"}:
                raise HTTPException(401, "Authentication required")
            return "local-owner"
        if key is None or not key.isascii() or len(key) > 256 or not any(hmac.compare_digest(key, allowed) for allowed in self.api_keys):
            raise HTTPException(401, "Authentication required")
        # Same identity on HTTP and WS; no credential/prefix retained in stores.
        return "key-" + sha256(key.encode()).hexdigest()


class BoundedRequestBody:
    """Cap actual bytes, including chunked bodies, before JSON decoding."""
    def __init__(self, app, limit):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > self.limit:
                return await JSONResponse({"detail": "Request too large"}, status_code=413)(scope, receive, send)
            chunks.append(message)
            if not message.get("more_body", False):
                break
        async def bounded_receive():
            return chunks.pop(0) if chunks else await receive()
        await self.app(scope, bounded_receive, send)


class SnapshotRequest(ContractModel):
    files: dict[str, str] = Field(max_length=100)
    capture_coverage: CaptureCoverage = Field(default_factory=CaptureCoverage)
    git_metadata: GitMetadata = Field(default_factory=GitMetadata)


class JobRequest(ContractModel):
    snapshot_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    changed_files: list[str] | None = Field(default=None, max_length=100)


def _public_job(job):
    return {field: getattr(job, field) for field in
            ("job_id", "status", "workflow_version", "ledger", "limits", "created_at", "updated_at")} | {
                "snapshot_id": job.request["snapshot_id"]}


def _cursor(value):
    if not value.isascii() or not value.isdigit() or len(value) > 19 or int(value) > MAX_EVENT_CURSOR:
        raise ValueError("invalid reconnect cursor")
    return int(value)


def create_app(*, settings: ServiceSettings | None = None, provider=None):
    settings = settings or ServiceSettings.from_env()
    if provider is None:
        from devwatch.providers.openai_adapter import OpenAIProviderAdapter
        provider_name = os.getenv("DEVWATCH_PROVIDER") or (
            "gemini" if settings.models[ModelTier.SMALL].startswith("gemini-") else "openai")
        provider = OpenAIProviderAdapter(provider_name=provider_name, max_concurrency=3)

    @asynccontextmanager
    async def lifespan(application):
        layout = StoreLayout(settings.runtime_root)
        jobs, events = JobStore(layout.jobs), EventStore(layout.events)
        artifacts, cache = ArtifactStore(layout.artifacts), RepoCache(layout.repo_cache)
        executor = CanonicalReviewExecutor(layout, artifacts, cache, jobs, events, provider, models=settings.models,
                                           trusted_commands=settings.trusted_commands, databases=settings.databases)
        manager = DurableJobManager(jobs, events, executor, recover_timeout=executor.recover_timeout)
        application.state.jobs, application.state.events = jobs, events
        application.state.artifacts, application.state.cache = artifacts, cache
        application.state.manager = manager
        telemetry = None
        if settings.langsmith_metadata:
            from devwatch.review.observability import MetadataExporter, configured_metadata_client
            exporter = MetadataExporter(events, client=configured_metadata_client(), project=settings.langsmith_project)
            telemetry = asyncio.create_task(exporter.run(), name="metadata-export")
        await manager.start()
        try:
            yield
        finally:
            await manager.close()
            if telemetry is not None:
                telemetry.cancel()
                await asyncio.gather(telemetry, return_exceptions=True)

    app = FastAPI(title="DevWatch Local Review Service", lifespan=lifespan)
    app.add_middleware(BoundedRequestBody, limit=settings.max_request_bytes)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.allowed_origins),
                       allow_methods=["GET", "POST"], allow_headers=["Authorization", "X-API-Key", "Idempotency-Key", "Last-Event-ID"])

    def owner(request: Request):
        return settings.principal(request.headers, client_host=request.client.host if request.client else "")

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Default validation errors may include submitted source/credentials.
        return JSONResponse({"detail": "Invalid request"}, status_code=422)

    @app.exception_handler(ValueError)
    async def bad_request(request, exc):
        return JSONResponse({"detail": "Invalid request"}, status_code=422)

    @app.exception_handler(JobConflict)
    async def conflict(request, exc):
        return JSONResponse({"detail": "Job conflict"}, status_code=409)

    async def unavailable(request, exc):
        return JSONResponse({"detail": "Resource not found"}, status_code=404)
    for exception in (JobNotFound, FileNotFoundError, PermissionError):
        app.add_exception_handler(exception, unavailable)

    @app.get("/health")
    async def health():
        return {"status": "ok", "workflow_version": "seven-agent-v1"}

    @app.post("/api/snapshots", status_code=201)
    async def snapshot(body: SnapshotRequest, principal=Depends(owner)):
        return app.state.artifacts.capture(owner=principal, files=body.files, capture_coverage=body.capture_coverage,
                                           git_metadata=body.git_metadata)

    @app.post("/api/jobs", status_code=202)
    async def submit(body: JobRequest, principal=Depends(owner),
                     idempotency_key: str = Header(min_length=1, max_length=256)):
        manifest = app.state.artifacts.manifest(body.snapshot_id, owner=principal)
        if body.changed_files is not None and any(path not in manifest.entries for path in body.changed_files):
            raise ValueError("changed files must belong to the snapshot")
        job = await app.state.manager.submit(owner=principal, request=body.model_dump(exclude_none=True),
                                            idempotency_key=idempotency_key)
        return _public_job(job)

    @app.get("/api/jobs/{identity}")
    async def job(identity: str, principal=Depends(owner)):
        return _public_job(app.state.jobs.get(identity, owner=principal))

    @app.post("/api/jobs/{identity}/cancel")
    async def cancel(identity: str, principal=Depends(owner)):
        return _public_job(await app.state.manager.cancel(identity, owner=principal))

    @app.post("/api/jobs/{identity}/resume", status_code=202)
    async def resume(identity: str, principal=Depends(owner)):
        return _public_job(await app.state.manager.resume(identity, owner=principal))

    @app.get("/api/jobs/{identity}/report")
    async def report(identity: str, format: Literal["json", "markdown", "pdf"] = "json", principal=Depends(owner)):
        record = app.state.jobs.get(identity, owner=principal)
        if record.status != "completed" or record.result is None:
            raise HTTPException(409, "Report is not finalized")
        if format == "pdf":
            if not record.result.get("pdf_artifact"):
                raise HTTPException(409, "PDF artifact unavailable")
            data = app.state.artifacts.read_report_pdf(identity, record.request["snapshot_id"], owner=principal,
                                                       reference=record.result["pdf_artifact"])
            return Response(data, media_type="application/pdf", headers={"X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store", "Content-Disposition": f'attachment; filename="devwatch-{identity}.pdf"'})
        return Response(record.result[format], media_type="application/json" if format == "json" else "text/markdown",
                        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})

    def repository(identity, principal):
        record = app.state.jobs.get(identity, owner=principal)
        return RepositoryContext(app.state.artifacts, app.state.cache, record.request["snapshot_id"], owner=principal)

    @app.get("/api/jobs/{identity}/snapshot")
    async def job_snapshot(identity: str, principal=Depends(owner)):
        record = app.state.jobs.get(identity, owner=principal)
        return app.state.artifacts.manifest(record.request["snapshot_id"], owner=principal)

    @app.get("/api/jobs/{identity}/source")
    async def source(identity: str, file_path: str, start_line: int = Query(1, ge=1),
                     end_line: int | None = Query(None, ge=1), principal=Depends(owner)):
        repo = repository(identity, principal)
        work = AgentWorkItem(task_id="__source_view", agent_id=AgentId.SYNTHESIZER_VERIFIER,
                             files=list(repo.manifest.entries), focus="Source view")
        arguments = {"file_path": file_path, "start_line": start_line}
        if end_line is not None:
            arguments["end_line"] = end_line
        observation = repo._read_source(arguments, work)
        excerpt = repo.scoped_evidence(observation.evidence_ref, work)
        # The source-view transport retains its bounded public wire contract;
        # agent provenance and paged evidence are separate artifact metadata.
        if len(excerpt["data"].encode("utf-8")) > repo.CONTEXT_BYTES:
            raise ValueError("source view exceeds context limit; select a smaller line range")
        return {key: value for key, value in excerpt.items() if key != "provenance"}

    @app.get("/api/jobs/{identity}/evidence/{reference}")
    async def evidence(identity: str, reference: str, principal=Depends(owner)):
        return repository(identity, principal).evidence(reference)

    def replay(identity, principal, after, limit=1000):
        app.state.jobs.get(identity, owner=principal)
        app.state.jobs.dispatch_events(app.state.events)
        return app.state.events.replay(identity, after=after, limit=limit)

    @app.get("/api/jobs/{identity}/events")
    async def events(identity: str, after: int = Query(0, ge=0, le=MAX_EVENT_CURSOR), limit: int = Query(100, ge=1, le=1000), principal=Depends(owner)):
        page = replay(identity, principal, after, limit)
        return {"events": page, "next_cursor": page[-1].sequence if page else after}

    async def persisted_events(identity, principal, after):
        while True:
            page = replay(identity, principal, after)
            for event in page:
                after = event.sequence
                yield event
            if not page and app.state.jobs.get(identity, owner=principal).status not in {"queued", "running"}:
                return
            if not page:
                await asyncio.sleep(.1)

    @app.get("/api/jobs/{identity}/stream")
    async def stream(identity: str, after: int = Query(0, ge=0, le=MAX_EVENT_CURSOR), principal=Depends(owner),
                     last_event_id: str | None = Header(None)):
        if last_event_id is not None:
            after = _cursor(last_event_id)
        replay(identity, principal, after)
        async def frames():
            async for event in persisted_events(identity, principal, after):
                yield f"id: {event.sequence}\nevent: {event.kind}\ndata: {event.model_dump_json()}\n\n"
        return StreamingResponse(frames(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.websocket("/api/jobs/{identity}/ws")
    async def websocket(socket: WebSocket, identity: str):
        viewers = []
        try:
            if set(socket.query_params) - {"after"} or (socket.headers.get("origin") is not None
                    and socket.headers["origin"] not in settings.allowed_origins):
                raise ValueError("invalid WebSocket request")
            cursor = _cursor(socket.query_params.get("after", "0"))
            headers = dict(socket.headers)
            if settings.api_keys and not (headers.get("x-api-key") or headers.get("authorization")):
                await socket.accept()
                frame = await asyncio.wait_for(socket.receive(), timeout=5)
                if frame["type"] == "websocket.disconnect":
                    raise WebSocketDisconnect(frame.get("code", 1000))
                message = frame.get("text")
                if frame["type"] != "websocket.receive" or not isinstance(message, str):
                    raise ValueError("authentication requires a text frame")
                if len(message) > 1024:
                    raise ValueError("authentication message too large")
                credentials = json.loads(message)
                if not isinstance(credentials, dict) or set(credentials) != {"api_key"} or not isinstance(credentials["api_key"], str):
                    raise ValueError("invalid credentials")
                headers["x-api-key"] = credentials["api_key"]
            principal = settings.principal(headers, client_host=socket.client.host if socket.client else "")
            replay(identity, principal, cursor)
            if socket.application_state.name != "CONNECTED":
                await socket.accept()
            async def send_events():
                async for event in persisted_events(identity, principal, cursor):
                    await socket.send_json(event.model_dump(mode="json"))
                await socket.close(code=1000)
            async def disconnect():
                message = await socket.receive()
                return message["type"] != "websocket.disconnect"
            viewers = [asyncio.create_task(send_events()), asyncio.create_task(disconnect())]
            done, pending = await asyncio.wait(viewers, return_when=asyncio.FIRST_COMPLETED)
            for viewer in pending:
                viewer.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for viewer in done:
                if viewer.result() is True:
                    await socket.close(code=1008)
        except WebSocketDisconnect:
            return
        except (HTTPException, JobNotFound, ValueError, TimeoutError):
            await socket.close(code=1008)
        finally:
            for viewer in viewers:
                if not viewer.done():
                    viewer.cancel()
            await asyncio.gather(*viewers, return_exceptions=True)

    return app
