"""Canonical local job API. Run with uvicorn backend.review.service:create_app --factory.

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

from backend.review.contracts import AgentId, AgentWorkItem, BalancedLimits, ContractModel, ModelTier
from backend.review.declared_context import validate_context_files
from backend.review.jobs import DurableJobManager, JobConflict, JobEvent, JobNotFound, JobStore, JobView, MAX_EVENT_CURSOR
from backend.review.repository import RepositoryContext
from backend.review.stores import ArtifactStore, CaptureCoverage, GitMetadata, SnapshotManifest, StoreLayout
from backend.review.workflow import CanonicalReviewExecutor
from backend.review.workspace import (
    PathOutsideWorkspaceError,
    WorkspaceError,
    WorkspaceManager,
    WorkspaceNotFoundError,
    WorkspaceNotSetError,
    build_workspace_manifest,
)


@dataclass(frozen=True)
class ServiceSettings:
    runtime_root: Path
    models: dict[ModelTier, str]
    api_keys: frozenset[str] = frozenset()
    production: bool = False
    allowed_origins: tuple[str, ...] = ("http://localhost:3000", "http://localhost:5173",
                                      "http://127.0.0.1:3000", "http://127.0.0.1:5173")
    max_request_bytes: int = 11_000_000
    default_job_tokens: int | None = None

    def __post_init__(self):
        if set(self.models) != set(ModelTier) or any(not name.strip() for name in self.models.values()):
            raise ValueError("explicit small, medium and strong model names are required")
        if self.production and not self.api_keys:
            raise ValueError("production requires an API key")
        if any(not key or not key.isascii() or len(key) > 256 for key in self.api_keys) or "*" in self.allowed_origins:
            raise ValueError("bounded credentials and explicit origins are required")
        if self.max_request_bytes < 1:
            raise ValueError("request size must be bounded")

    @classmethod
    def from_env(cls):
        key = os.getenv("DEVWATCH_API_KEY", "")
        model = os.getenv("DEVWATCH_MODEL", "")
        small = model or os.getenv("DEVWATCH_MODEL_SMALL") or os.getenv("DEVWATCH_FAST_MODEL") or os.getenv("LLM_MODEL") or ""
        medium = model or os.getenv("DEVWATCH_MODEL_MEDIUM") or os.getenv("LLM_MODEL") or small
        strong = os.getenv("DEVWATCH_MODEL_STRONG") or os.getenv("DEVWATCH_HEAVY_MODEL") or medium
        raw_tokens = os.getenv("DEVWATCH_JOB_TOKENS", "").strip()
        default_job_tokens = int(raw_tokens) if raw_tokens.isdigit() and int(raw_tokens) > 0 else None
        return cls(
            runtime_root=Path(os.getenv("DEVWATCH_RUNTIME_DIR", ".devwatch/runtime")),
            models={
                ModelTier.SMALL: small,
                ModelTier.MEDIUM: medium,
                ModelTier.STRONG: strong,
            },
            api_keys=frozenset({key}) if key else frozenset(),
            production=os.getenv("DEVWATCH_ENV", "development").lower() == "production",
            default_job_tokens=default_job_tokens,
        )

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


class WorkspaceRequest(ContractModel):
    path: str = Field(min_length=1, max_length=4096)


class SnapshotRequest(ContractModel):
    files: dict[str, str] = Field(max_length=100)
    capture_coverage: CaptureCoverage = Field(default_factory=CaptureCoverage)
    git_metadata: GitMetadata = Field(default_factory=GitMetadata)


class JobRequest(ContractModel):
    snapshot_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    workspace_path: str | None = Field(default=None, min_length=1, max_length=4096)
    changed_files: list[str] | None = Field(default=None, max_length=1000)
    context_files: list[str] | None = Field(default=None, max_length=4)
    execution_mode: Literal["parallel", "balanced", "sequential"] | None = None
    job_tokens: int | None = Field(default=None, ge=1)


class HealthResponse(ContractModel):
    status: str
    workflow_version: Literal["seven-agent-v1"]


class WorkspaceResponse(ContractModel):
    path: str | None = None


class WorkspacePickResponse(ContractModel):
    path: str | None = None
    cancelled: bool | None = None
    error: str | None = None


class FsEntryModel(ContractModel):
    name: str
    path: str
    type: Literal["file", "dir"]
    size: int = Field(ge=0)
    isSymlink: bool
    ignored: bool


class FsListResponse(ContractModel):
    root: str
    path: str
    entries: list[FsEntryModel]


class FsReadResponse(ContractModel):
    path: str
    size: int = Field(ge=0)
    binary: bool
    tooLarge: bool
    maxBytes: int = Field(ge=0)
    lineCount: int | None = None
    content: str | None = None


class EventsResponse(ContractModel):
    events: list[JobEvent]
    next_cursor: int = Field(ge=0)


class JobsListResponse(ContractModel):
    jobs: list[JobView]


def _public_job(job):
    data = {
        field: getattr(job, field)
        for field in ("job_id", "status", "workflow_version", "ledger", "limits", "created_at", "updated_at")
    }
    data["snapshot_id"] = job.request.get("snapshot_id")
    if "workspace_path" in job.request:
        data["workspace_path"] = job.request["workspace_path"]
    return data


def _cursor(value):
    if not value.isascii() or not value.isdigit() or len(value) > 19 or int(value) > MAX_EVENT_CURSOR:
        raise ValueError("invalid reconnect cursor")
    return int(value)


def create_app(*, settings: ServiceSettings | None = None, provider=None):
    settings = settings or ServiceSettings.from_env()
    if provider is None:
        from backend.providers.openai_adapter import OpenAIProviderAdapter
        provider_name = os.getenv("DEVWATCH_PROVIDER") or (
            "gemini" if settings.models[ModelTier.SMALL].startswith("gemini-") else "openai")
        provider = OpenAIProviderAdapter(provider_name=provider_name, max_concurrency=3)

    @asynccontextmanager
    async def lifespan(application):
        layout = StoreLayout(settings.runtime_root)
        jobs = JobStore(layout.app_db)
        artifacts = ArtifactStore(layout.app_db)
        executor = CanonicalReviewExecutor(layout, artifacts, jobs, provider, models=settings.models)
        manager = DurableJobManager(jobs, executor, recover_timeout=executor.recover_timeout)
        application.state.jobs = jobs
        application.state.artifacts = artifacts
        application.state.manager = manager
        await manager.start()
        try:
            yield
        finally:
            await manager.close()
            if hasattr(provider, "aclose"):
                await provider.aclose()

    app = FastAPI(title="DevWatch Local Review Service", lifespan=lifespan)
    app.state.workspace = WorkspaceManager()
    app.state.workspaces = {}

    def _workspace_for(principal: str) -> WorkspaceManager:
        manager = app.state.workspaces.get(principal)
        if manager is None:
            manager = app.state.workspace if principal == "local" and "local" not in app.state.workspaces else WorkspaceManager()
            app.state.workspaces[principal] = manager
        return manager
    app.add_middleware(BoundedRequestBody, limit=settings.max_request_bytes)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.allowed_origins),
                       allow_methods=["GET", "POST"], allow_headers=["Authorization", "X-API-Key", "Idempotency-Key", "Last-Event-ID"])

    def owner(request: Request):
        return settings.principal(request.headers, client_host=request.client.host if request.client else "")

    @app.exception_handler(PathOutsideWorkspaceError)
    async def workspace_forbidden(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=403)

    @app.exception_handler(WorkspaceNotSetError)
    async def workspace_not_set(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(WorkspaceNotFoundError)
    async def workspace_not_found(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(WorkspaceError)
    async def workspace_bad_request(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

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

    @app.get("/health", response_model=HealthResponse)
    async def health():
        return {"status": "ok", "workflow_version": "seven-agent-v1"}

    @app.get("/workspace", response_model=WorkspaceResponse)
    async def get_workspace(principal=Depends(owner)):
        ws = _workspace_for(principal)
        return {"path": str(ws.root) if ws.root is not None else None}

    @app.post("/workspace", response_model=WorkspaceResponse)
    async def set_workspace(body: WorkspaceRequest, principal=Depends(owner)):
        resolved = _workspace_for(principal).set_root(body.path)
        return {"path": str(resolved)}

    @app.post("/workspace/pick", response_model=WorkspacePickResponse)
    async def pick_workspace(principal=Depends(owner)):
        def _pick() -> str | None:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            try:
                root.attributes("-topmost", True)
            except Exception:
                pass
            try:
                selected = filedialog.askdirectory(title="Open Workspace Folder")
            finally:
                root.destroy()
            return selected or None

        try:
            selected = await asyncio.to_thread(_pick)
        except Exception as exc:
            return WorkspacePickResponse(path=None, error=str(exc))
        if not selected:
            return {"path": None, "cancelled": True}
        resolved = _workspace_for(principal).set_root(selected)
        return {"path": str(resolved)}

    @app.get("/fs/list", response_model=FsListResponse)
    async def fs_list(path: str = Query(""), principal=Depends(owner)):
        ws = _workspace_for(principal)
        entries = ws.list_dir(path)
        return {
            "root": str(ws.get_root()),
            "path": path,
            "entries": [entry.to_dict() for entry in entries],
        }

    @app.get("/fs/read", response_model=FsReadResponse)
    async def fs_read(path: str = Query(..., min_length=1), principal=Depends(owner)):
        return _workspace_for(principal).read_file(path).to_dict()

    @app.post("/api/snapshots", status_code=201, response_model=SnapshotManifest)
    async def snapshot(body: SnapshotRequest, principal=Depends(owner)):
        return app.state.artifacts.capture(owner=principal, files=body.files, capture_coverage=body.capture_coverage,
                                           git_metadata=body.git_metadata)

    @app.get("/api/jobs", response_model=JobsListResponse)
    async def list_jobs(limit: int = Query(50, ge=1, le=200), principal=Depends(owner)):
        records = app.state.jobs.list_jobs(owner=principal, limit=limit)
        return {"jobs": [_public_job(record) for record in records]}

    @app.post("/api/jobs", status_code=202, response_model=JobView)
    async def submit(body: JobRequest, principal=Depends(owner),
                     idempotency_key: str = Header(min_length=1, max_length=256)):
        payload = body.model_dump(exclude_none=True, exclude={"execution_mode", "job_tokens"})
        ws = _workspace_for(principal)
        if body.workspace_path is not None:
            resolved = ws.set_root(body.workspace_path)
            payload["workspace_path"] = str(resolved)
            manifest = build_workspace_manifest(resolved)
        elif body.snapshot_id is not None:
            manifest = app.state.artifacts.manifest(body.snapshot_id, owner=principal)
        else:
            resolved = ws.get_root()
            payload["workspace_path"] = str(resolved)
            manifest = build_workspace_manifest(resolved)
        validate_context_files(manifest, body.context_files)
        if body.changed_files is not None and any(path not in manifest.entries for path in body.changed_files):
            raise ValueError("changed files must belong to the workspace")
        mode_concurrency = {"sequential": 1, "balanced": 2, "parallel": 3}
        limits = None
        if body.execution_mode is not None or body.job_tokens is not None or settings.default_job_tokens is not None:
            concurrency = mode_concurrency[body.execution_mode] if body.execution_mode is not None else 3
            job_tokens = body.job_tokens if body.job_tokens is not None else settings.default_job_tokens
            limits = BalancedLimits(concurrent_model_calls=concurrency, job_tokens=job_tokens)
        job = await app.state.manager.submit(owner=principal, request=payload,
                                            idempotency_key=idempotency_key, limits=limits)
        return _public_job(job)

    @app.get("/api/jobs/{identity}", response_model=JobView)
    async def job(identity: str, principal=Depends(owner)):
        return _public_job(app.state.jobs.get(identity, owner=principal))

    @app.post("/api/jobs/{identity}/cancel", response_model=JobView)
    async def cancel(identity: str, principal=Depends(owner)):
        return _public_job(await app.state.manager.cancel(identity, owner=principal))

    @app.post("/api/jobs/{identity}/resume", status_code=202, response_model=JobView)
    async def resume(identity: str, principal=Depends(owner)):
        return _public_job(await app.state.manager.resume(identity, owner=principal))

    @app.get("/api/jobs/{identity}/report")
    async def report(identity: str, format: Literal["json", "markdown"] = "json", principal=Depends(owner)):
        record = app.state.jobs.get(identity, owner=principal)
        if record.status != "completed" or record.result is None:
            raise HTTPException(409, "Report is not finalized")
        return Response(record.result[format], media_type="application/json" if format == "json" else "text/markdown",
                        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})

    def repository(identity, principal):
        record = app.state.jobs.get(identity, owner=principal)
        if "workspace_path" in record.request:
            return RepositoryContext(
                app.state.artifacts,
                owner=principal,
                workspace_root=record.request["workspace_path"],
            )
        return RepositoryContext(app.state.artifacts, record.request["snapshot_id"], owner=principal)

    @app.get("/api/jobs/{identity}/snapshot", response_model=SnapshotManifest)
    async def job_snapshot(identity: str, principal=Depends(owner)):
        return repository(identity, principal).manifest

    @app.get("/api/jobs/{identity}/source")
    async def source(identity: str, file_path: str, start_line: int = Query(1, ge=1),
                     end_line: int | None = Query(None, ge=1), principal=Depends(owner)):
        repo = repository(identity, principal)
        work = AgentWorkItem(task_id="__source_view", agent_id=AgentId.SYNTHESIZER_VERIFIER,
                             files=list(repo.manifest.entries), focus="Source view")
        arguments = {"file_path": file_path, "start_line": start_line}
        if end_line is not None:
            arguments["end_line"] = end_line
        observation = repo._read_file(arguments, work)
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
        return app.state.jobs.events(identity, owner=principal, after=after, limit=limit)

    @app.get("/api/jobs/{identity}/events", response_model=EventsResponse)
    async def events(identity: str, after: int = Query(0, ge=0, le=MAX_EVENT_CURSOR), limit: int = Query(100, ge=1, le=1000), principal=Depends(owner)):
        page = replay(identity, principal, after, limit)
        return {"events": page, "next_cursor": page[-1].seq if page else after}

    async def persisted_events(identity, principal, after):
        queue = app.state.jobs.subscribe(identity, owner=principal)
        last_seq = after
        try:
            while True:
                page = replay(identity, principal, last_seq, limit=1000)
                for event in page:
                    if event.seq > last_seq:
                        last_seq = event.seq
                        yield event
                if len(page) < 1000:
                    break
            if app.state.jobs.get(identity, owner=principal).status not in {"queued", "running"}:
                return
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                except TimeoutError:
                    while True:
                        page = replay(identity, principal, last_seq, limit=1000)
                        for item in page:
                            if item.seq > last_seq:
                                last_seq = item.seq
                                yield item
                        if len(page) < 1000:
                            break
                    if app.state.jobs.get(identity, owner=principal).status not in {"queued", "running"}:
                        return
                    continue
                if event.seq <= last_seq:
                    continue
                if event.seq > last_seq + 1:
                    page = replay(identity, principal, last_seq, limit=1000)
                    for item in page:
                        if item.seq > last_seq:
                            last_seq = item.seq
                            yield item
                if event.seq > last_seq:
                    last_seq = event.seq
                    yield event
                if event.type in {"job_completed", "job_failed", "job_cancelled", "job_interrupted"}:
                    return
        finally:
            app.state.jobs.unsubscribe(identity, queue)

    @app.get("/api/jobs/{identity}/stream")
    async def stream(identity: str, after: int = Query(0, ge=0, le=MAX_EVENT_CURSOR), principal=Depends(owner),
                     last_event_id: str | None = Header(None)):
        if last_event_id is not None:
            after = _cursor(last_event_id)
        replay(identity, principal, after)
        async def frames():
            async for event in persisted_events(identity, principal, after):
                yield f"id: {event.seq}\nevent: {event.type}\ndata: {event.model_dump_json()}\n\n"
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
                    await asyncio.wait_for(socket.send_json(event.model_dump(mode="json")), timeout=5)
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
        except TimeoutError:
            await socket.close(code=1013)
        except (HTTPException, JobNotFound, ValueError):
            await socket.close(code=1008)
        finally:
            for viewer in viewers:
                if not viewer.done():
                    viewer.cancel()
            await asyncio.gather(*viewers, return_exceptions=True)

    return app
