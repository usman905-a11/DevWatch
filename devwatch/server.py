import os
import uuid
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Query, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from devwatch.crew.orchestrator import CodeReviewEngine
from devwatch.scanner import CodebaseScanner
from devwatch.models import ReviewReport, AgentStepUpdate
from devwatch.storage import ReportStorage

app = FastAPI(
    title="DevWatch API",
    description="Multi-Agent Code Review & VS Code IDE Backend Server",
    version="0.1.0",
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


def verify_api_key(x_api_key: Optional[str] = Header(None, alias="x-api-key")):
    """Enforce API Key verification if DEVWATCH_API_KEY environment variable is configured."""
    expected_key = os.getenv("DEVWATCH_API_KEY")
    if expected_key:
        if not x_api_key or x_api_key != expected_key:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")


from devwatch.tools.fix_applier import apply_code_fix


class ReviewRequest(BaseModel):
    target_path: str = "."


class SingleFileAuditRequest(BaseModel):
    file_path: str
    content: str


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


@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": "DevWatch API", "version": "0.1.0"}


@app.get("/api/fs/tree", dependencies=[Depends(verify_api_key)])
def get_fs_tree(root: str = Query(".", description="Root directory path")):
    try:
        scanner = CodebaseScanner(root)
        tree = scanner.get_tree_structure()
        files = scanner.get_files()
        return {"root": root, "tree": tree, "files": files}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/fs/read", dependencies=[Depends(verify_api_key)])
def read_file_content(
    path: str = Query(..., description="Relative file path"),
    root: str = Query(".", description="Root directory path"),
):
    try:
        scanner = CodebaseScanner(root)
        content = scanner.read_file(path)
        return {"path": path, "content": content}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/fs/write", dependencies=[Depends(verify_api_key)])
def write_file_content(request: WriteFileRequest):
    try:
        scanner = CodebaseScanner(request.root_path)
        success = scanner.write_file(request.file_path, request.content)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to write file")
        return {"status": "success", "path": request.file_path}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/review/file", dependencies=[Depends(verify_api_key)])
async def trigger_file_audit(request: SingleFileAuditRequest):
    crew = CodeReviewEngine()
    try:
        report = await crew.arun_file_audit(request.file_path, request.content)
        report_dict = report.model_dump()
        report_dict["total_issues"] = report.total_issues
        return {"status": "completed", "report": report_dict}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File audit failed: {str(e)}")


@app.post("/api/review", dependencies=[Depends(verify_api_key)])
async def trigger_review(request: ReviewRequest):
    report_id = str(uuid.uuid4())
    steps: List[AgentStepUpdate] = []

    def on_step(update: AgentStepUpdate):
        update.timestamp = time.time()
        steps.append(update)

    crew = CodeReviewEngine(step_callback=on_step)

    try:
        report: ReviewReport = await crew.arun(request.target_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Review failed: {str(e)}")

    report_dict = report.model_dump()
    report_dict["total_issues"] = report.total_issues
    report_dict["critical_count"] = report.critical_count
    report_dict["high_count"] = report.high_count
    report_dict["medium_count"] = report.medium_count
    report_dict["low_count"] = report.low_count

    report_data = {
        "report_id": report_id,
        "target_path": request.target_path,
        "status": "completed",
        "timestamp": time.time(),
        "steps": [s.model_dump() for s in steps],
        "report": report_dict,
        "summary_markdown": report.summary,
    }

    REPORTS_DB[report_id] = report_data
    report_storage.save_report(report_id, report_data)
    return report_data


@app.post("/api/review/apply-fix", dependencies=[Depends(verify_api_key)])
def apply_quick_fix(request: ApplyFixRequest):
    try:
        success = apply_code_fix(
            root_dir=request.root_path,
            file_path=request.file_path,
            line_number=request.line_number,
            target_snippet=request.target_snippet,
            replacement_code=request.replacement_code,
        )
        return {
            "status": "success",
            "file_path": request.file_path,
            "line_number": request.line_number,
            "modified": success,
        }
    except (ValueError, FileNotFoundError) as err:
        raise HTTPException(status_code=400, detail=str(err))
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Failed to apply code fix: {str(err)}")


@app.get("/api/reports/{report_id}", dependencies=[Depends(verify_api_key)])
def get_report(report_id: str):
    if report_id in REPORTS_DB:
        return REPORTS_DB[report_id]
    report_data = report_storage.get_report(report_id)
    if not report_data:
        raise HTTPException(status_code=404, detail="Report not found")
    REPORTS_DB[report_id] = report_data
    return report_data


@app.websocket("/ws/review")
async def websocket_review_endpoint(websocket: WebSocket):
    expected_key = os.getenv("DEVWATCH_API_KEY")
    if expected_key:
        api_key = websocket.query_params.get("api_key") or websocket.headers.get("x-api-key")
        if not api_key or api_key != expected_key:
            await websocket.close(code=4001, reason="Unauthorized: Invalid API key")
            return

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

        crew = CodeReviewEngine(step_callback=sync_step_callback)
        report = await crew.arun(target_path)
        await queue.put(None)
        await stream_task

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
        await websocket.send_json({"type": "review_error", "status": "FAILED", "message": str(e)})
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


