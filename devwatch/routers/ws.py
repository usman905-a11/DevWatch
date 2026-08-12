import time
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from devwatch.pipeline.dag import ReviewPipeline
from devwatch.scanner import CodebaseScanner
from devwatch.models import AgentStepUpdate
from devwatch.auth import authenticate_ws_connection
from devwatch.audit_log import log_review_created

ws_router = APIRouter(prefix="/ws", tags=["websocket"])


@ws_router.websocket("/review")
async def websocket_review_endpoint(websocket: WebSocket):
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
        pipeline = ReviewPipeline(step_callback=sync_step_callback)
        report = await pipeline.execute(target_path)
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
