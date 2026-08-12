import os
import pytest
import shutil
import tempfile
from unittest.mock import patch
from pydantic import BaseModel
from devwatch.models import ReviewReport
from devwatch.pipeline.dag import ReviewPipeline
from devwatch.storage import ReportStorage
from devwatch.agents.llm import acall_llm_structured


class DummyAsyncSchema(BaseModel):
    status: str
    code: int


@pytest.mark.asyncio
async def test_acall_llm_structured():
    from devwatch.providers.fake_provider import FakeLLMProvider
    fake_provider = FakeLLMProvider(default_content='{"status": "ok", "code": 200}')
    res = await acall_llm_structured("prompt", DummyAsyncSchema, provider=fake_provider)
    assert res is not None
    assert res.status == "ok"
    assert res.code == 200


@pytest.mark.asyncio
async def test_async_code_review_engine_arun():
    pipeline = ReviewPipeline(max_concurrent_files=2)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    report = await pipeline.execute(current_dir)
    assert isinstance(report, ReviewReport)
    assert report.target_path == current_dir


def test_report_storage_persistence():
    temp_dir = tempfile.mkdtemp()
    try:
        storage1 = ReportStorage(storage_dir=temp_dir)
        report_id = "test-report-12345"
        dummy_data = {
            "report_id": report_id,
            "status": "completed",
            "summary_markdown": "# Summary Test",
        }

        assert storage1.save_report(report_id, dummy_data) is True

        # Create new storage instance pointing to same directory
        storage2 = ReportStorage(storage_dir=temp_dir)
        loaded = storage2.get_report(report_id)
        assert loaded is not None
        assert loaded["report_id"] == report_id
        assert loaded["summary_markdown"] == "# Summary Test"
        assert report_id in storage2.list_reports()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
