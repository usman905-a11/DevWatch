import pytest
import asyncio
import time
import sys
import tracemalloc
from unittest.mock import patch, AsyncMock
from devwatch.pipeline.dag import ReviewPipeline, BoundedCandidateCollector
from devwatch.models import CodeIssue, IssueSeverity
from devwatch.config import Config


@pytest.mark.asyncio
async def test_bounded_candidate_collector_incremental_eviction():
    """Verify BoundedCandidateCollector keeps memory strictly bounded under capacity limit."""
    collector = BoundedCandidateCollector(max_capacity=10)

    low_issues = [
        CodeIssue(
            file_path=f"file_{i}.py",
            line_number=1,
            severity=IssueSeverity.LOW,
            category="Quality",
            title=f"Low issue {i}",
            description="Low issue",
            suggestion="Fix",
        )
        for i in range(15)
    ]

    await collector.add_issues(low_issues)
    assert len(collector.get_candidates()) == 10
    assert collector.evicted_count == 5

    critical_issue = CodeIssue(
        file_path="critical.py",
        line_number=1,
        severity=IssueSeverity.CRITICAL,
        category="Security",
        title="Critical vuln",
        description="Critical SQL injection",
        suggestion="Fix immediately",
    )
    await collector.add_issues([critical_issue])
    candidates = collector.get_candidates()

    assert len(candidates) == 10
    assert candidates[0].severity == IssueSeverity.CRITICAL
    assert candidates[0].title == "Critical vuln"
    assert collector.evicted_count == 6


@pytest.mark.asyncio
async def test_synthetic_large_repo_scale_5000_files(tmp_path):
    """Synthetic benchmark testing 5,000+ files for flat memory footprint and high concurrency."""
    repo = tmp_path / "large_repo"
    repo.mkdir()

    file_count = 5050
    for i in range(file_count):
        dir_idx = i // 100
        d = repo / f"dir_{dir_idx}"
        d.mkdir(exist_ok=True)
        (d / f"module_{i}.py").write_text(f"# Python file {i}\ndef func_{i}():\n    return {i}\n", encoding="utf-8")

    pipeline = ReviewPipeline(max_concurrent_files=50)

    mock_sec_issues = [
        CodeIssue(
            file_path="dir_0/module_0.py",
            line_number=2,
            severity=IssueSeverity.HIGH,
            category="Security",
            title="Sample Security Issue",
            description="Sample security vulnerability",
            suggestion="Fix code",
        )
    ]

    tracemalloc.start()
    start_time = time.time()

    with patch.object(pipeline.planner, "execute", new_callable=AsyncMock) as mock_plan, \
         patch.object(pipeline.security_agent, "execute", new_callable=AsyncMock, return_value=mock_sec_issues), \
         patch.object(pipeline.quality_agent, "execute", new_callable=AsyncMock, return_value=[]), \
         patch.object(pipeline.verifier, "execute", new_callable=AsyncMock, side_effect=lambda kwargs: kwargs.get("issues", [])):
        
        from devwatch.models import ReviewScope
        mock_plan.return_value = ReviewScope(
            target_path=str(repo),
            files_to_review=[f"dir_{i//100}/module_{i}.py" for i in range(file_count)],
            focus_areas=["Security"],
        )

        with patch.object(Config, "MAX_FILES_PER_REVIEW", 10000):
            report = await pipeline.execute(str(repo))

    elapsed_time = time.time() - start_time
    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    peak_mem_mb = peak_mem / (1024 * 1024)

    assert report is not None
    assert len(report.issues) <= 1000
    assert peak_mem_mb < 200.0, f"Peak memory usage was too high: {peak_mem_mb:.2f} MB"
    assert elapsed_time < 45.0, f"Review took too long for 5000+ files: {elapsed_time:.2f} seconds"
