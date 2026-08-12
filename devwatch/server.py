import os
import uuid
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional, Set

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Query, Header, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from devwatch.config import Config
from devwatch.pipeline.dag import ReviewPipeline
from devwatch.scanner import CodebaseScanner
from devwatch.models import ReviewReport, AgentStepUpdate, RemediationProposal
from devwatch.agents.llm import OpenRouterRateLimitError
from devwatch.storage import ReportStorage
from devwatch.auth import verify_api_key, authenticate_ws_connection, verify_report_access
from devwatch.rate_limiter import rate_limiter
from devwatch.audit_log import log_review_created, log_fix_applied, log_authz_failure, log_proposal_created, log_remediation_event
from devwatch.patcher import RemediationPatcher


from contextlib import asynccontextmanager


active_review_tasks: Set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate server security configuration on startup and cancel tasks on shutdown."""
    Config.validate_security_config()
    yield
    for task in list(active_review_tasks):
        if not task.done():
            task.cancel()
    if active_review_tasks:
        await asyncio.gather(*active_review_tasks, return_exceptions=True)



from fastapi.responses import JSONResponse
from devwatch.providers.exceptions import (
    ProviderError,
    ProviderRateLimitError,
    ProviderQuotaExhaustedError,
    ProviderAuthenticationError,
)

app = FastAPI(
    title="DevWatch API",
    description="Multi-Agent Code Review & VS Code IDE Backend Server",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(ProviderQuotaExhaustedError)
@app.exception_handler(ProviderRateLimitError)
async def provider_rate_limit_exception_handler(request: Request, exc: ProviderRateLimitError):
    return JSONResponse(
        status_code=429,
        content={"detail": exc.message, "provider": exc.provider},
        headers={"Retry-After": "60"},
    )


@app.exception_handler(ProviderError)
async def provider_generic_exception_handler(request: Request, exc: ProviderError):
    return JSONResponse(
        status_code=500,
        content={"detail": f"LLM Provider Error: {exc.message}", "provider": exc.provider},
    )




def get_allowed_origins() -> List[str]:
    raw = os.getenv(
        "DEVWATCH_ALLOWED_ORIGINS",
        "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173",
    )
    if raw.strip() == "*":
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

from devwatch.routers import fs_router, review_router, ws_router

app.include_router(fs_router)
app.include_router(review_router)
app.include_router(ws_router)


@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": "DevWatch API", "version": "0.1.0", "env": Config.ENV}
