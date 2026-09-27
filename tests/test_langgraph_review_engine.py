from langgraph.checkpoint.memory import InMemorySaver
import pytest
import subprocess

from devwatch.models import CodeIssue, IssueSeverity, VerificationStatus
from devwatch.review.engine import ReviewEngine
from devwatch.review.models import ReviewTask, SpecialistRole


pytestmark = pytest.mark.asyncio


class RecordingAgent:
    def __init__(self, output):
        self.output = output
        self.calls = []

    async def execute(self, context):
        self.calls.append(context)
        if callable(self.output):
            return self.output(context)
        return self.output


def _candidate(confidence=None, status=VerificationStatus.ACCEPTED):
    return CodeIssue(
        file_path="app.py",
        line_number=1,
        severity=IssueSeverity.HIGH,
        category="Security",
        title="Unsafe command construction",
        description="User data reaches a process command.",
        suggestion="Pass an argv list.",
        code_snippet="run(user_input)",
        specialist=SpecialistRole.SECURITY.value,
        verification_status=status,
        verification_confidence=confidence,
        source_type="agent",
    )


def _planner_output(_context):
    return [
        ReviewTask(
            task_id="security-app",
            specialist=SpecialistRole.SECURITY,
            files=["app.py"],
            focus="command injection",
        )
    ]


async def _run_engine(verifier_output):
    planner = RecordingAgent(_planner_output)
    security = RecordingAgent([_candidate()])
    unused = {
        SpecialistRole.ARCHITECTURE_API: RecordingAgent([]),
        SpecialistRole.CORRECTNESS: RecordingAgent([]),
        SpecialistRole.PERFORMANCE: RecordingAgent([]),
    }
    verifier = RecordingAgent(verifier_output)
    engine = ReviewEngine(
        planner=planner,
        specialists={SpecialistRole.SECURITY: security, **unused},
        verifier=verifier,
        checkpointer=InMemorySaver(),
    )

    report = await engine.review_files(
        [{"file_path": "app.py", "content": "run(user_input)\n"}]
    )
    return report, planner, security, unused, verifier


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _repository_engine(tmp_path, planner):
    security = RecordingAgent([_candidate()])
    verifier = RecordingAgent(
        lambda context: [
            issue.model_copy(
                update={
                    "verification_status": VerificationStatus.ACCEPTED,
                    "verification_confidence": 0.95,
                }
            )
            for issue in context["issues"]
        ]
    )
    return ReviewEngine(
        planner=planner,
        specialists={
            SpecialistRole.SECURITY: security,
            SpecialistRole.ARCHITECTURE_API: RecordingAgent([]),
            SpecialistRole.CORRECTNESS: RecordingAgent([]),
            SpecialistRole.PERFORMANCE: RecordingAgent([]),
        },
        verifier=verifier,
        checkpointer=InMemorySaver(),
        runs_dir=tmp_path / "runs",
        run_commands=False,
    )


async def test_graph_dispatches_only_planned_specialist_and_reports_verified_finding():
    """Running every reviewer would violate risk routing and the bounded-cost contract."""
    report, planner, security, unused, verifier = await _run_engine(
        lambda context: [
            context["issues"][0].model_copy(
                update={
                    "verification_status": VerificationStatus.ACCEPTED,
                    "verification_confidence": 0.95,
                }
            )
        ]
    )

    assert report.total_issues == 1
    assert "Detailed Verified Findings" in report.summary
    assert len(planner.calls) == 1
    assert len(security.calls) == 1
    assert all(len(agent.calls) == 0 for agent in unused.values())
    assert len(verifier.calls) == 1


async def test_graph_suppresses_llm_finding_without_strict_verification():
    """Provider failure must not turn an unverified LLM opinion into a confirmed bug."""
    report, *_ = await _run_engine(lambda context: context["issues"])

    assert report.total_issues == 0
    assert len(report.manual_review_candidates) == 0
    assert "No confirmed issues" in report.summary


