import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from devwatch.config import Config
from devwatch.models import CodeIssue, IssueSeverity, ReviewScope, VerificationStatus
from devwatch.pipeline.context import ReviewContext, ReviewOutcome
from devwatch.pipeline.dag import ReviewPipeline
from devwatch.agents.fake_agent import FakeAgent


@pytest.fixture
def fake_planner(tmp_path):
    return FakeAgent(
        agent_id="planner_agent",
        canned_output=ReviewScope(target_path=str(tmp_path), files_to_review=["main.py"], focus_areas=["General"])
    )


@pytest.mark.asyncio
async def test_empty_repository_handling(tmp_path):
    empty_dir = tmp_path / "empty_repo"
    empty_dir.mkdir()

    pipeline = ReviewPipeline()
    ctx = ReviewContext(target_path=str(empty_dir))
    report = await pipeline.execute(str(empty_dir), context=ctx)

    assert report is not None
    assert report.total_issues == 0
    assert ctx.status == ReviewOutcome.COMPLETED
    assert "Empty repository" in report.summary


@pytest.mark.asyncio
async def test_security_agent_failure_quality_findings_survive(tmp_path):
    (tmp_path / "main.py").write_text("import sys\nprint('test')")

    planner = FakeAgent(
        agent_id="planner_agent",
        canned_output=ReviewScope(target_path=str(tmp_path), files_to_review=["main.py"], focus_areas=["General"])
    )
    failing_sec = FakeAgent(agent_id="security_auditor")
    failing_sec.execute = AsyncMock(side_effect=RuntimeError("Security Agent Crashed"))

    quality_issue = CodeIssue(
        file_path="main.py",
        line_number=1,
        severity=IssueSeverity.MEDIUM,
        category="Code Quality",
        title="Quality Bug",
        description="Quality description",
        suggestion="Clean up print statement",
    )
    working_qual = FakeAgent(agent_id="quality_auditor", canned_output=[quality_issue])

    fake_verifier = FakeAgent(agent_id="verifier_agent")
    fake_verifier.execute = AsyncMock(
        side_effect=lambda context: [
            issue.model_copy(
                update={
                    "verification_status": VerificationStatus.ACCEPTED,
                    "verification_confidence": 0.95,
                }
            )
            for issue in context["issues"]
        ]
    )

    pipeline = ReviewPipeline(
        planner=planner,
        security_agent=failing_sec,
        quality_agent=working_qual,
        verifier=fake_verifier,
    )


    ctx = ReviewContext(target_path=str(tmp_path))
    report = await pipeline.execute(str(tmp_path), context=ctx)

    assert report is not None
    assert ctx.status == ReviewOutcome.PARTIALLY_COMPLETED
    assert len(ctx.stage_failures) >= 1
    assert any(f["stage"] == "SECURITY_ANALYSIS" for f in ctx.stage_failures)
    assert any(i.title == "Quality Bug" for i in report.issues)


@pytest.mark.asyncio
async def test_quality_agent_failure_security_findings_survive(tmp_path):
    (tmp_path / "auth.py").write_text("secret = '12345'")

    planner = FakeAgent(
        agent_id="planner_agent",
        canned_output=ReviewScope(target_path=str(tmp_path), files_to_review=["auth.py"], focus_areas=["General"])
    )
    failing_qual = FakeAgent(agent_id="quality_auditor")
    failing_qual.execute = AsyncMock(side_effect=RuntimeError("Quality Agent Crashed"))

    sec_issue = CodeIssue(
        file_path="auth.py",
        line_number=1,
        severity=IssueSeverity.CRITICAL,
        category="Security",
        title="Hardcoded Secret",
        description="Plaintext secret found",
        suggestion="Remove hardcoded secret",
    )
    working_sec = FakeAgent(agent_id="security_auditor", canned_output=[sec_issue])

    fake_verifier = FakeAgent(agent_id="verifier_agent")
    fake_verifier.execute = AsyncMock(
        side_effect=lambda context: [
            issue.model_copy(
                update={
                    "verification_status": VerificationStatus.ACCEPTED,
                    "verification_confidence": 0.95,
                }
            )
            for issue in context["issues"]
        ]
    )

    pipeline = ReviewPipeline(
        planner=planner,
        security_agent=working_sec,
        quality_agent=failing_qual,
        verifier=fake_verifier,
    )


    ctx = ReviewContext(target_path=str(tmp_path))
    report = await pipeline.execute(str(tmp_path), context=ctx)

    assert report is not None
    assert ctx.status == ReviewOutcome.PARTIALLY_COMPLETED
    assert len(ctx.stage_failures) >= 1
    assert any(f["stage"] == "QUALITY_ANALYSIS" for f in ctx.stage_failures)
    assert any(i.title == "Hardcoded Secret" for i in report.issues)


