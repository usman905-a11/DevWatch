import asyncio
import time
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from devwatch.auth import authenticate_ws_connection
from devwatch.models import AgentStepUpdate
from devwatch.operations import ReviewOperations
from devwatch.routers import review as review_routes

ws_router = APIRouter(prefix="/ws", tags=["websocket"])


@ws_router.websocket("/review")
async def websocket_review_endpoint(websocket: WebSocket):
    ws_identity = await authenticate_ws_connection(websocket)
    await websocket.accept()

    queue: asyncio.Queue[AgentStepUpdate | None] = asyncio.Queue()
    steps: list[AgentStepUpdate] = []
    pipeline_task = None
    stream_task = None
    disconnect_task = None

    try:
        data = await websocket.receive_json()
        target_path = data.get("target_path", ".")

        def on_step(update: AgentStepUpdate) -> None:
            update.timestamp = time.time()
            steps.append(update)
            queue.put_nowait(update)

        async def stream_queue() -> None:
            while True:
                item = await queue.get()
                try:
                    if item is None:
                        return
                    await websocket.send_json({"type": "agent_update", **item.model_dump()})
                finally:
                    queue.task_done()

        async def watch_disconnect() -> None:
            while True:
                event = await websocket.receive()
                if event["type"] == "websocket.disconnect":
                    return

        stream_task = asyncio.create_task(stream_queue())
        disconnect_task = asyncio.create_task(watch_disconnect())
        operations = ReviewOperations()
        pipeline_task = asyncio.create_task(
            operations.audit_repository(
                target_path=target_path,
                client_identity=ws_identity,
                client_ip=websocket.client.host if websocket.client else "unknown",
                step_callback=on_step,
            )
        )
        done, _ = await asyncio.wait(
            {pipeline_task, stream_task, disconnect_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if disconnect_task in done:
            return
        if stream_task in done:
            stream_task.result()
            raise RuntimeError("Progress stream ended before the review")
        report = pipeline_task.result()
        await queue.put(None)
        await stream_task

        report_id = str(uuid.uuid4())
        report_data = review_routes.create_report_record(
            report_id, report, target_path, ws_identity, steps
        )
        if not review_routes.report_storage.save_report(report_id, report_data):
            raise RuntimeError("Report could not be saved")
        await websocket.send_json({
            "type": "review_completion",
            "status": "COMPLETED",
            "message": "Review complete!",
            "report_id": report_id,
            "report": report_data["report"],
        })
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        raise
    except Exception as error:
        try:
            await websocket.send_json({
                "type": "review_error",
                "status": "FAILED",
                "message": str(error),
            })
        except (RuntimeError, WebSocketDisconnect):
            pass
    finally:
        for task in (pipeline_task, stream_task, disconnect_task):
            if task is not None and not task.done():
                task.cancel()
        pending = [
            task for task in (pipeline_task, stream_task, disconnect_task)
            if task is not None
        ]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        try:
            await websocket.close()
        except Exception:
            pass
