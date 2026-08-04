import sys
import asyncio
import pytest
from pathlib import Path
from devwatch.crew.orchestrator import CodeReviewEngine
from devwatch.agents.security import SecurityAuditorAgent
from devwatch.agents.quality import QualityAuditorAgent
from devwatch.agents.verifier import VerificationAgent


def test_nest_asyncio_not_in_modules_or_codebase():
    """Verify nest_asyncio is nowhere imported or used in devwatch."""
    assert "nest_asyncio" not in sys.modules

    devwatch_root = Path(__file__).parent.parent / "devwatch"
    for py_file in devwatch_root.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "nest_asyncio" not in content, f"nest_asyncio found in {py_file}"


@pytest.mark.asyncio
async def test_sync_run_raises_runtime_error_in_event_loop():
    """Verify calling synchronous run() inside a running loop raises RuntimeError."""
    engine = CodeReviewEngine()

    with pytest.raises(RuntimeError) as exc_info:
        engine.run(".")
    assert "active asyncio event loop" in str(exc_info.value)

    sec_agent = SecurityAuditorAgent()
    with pytest.raises(RuntimeError) as exc_info:
        sec_agent.analyze("test.py", "def foo(): pass")
    assert "active event loop" in str(exc_info.value)

    qual_agent = QualityAuditorAgent()
    with pytest.raises(RuntimeError) as exc_info:
        qual_agent.analyze("test.py", "def foo(): pass")
    assert "active event loop" in str(exc_info.value)

    verifier = VerificationAgent()
    with pytest.raises(RuntimeError) as exc_info:
        verifier.verify_issues("test.py", "def foo(): pass", [])
    assert "active event loop" in str(exc_info.value)



@pytest.mark.asyncio
async def test_async_arun_execution_without_nest_asyncio(tmp_path, monkeypatch):
    """Verify arun() executes natively in async context without nest_asyncio."""
    from unittest.mock import patch
    (tmp_path / "app.py").write_text("def index(): return 'hello'")
    engine = CodeReviewEngine()

    with patch("devwatch.agents.llm.is_llm_available", return_value=False):
        report = await engine.arun(str(tmp_path))
        assert report is not None
        assert report.target_path == str(tmp_path)


@pytest.mark.asyncio
async def test_concurrent_review_requests(tmp_path):
    """Verify multiple concurrent review requests run in parallel safely."""
    from unittest.mock import patch
    (tmp_path / "file1.py").write_text("x = 1")
    (tmp_path / "file2.py").write_text("y = 2")

    engine1 = CodeReviewEngine()
    engine2 = CodeReviewEngine()

    with patch("devwatch.agents.llm.is_llm_available", return_value=False):
        report1, report2 = await asyncio.gather(
            engine1.arun(str(tmp_path)),
            engine2.arun(str(tmp_path)),
        )

        assert report1 is not None
        assert report2 is not None


@pytest.mark.asyncio
async def test_graceful_task_cancellation(tmp_path):
    """Verify active tasks can be cancelled gracefully without unhandled exceptions."""
    from unittest.mock import patch
    (tmp_path / "main.py").write_text("print('hello')")
    engine = CodeReviewEngine()

    with patch("devwatch.agents.llm.is_llm_available", return_value=False):
        # Launch arun as a background task and immediately cancel
        task = asyncio.create_task(engine.arun(str(tmp_path)))
        await asyncio.sleep(0.001)
        engine.cancel_active_tasks()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task


def test_cli_outermost_sync_execution(tmp_path):
    """Verify CLI synchronous entry point works when no event loop is running."""
    from unittest.mock import patch
    (tmp_path / "cli_sample.py").write_text("def run(): pass")
    engine = CodeReviewEngine()

    with patch("devwatch.agents.llm.is_llm_available", return_value=False):
        # Outside event loop, engine.run() succeeds using asyncio.run()
        report = engine.run(str(tmp_path))
        assert report is not None