@pytest.mark.asyncio
async def test_verifier_failure_suppresses_llm_only_candidates(tmp_path):
    (tmp_path / "server.py").write_text("x = 1")

    planner = FakeAgent(
        agent_id="planner_agent",
        canned_output=ReviewScope(target_path=str(tmp_path), files_to_review=["server.py"], focus_areas=["General"])
    )
    candidate_issue = CodeIssue(
        file_path="server.py",
        line_number=1,
        severity=IssueSeverity.HIGH,
        category="Security",
        title="Candidate Vulnerability",
        description="Candidate vulnerability description",
        suggestion="Sanitize input",
    )
    working_sec = FakeAgent(agent_id="security_auditor", canned_output=[candidate_issue])
    working_qual = FakeAgent(agent_id="quality_auditor", canned_output=[])

    failing_verifier = FakeAgent(agent_id="verifier_agent")
    failing_verifier.execute = AsyncMock(side_effect=RuntimeError("Verifier Crashed"))

    pipeline = ReviewPipeline(
        planner=planner,
        security_agent=working_sec,
        quality_agent=working_qual,
        verifier=failing_verifier,
    )

    ctx = ReviewContext(target_path=str(tmp_path))
    report = await pipeline.execute(str(tmp_path), context=ctx)

    assert report is not None
    assert ctx.status == ReviewOutcome.PARTIALLY_COMPLETED
    assert not any(i.title == "Candidate Vulnerability" for i in report.issues)
    assert report.metrics["suppressed_findings"] >= 1


@pytest.mark.asyncio
async def test_legacy_synthesizer_is_not_called_by_deterministic_renderer(tmp_path):
    (tmp_path / "app.py").write_text("x = 1")

    planner = FakeAgent(
        agent_id="planner_agent",
        canned_output=ReviewScope(target_path=str(tmp_path), files_to_review=["app.py"], focus_areas=["General"])
    )
    failing_synth = FakeAgent(agent_id="report_synthesizer")
    failing_synth.execute = AsyncMock(side_effect=RuntimeError("Synthesizer Crashed"))

    pipeline = ReviewPipeline(planner=planner, synthesizer=failing_synth)

    ctx = ReviewContext(target_path=str(tmp_path))
    report = await pipeline.execute(str(tmp_path), context=ctx)

    assert report is not None
    assert ctx.status == ReviewOutcome.COMPLETED
    assert "DevWatch Code Review Report" in report.summary
    failing_synth.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancellation_between_stages(tmp_path):
    (tmp_path / "file1.py").write_text("x = 1")

    pipeline = ReviewPipeline()
    ctx = ReviewContext(target_path=str(tmp_path))
    ctx.cancellation_requested = True

    with pytest.raises(asyncio.CancelledError):
        await pipeline.execute(str(tmp_path), context=ctx)

    assert ctx.status == ReviewOutcome.CANCELLED


@pytest.mark.asyncio
async def test_global_deadline_exceeded(tmp_path):
    (tmp_path / "test.py").write_text("x = 1")

    pipeline = ReviewPipeline()
    ctx = ReviewContext(target_path=str(tmp_path))

    with patch.object(Config, "GLOBAL_REVIEW_TIMEOUT_SECONDS", 0.001):
        with pytest.raises(TimeoutError):
            await pipeline.execute(str(tmp_path), context=ctx)

    assert ctx.status == ReviewOutcome.FAILED
