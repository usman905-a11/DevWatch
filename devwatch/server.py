import os
import uuid
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Query, Header, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from devwatch.config import Config
from devwatch.crew.orchestrator import CodeReviewEngine
from devwatch.scanner import CodebaseScanner
from devwatch.models import ReviewReport, AgentStepUpdate, RemediationProposal
from devwatch.agents.llm import OpenRouterRateLimitError
from devwatch.storage import ReportStorage
from devwatch.auth import verify_api_key, authenticate_ws_connection, verify_report_access
from devwatch.rate_limiter import rate_limiter
from devwatch.audit_log import log_review_created, log_fix_applied, log_authz_failure, log_proposal_created, log_remediation_event
from devwatch.tools.fix_applier import apply_code_fix
from devwatch.patcher import RemediationPatcher


from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate server security configuration on startup (fails closed in production mode)."""
    Config.validate_security_config()
    yield


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

report_storage = ReportStorage()
REPORTS_DB: Dict[str, Dict[str, Any]] = {}
executor = ThreadPoolExecutor(max_workers=4)


class ReviewRequest(BaseModel):
    target_path: str = "."


class SingleFileAuditRequest(BaseModel):
    file_path: str
    content: str


class MultiFileAuditRequest(BaseModel):
    files: List[SingleFileAuditRequest]


class WriteFileRequest(BaseModel):
    root_path: str = "."
    file_path: str
    content: str


class ApplyFixRequest(BaseModel):
    root_path: str = "."
    file_path: str
    line_number: int = 1
    target_snippet: str = ""
    replacement_code: str
    finding_id: str = "finding_1"


class ProposeFixRequest(BaseModel):
    root_path: str = "."
    file_path: str
    finding_id: str = "finding_1"
    start_line: int = 1
    end_line: int = 1
    target_snippet: str = ""
    replacement_code: str
    reason: str = "Code remediation proposal"


class ApplyProposalRequest(BaseModel):
    root_path: str = "."
    proposal: RemediationProposal



@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": "DevWatch API", "version": "0.1.0", "env": Config.ENV}


@app.post("/api/review/files", dependencies=[Depends(verify_api_key)])
async def trigger_files_audit(request_obj: Request, request: MultiFileAuditRequest, client_identity: str = Depends(verify_api_key)):
    client_ip = request_obj.client.host if request_obj.client else "unknown"
    rate_limiter.check_rate_limit(client_ip, Config.RATE_LIMIT_REVIEWS_RPM, window_seconds=60, endpoint="/api/review/files")

    crew = CodeReviewEngine()
    try:
        file_dicts = [{"file_path": f.file_path, "content": f.content} for f in request.files]
        report = await crew.arun_files_audit(file_dicts)
        report_dict = report.model_dump()
        report_dict["total_issues"] = report.total_issues
        log_review_created("in_memory_batch", "uploaded_files", client_identity)
        return {"status": "completed", "report": report_dict}
    except OpenRouterRateLimitError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except Exception as e:
        if "429" in str(e) or "Rate limit" in str(e) or "free-models-per-day" in str(e):
            raise HTTPException(status_code=429, detail="OpenRouter daily free rate limit reached (50/50 requests used today). Please wait for daily reset or add credits to your OpenRouter account.")
        raise HTTPException(status_code=500, detail=f"Files audit failed: {str(e)}")


@app.post("/api/review/file", dependencies=[Depends(verify_api_key)])
async def trigger_file_audit(request_obj: Request, request: SingleFileAuditRequest, client_identity: str = Depends(verify_api_key)):
    client_ip = request_obj.client.host if request_obj.client else "unknown"
    rate_limiter.check_rate_limit(client_ip, Config.RATE_LIMIT_REVIEWS_RPM, window_seconds=60, endpoint="/api/review/file")

    crew = CodeReviewEngine()
    try:
        report = await crew.arun_file_audit(request.file_path, request.content)
        report_dict = report.model_dump()
        report_dict["total_issues"] = report.total_issues
        log_review_created("single_file", request.file_path, client_identity)
        return {"status": "completed", "report": report_dict}
    except OpenRouterRateLimitError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except Exception as e:
        if "429" in str(e) or "Rate limit" in str(e) or "free-models-per-day" in str(e):
            raise HTTPException(status_code=429, detail="OpenRouter daily free rate limit reached (50/50 requests used today). Please wait for daily reset or add credits to your OpenRouter account.")
        raise HTTPException(status_code=500, detail=f"File audit failed: {str(e)}")


@app.get("/api/fs/tree", dependencies=[Depends(verify_api_key)])
def get_fs_tree(request_obj: Request, root: str = Query(".", description="Root directory path")):
    client_ip = request_obj.client.host if request_obj.client else "unknown"
    rate_limiter.check_rate_limit(client_ip, Config.RATE_LIMIT_RPM, window_seconds=60, endpoint="/api/fs/tree")

    try:
        scanner = CodebaseScanner(root)
        tree = scanner.get_tree_structure()
        files = scanner.get_files()
        return {"root": root, "tree": tree, "files": files}
    except ValueError as e:
        status_code = 403 if "Access denied" in str(e) or "blocked" in str(e) else 400
        raise HTTPException(status_code=status_code, detail=str(e))


@app.get("/api/fs/read", dependencies=[Depends(verify_api_key)])
def read_file_content(
    request_obj: Request,
    path: str = Query(..., description="Relative file path"),
    root: str = Query(".", description="Root directory path"),
):
    client_ip = request_obj.client.host if request_obj.client else "unknown"
    rate_limiter.check_rate_limit(client_ip, Config.RATE_LIMIT_RPM, window_seconds=60, endpoint="/api/fs/read")

    try:
        scanner = CodebaseScanner(root)
        content = scanner.read_file(path)
        return {"path": path, "content": content}
    except ValueError as e:
        status_code = 403 if "Access denied" in str(e) or "blocked" in str(e) else 400
        raise HTTPException(status_code=status_code, detail=str(e))


@app.post("/api/fs/write", dependencies=[Depends(verify_api_key)])
def write_file_content(request_obj: Request, request: WriteFileRequest):
    client_ip = request_obj.client.host if request_obj.client else "unknown"
    rate_limiter.check_rate_limit(client_ip, Config.RATE_LIMIT_RPM, window_seconds=60, endpoint="/api/fs/write")

    try:
        scanner = CodebaseScanner(request.root_path)
        success = scanner.write_file(request.file_path, request.content)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to write file")
        return {"status": "success", "path": request.file_path}
    except ValueError as e:
        status_code = 403 if "Access denied" in str(e) or "blocked" in str(e) else 400
        raise HTTPException(status_code=status_code, detail=str(e))


@app.post("/api/review", dependencies=[Depends(verify_api_key)])
async def trigger_review(request_obj: Request, request: ReviewRequest, client_identity: str = Depends(verify_api_key)):
    client_ip = request_obj.client.host if request_obj.client else "unknown"
    rate_limiter.check_rate_limit(client_ip, Config.RATE_LIMIT_REVIEWS_RPM, window_seconds=60, endpoint="/api/review")

    report_id = str(uuid.uuid4())
    steps: List[AgentStepUpdate] = []

    def on_step(update: AgentStepUpdate):
        update.timestamp = time.time()
        steps.append(update)

    try:
        CodebaseScanner(request.target_path)
        crew = CodeReviewEngine(step_callback=on_step)
        report: ReviewReport = await crew.arun(request.target_path)
    except ValueError as e:
        status_code = 403 if "Access denied" in str(e) or "blocked" in str(e) else 400
        raise HTTPException(status_code=status_code, detail=str(e))
    except OpenRouterRateLimitError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except Exception as e:
        if "429" in str(e) or "Rate limit" in str(e) or "free-models-per-day" in str(e):
            raise HTTPException(status_code=429, detail="OpenRouter daily free rate limit reached (50/50 requests used today). Please wait for daily reset or add credits to your OpenRouter account.")
        raise HTTPException(status_code=500, detail=f"Review failed: {str(e)}")

    report_dict = report.model_dump()
    report_dict["total_issues"] = report.total_issues
    report_dict["critical_count"] = report.critical_count
    report_dict["high_count"] = report.high_count
    report_dict["medium_count"] = report.medium_count
    report_dict["low_count"] = report.low_count

    report_data = {
        "report_id": report_id,
        "owner": client_identity,
        "target_path": request.target_path,
        "status": "completed",
        "timestamp": time.time(),
        "steps": [s.model_dump() for s in steps],
        "report": report_dict,
        "summary_markdown": report.summary,
    }

    REPORTS_DB[report_id] = report_data
    report_storage.save_report(report_id, report_data)
    log_review_created(report_id, request.target_path, client_identity)
    return report_data


@app.post("/api/review/propose-fix", dependencies=[Depends(verify_api_key)])
def propose_remediation_fix(request_obj: Request, request: ProposeFixRequest, client_identity: str = Depends(verify_api_key)):
    client_ip = request_obj.client.host if request_obj.client else "unknown"
    rate_limiter.check_rate_limit(client_ip, Config.RATE_LIMIT_RPM, window_seconds=60, endpoint="/api/review/propose-fix")

    try:
        patcher = RemediationPatcher(request.root_path)
        proposal = patcher.propose_fix(
            file_path=request.file_path,
            finding_id=request.finding_id,
            start_line=request.start_line,
            end_line=request.end_line,
            target_snippet=request.target_snippet,
            replacement_code=request.replacement_code,
            reason=request.reason,
            author=client_identity,
        )
        log_proposal_created(proposal.proposal_id, request.finding_id, request.file_path, client_identity)
        return {"status": "success", "proposal": proposal.model_dump()}
    except (ValueError, FileNotFoundError) as err:
        status_code = 403 if "Access denied" in str(err) or "blocked" in str(err) else 400
        raise HTTPException(status_code=status_code, detail=str(err))
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Failed to propose code fix: {str(err)}")


@app.post("/api/review/apply-proposal", dependencies=[Depends(verify_api_key)])
def apply_remediation_proposal(request_obj: Request, request: ApplyProposalRequest, client_identity: str = Depends(verify_api_key)):
    client_ip = request_obj.client.host if request_obj.client else "unknown"
    rate_limiter.check_rate_limit(client_ip, Config.RATE_LIMIT_RPM, window_seconds=60, endpoint="/api/review/apply-proposal")

    try:
        patcher = RemediationPatcher(request.root_path)
        result = patcher.apply_proposal(request.proposal, authorized_by=client_identity)
        if not result.success:
            raise HTTPException(status_code=400, detail=result.error_message)
        log_remediation_event("REMEDIATION_APPLIED", request.proposal.proposal_id, request.proposal.file_path, client_identity)
        return {"status": "success", "result": result.model_dump()}
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Failed to apply proposal: {str(err)}")


@app.post("/api/review/apply-fix", dependencies=[Depends(verify_api_key)])
def apply_quick_fix(request_obj: Request, request: ApplyFixRequest, client_identity: str = Depends(verify_api_key)):
    client_ip = request_obj.client.host if request_obj.client else "unknown"
    rate_limiter.check_rate_limit(client_ip, Config.RATE_LIMIT_RPM, window_seconds=60, endpoint="/api/review/apply-fix")

    try:
        res = apply_code_fix(
            root_dir=request.root_path,
            file_path=request.file_path,
            line_number=request.line_number,
            target_snippet=request.target_snippet,
            replacement_code=request.replacement_code,
            finding_id=request.finding_id,
            authorized_by=client_identity,
        )
        log_fix_applied(request.file_path, request.line_number, client_identity)
        return {
            "status": "success",
            "file_path": request.file_path,
            "line_number": request.line_number,
            "modified": res.success,
            "diff_preview": res.diff_preview,
        }
    except (ValueError, FileNotFoundError) as err:
        status_code = 403 if "Access denied" in str(err) or "blocked" in str(err) else 400
        raise HTTPException(status_code=status_code, detail=str(err))
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Failed to apply code fix: {str(err)}")



@app.get("/api/reports/{report_id}", dependencies=[Depends(verify_api_key)])
def get_report(report_id: str, client_identity: str = Depends(verify_api_key)):
    report_data = REPORTS_DB.get(report_id) or report_storage.get_report(report_id)
    if not report_data:
        raise HTTPException(status_code=404, detail="Report not found")
    
    verify_report_access(report_data, client_identity)
    REPORTS_DB[report_id] = report_data
    return report_data


@app.websocket("/ws/review")
async def websocket_review_endpoint(websocket: WebSocket):
    # Enforce WebSocket authentication
    ws_identity = await authenticate_ws_connection(websocket)
    await websocket.accept()

    queue: asyncio.Queue = asyncio.Queue()

    try:
        data = await websocket.receive_json()
        target_path = data.get("target_path", ".")

        def sync_step_callback(update: AgentStepUpdate):
            update.timestamp = time.time()
            queue.put_nowait(update)

        async def stream_queue():
            while True:
                item = await queue.get()
                if item is None:
                    break
                payload = item.model_dump()
                payload["type"] = "agent_update"
                await websocket.send_json(payload)
                queue.task_done()

        stream_task = asyncio.create_task(stream_queue())

        CodebaseScanner(target_path)
        crew = CodeReviewEngine(step_callback=sync_step_callback)
        report = await crew.arun(target_path)
        await queue.put(None)
        await stream_task

        log_review_created("ws_review", target_path, ws_identity)

        await websocket.send_json(
            {
                "type": "review_completion",
                "status": "COMPLETED",
                "message": "Review complete!",
                "report": report.model_dump(),
            }
        )
    except WebSocketDisconnect:
        pass
    except Exception as e:
        status_code = 403 if "Access denied" in str(e) or "blocked" in str(e) else 400
        await websocket.send_json({"type": "review_error", "status": "FAILED", "message": str(e)})
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
