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
    pipeline_task = None
    stream_task = None

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
        pipeline_task = asyncio.create_task(pipeline.execute(target_path))
        done, _ = await asyncio.wait(
            {pipeline_task, stream_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if stream_task in done and not pipeline_task.done():
            pipeline.cancel_active_tasks()
            pipeline_task.cancel()
            await asyncio.gather(pipeline_task, return_exceptions=True)
            stream_task.result()
        report = await pipeline_task
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
        if pipeline_task and not pipeline_task.done():
            pipeline_task.cancel()
            await asyncio.gather(pipeline_task, return_exceptions=True)
    except Exception as e:
        try:
            await websocket.send_json(
                {"type": "review_error", "status": "FAILED", "message": str(e)}
            )
        except (RuntimeError, WebSocketDisconnect):
            pass
    finally:
        for task in (pipeline_task, stream_task):
            if task and not task.done():
                task.cancel()
        pending = [task for task in (pipeline_task, stream_task) if task]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        try:
            await websocket.close()
        except Exception:
            pass
