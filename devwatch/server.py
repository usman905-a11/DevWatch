import uuid
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from devwatch.crew.orchestrator import CodeReviewEngine
from devwatch.scanner import CodebaseScanner
from devwatch.models import ReviewReport, AgentStepUpdate

app = FastAPI(
    title="DevWatch API",
    description="Multi-Agent Code Review & VS Code IDE Backend Server",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

REPORTS_DB: Dict[str, Dict[str, Any]] = {}
executor = ThreadPoolExecutor(max_workers=4)


class ReviewRequest(BaseModel):
    target_path: str = "."


class SingleFileAuditRequest(BaseModel):
    file_path: str
    content: str


class WriteFileRequest(BaseModel):
    root_path: str = "."
    file_path: str
    content: str


@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": "DevWatch API", "version": "0.1.0"}


@app.get("/api/fs/tree")
def get_fs_tree(root: str = Query(".", description="Root directory path")):
    scanner = CodebaseScanner(root)
    tree = scanner.get_tree_structure()
    files = scanner.get_files()
    return {"root": root, "tree": tree, "files": files}


@app.get("/api/fs/read")
def read_file_content(
    path: str = Query(..., description="Relative file path"),
    root: str = Query(".", description="Root directory path"),
):
    scanner = CodebaseScanner(root)
    content = scanner.read_file(path)
    return {"path": path, "content": content}


@app.post("/api/fs/write")
def write_file_content(request: WriteFileRequest):
    scanner = CodebaseScanner(request.root_path)
    success = scanner.write_file(request.file_path, request.content)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to write file")
    return {"status": "success", "path": request.file_path}


@app.post("/api/review/file")
def trigger_file_audit(request: SingleFileAuditRequest):
    crew = CodeReviewEngine()
    try:
        report = crew.run_file_audit(request.file_path, request.content)
        report_dict = report.model_dump()
        report_dict["total_issues"] = report.total_issues
        return {"status": "completed", "report": report_dict}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File audit failed: {str(e)}")


@app.post("/api/review")
def trigger_review(request: ReviewRequest):
    report_id = str(uuid.uuid4())
    steps: List[AgentStepUpdate] = []

    def on_step(update: AgentStepUpdate):
        update.timestamp = time.time()
        steps.append(update)

    crew = CodeReviewEngine(step_callback=on_step)

    try:
        report: ReviewReport = crew.run(request.target_path)
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
    return report_data


@app.get("/api/reports/{report_id}")
def get_report(report_id: str):
    if report_id not in REPORTS_DB:
        raise HTTPException(status_code=404, detail="Report not found")
    return REPORTS_DB[report_id]


@app.websocket("/ws/review")
async def websocket_review_endpoint(websocket: WebSocket):
    await websocket.accept()
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    try:
        data = await websocket.receive_json()
        target_path = data.get("target_path", ".")

        def sync_step_callback(update: AgentStepUpdate):
            update.timestamp = time.time()
            loop.call_soon_threadsafe(queue.put_nowait, update)

        async def stream_queue():
            while True:
                item = await queue.get()
                if item is None:
                    break
                await websocket.send_json(item.model_dump())
                queue.task_done()

        stream_task = asyncio.create_task(stream_queue())

        def run_crew():
            crew = CodeReviewEngine(step_callback=sync_step_callback)
            return crew.run(target_path)

        report = await loop.run_in_executor(executor, run_crew)
        await queue.put(None)
        await stream_task

        await websocket.send_json(
            {
                "status": "COMPLETED",
                "message": "Review complete!",
                "report": report.model_dump(),
            }
        )
    except WebSocketDisconnect:
        pass
    except Exception as e:
        await websocket.send_json({"status": "FAILED", "message": str(e)})
    finally:
        try:
            await websocket.close()
        except Exception:
            pass

