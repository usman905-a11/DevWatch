"""Accepted-only PDF interfaces. Runtime rendering is an owned child process."""
import asyncio
from pathlib import Path
import sys

from devwatch.review.finalization import AcceptedReport


def render_accepted_pdf(report: AcceptedReport) -> bytes:
    if not isinstance(report, AcceptedReport):
        raise TypeError("PDF renderer requires an accepted structured draft")
    from devwatch.review._pdf_document import render_document
    return render_document(report.draft.model_dump(mode="json"))


async def render_accepted_pdf_async(report: AcceptedReport) -> bytes:
    if not isinstance(report, AcceptedReport):
        raise TypeError("PDF renderer requires an accepted structured draft")
    payload = report._data.encode("utf-8")
    if len(payload) > 10_000_000:
        raise ValueError("PDF input exceeds its byte limit")
    # Only the post-acceptance runtime launches this fixed worker. The worker has
    # no store access or destination parameter; JSON is data, never executable.
    spawn = asyncio.create_task(asyncio.create_subprocess_exec(sys.executable,
        str(Path(__file__).with_name("pdf_worker.py")), stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL))
    exchange = None
    try:
        process = await asyncio.shield(spawn)
        exchange = asyncio.create_task(process.communicate(payload))
        data, _ = await asyncio.shield(exchange)
        if (process.returncode != 0 or len(data) > 10_000_000
                or not data.startswith(b"%PDF-") or not data.rstrip().endswith(b"%%EOF")):
            raise RuntimeError("PDF renderer failed")
        return data
    except BaseException:
        async def drain():
            try:
                process = await spawn
            except Exception:
                return
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            if exchange is not None:
                await asyncio.gather(exchange, return_exceptions=True)
            await process.wait()
        cleanup = asyncio.create_task(drain())
        # Even repeated shutdown/cancel requests must not detach child cleanup.
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                continue
        cleanup.result()
        raise
