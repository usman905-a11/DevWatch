import uuid
import time
from typing import Dict, Any, List
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from devwatch.crew.orchestrator import CodeReviewCrew
from devwatch.models import ReviewReport, AgentStepUpdate

app = FastAPI(
    title="DevWatch API",
    description="Multi-Agent Code Review Backend Server",
    version="0.1.0",
)

# Enable CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory store for reports
REPORTS_DB: Dict[str, Dict[str, Any]] = {}


class ReviewRequest(BaseModel):
    target_path: str = "."


@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": "DevWatch API", "version": "0.1.0"}


@app.post("/api/review")
def trigger_review(request: ReviewRequest):
    report_id = str(uuid.uuid4())
    steps: List[AgentStepUpdate] = []

    def on_step(update: AgentStepUpdate):
        update.timestamp = time.time()
        steps.append(update)

    crew = CodeReviewCrew(step_callback=on_step)

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
    try:
        data = await websocket.receive_json()
        target_path = data.get("target_path", ".")

        async def send_update(update: AgentStepUpdate):
            update.timestamp = time.time()
            await websocket.send_json(update.model_dump())

        # For synchronous execution callback to async websocket
        def sync_step_callback(update: AgentStepUpdate):
            update.timestamp = time.time()
            # Send sync update json string via websocket if connected
            import asyncio

            asyncio.run(websocket.send_json(update.model_dump()))

        crew = CodeReviewCrew(step_callback=sync_step_callback)
        report = crew.run(target_path)

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
        await websocket.close()