async def test_graph_separates_uncertain_high_risk_candidate_from_confirmed_issues():
    """Uncertain high-impact evidence stays visible without polluting precision metrics."""
    report, *_ = await _run_engine(
        lambda context: [
            context["issues"][0].model_copy(
                update={
                    "verification_status": VerificationStatus.NEEDS_HUMAN_REVIEW,
                    "verification_confidence": 0.7,
                }
            )
        ]
    )

    assert report.total_issues == 0
    assert len(report.manual_review_candidates) == 1
    assert "Manual Review Candidates" in report.summary


async def test_repository_review_returns_empty_report_for_clean_git_tree(tmp_path):
    """A clean repository must not fall back to a costly whole-repository review."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "DevWatch Test")
    (repo / "app.py").write_text("print('clean')\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "baseline")
    planner = RecordingAgent(_planner_output)
    engine = _repository_engine(tmp_path, planner)

    report = await engine.review_repository(str(repo))

    assert report.total_issues == 0
    assert "No reviewable Git changes" in report.summary
    assert planner.calls == []


async def test_repository_review_excludes_blocked_untracked_files(tmp_path):
    """Git discovery must not bypass the scanner's sensitive-file exclusions."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "DevWatch Test")
    (repo / "app.py").write_text("pass\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-qm", "baseline")
    (repo / "secrets.json").write_text('{"token":"private"}', encoding="utf-8")
    planner = RecordingAgent([])
    engine = _repository_engine(tmp_path, planner)

    report = await engine.review_repository(str(repo))

    assert report.total_issues == 0
    assert "No reviewable Git changes" in report.summary
    assert planner.calls == []


async def test_repository_review_passes_only_changed_source_to_planner(tmp_path):
    """Unchanged source must be context at most, never an automatic review target."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "DevWatch Test")
    (repo / "app.py").write_text("run('safe')\n", encoding="utf-8")
    (repo / "unchanged.py").write_text("pass\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "baseline")
    (repo / "app.py").write_text("run(user_input)\n", encoding="utf-8")
    planner = RecordingAgent(_planner_output)
    engine = _repository_engine(tmp_path, planner)

    report = await engine.review_repository(str(repo))

    assert report.total_issues == 1
    assert planner.calls[0]["files"] == ["app.py"]


async def test_engine_persists_graph_checkpoints_to_sqlite(tmp_path):
    """Using in-memory checkpoints in production would lose resumability on restart."""
    checkpoint_path = tmp_path / "state" / "checkpoints.sqlite"
    engine = ReviewEngine(
        planner=RecordingAgent([]),
        specialists={role: RecordingAgent([]) for role in SpecialistRole},
        verifier=RecordingAgent([]),
        checkpoint_path=checkpoint_path,
    )

    await engine.review_file("app.py", "pass\n")

    assert checkpoint_path.is_file()
    assert checkpoint_path.stat().st_size > 0


async def test_sqlite_checkpoint_references_artifacts_without_source_contents(tmp_path):
    """Large or sensitive source text belongs in run artifacts, not checkpoint rows."""
    checkpoint_path = tmp_path / "state" / "checkpoints.sqlite"
    runs_path = tmp_path / "runs"
    marker = "SOURCE_MARKER_THAT_MUST_NOT_ENTER_THE_CHECKPOINT"
    engine = ReviewEngine(
        planner=RecordingAgent([]),
        specialists={role: RecordingAgent([]) for role in SpecialistRole},
        verifier=RecordingAgent([]),
        checkpoint_path=checkpoint_path,
        runs_dir=runs_path,
    )

    await engine.review_file("app.py", f"value = '{marker}'\n")

    assert marker.encode() not in checkpoint_path.read_bytes()
    assert any(marker in path.read_text(encoding="utf-8") for path in runs_path.rglob("app.py"))
