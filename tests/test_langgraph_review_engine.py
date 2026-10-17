from langgraph.checkpoint.memory import InMemorySaver
import asyncio
import pytest
import subprocess

from devwatch.config import Config
from devwatch.models import CodeIssue, IssueSeverity, VerificationStatus, generate_evidence_fingerprint
from devwatch.review.engine import ReviewEngine
from devwatch.review.models import ReviewTask, SpecialistRole
from devwatch.review.models import ChangedRegion, ToolEvidence
from devwatch.agents import llm
from devwatch.providers.fake_provider import FakeLLMProvider


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


async def test_planner_assignments_are_bounded_to_changed_files_and_roles(tmp_path):
    """Planner output cannot schedule context files or duplicate LLM role calls."""
    planner = RecordingAgent(
        [
            ReviewTask(task_id="a", specialist=SpecialistRole.SECURITY,
                       files=["app.py", "outside.py"], focus="security"),
            ReviewTask(task_id="b", specialist=SpecialistRole.SECURITY,
                       files=["app.py"], focus="security"),
            ReviewTask(task_id="c", specialist=SpecialistRole.CORRECTNESS,
                       files=["outside.py"], focus="correctness"),
        ]
    )
    security = RecordingAgent([])
    correctness = RecordingAgent([])
    engine = ReviewEngine(
        planner=planner,
        specialists={SpecialistRole.SECURITY: security,
                     SpecialistRole.CORRECTNESS: correctness},
        verifier=RecordingAgent([]),
        runs_dir=tmp_path / "runs",
    )

    report = await engine.review_file("app.py", "pass\n")

    assert report.metrics["specialist_tasks"] == 1
    assert len(security.calls) == 1
    assert security.calls[0]["task"].files == ["app.py"]
    assert correctness.calls == []


async def test_specialist_fanout_respects_configured_concurrency(tmp_path, monkeypatch):
    """A graph fan-out must not exceed the configured live LLM call budget."""
    monkeypatch.setattr(Config, "MAX_CONCURRENT_LLM_CALLS", 1)
    active = 0
    peak = 0

    class ConcurrentAgent:
        async def execute(self, context):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1
            return []

    tasks = [
        ReviewTask(task_id=role.value, specialist=role, files=["app.py"], focus="review")
        for role in (SpecialistRole.SECURITY, SpecialistRole.CORRECTNESS)
    ]
    engine = ReviewEngine(
        planner=RecordingAgent(tasks),
        specialists={role: ConcurrentAgent() for role in SpecialistRole},
        verifier=RecordingAgent([]),
        runs_dir=tmp_path / "runs",
    )

    await engine.review_file("app.py", "pass\n")

    assert peak == 1


async def test_specialist_output_is_capped_before_parallel_merge(tmp_path, monkeypatch):
    """A verbose specialist cannot overfill the reducer state."""
    monkeypatch.setattr(Config, "MAX_CANDIDATE_FINDINGS", 2)
    issues = [
        _candidate().model_copy(update={"title": f"Issue {index}", "rule_id": f"rule-{index}"})
        for index in range(3)
    ]
    engine = ReviewEngine(
        planner=RecordingAgent(_planner_output),
        specialists={SpecialistRole.SECURITY: RecordingAgent(issues)},
        verifier=RecordingAgent([]),
        runs_dir=tmp_path / "runs",
    )

    report = await engine.review_file("app.py", "run(user_input)\n")

    assert report.metrics["candidate_findings"] == 2


async def test_parallel_candidate_merge_has_stable_tie_breaker(tmp_path):
    """Equivalent candidates must not change the chosen report text by arrival order."""
    engine = ReviewEngine(
        planner=RecordingAgent([]), specialists={}, verifier=RecordingAgent([]),
        runs_dir=tmp_path / "runs",
    )
    first = _candidate().model_copy(update={"title": "Alpha", "specialist": "security"})
    second = _candidate().model_copy(update={"title": "Zulu", "specialist": "correctness"})

    forward = engine._deduplicate({"candidate_findings": [first, second]})
    reverse = engine._deduplicate({"candidate_findings": [second, first]})

    assert [issue.title for issue in forward["deduped_findings"]] == [
        issue.title for issue in reverse["deduped_findings"]
    ]


async def test_graph_suppresses_llm_finding_without_strict_verification():
    """Provider failure must not turn an unverified LLM opinion into a confirmed bug."""
    report, *_ = await _run_engine(lambda context: context["issues"])

    assert report.total_issues == 0
    assert len(report.manual_review_candidates) == 0
    assert "No confirmed issues" in report.summary


@pytest.mark.parametrize("bad_issue", [
    {"line_number": 2, "start_line": 2, "end_line": 2},
    {"code_snippet": "different_source()"},
    {"evidence_fingerprint": "bad-hash"},
    {"verification_confidence": 0.79},
])
async def test_strict_gate_rejects_invalid_or_weak_evidence(bad_issue):
    issue = _candidate().model_copy(update={
        **{key: value for key, value in bad_issue.items() if key != "verification_confidence"}
    })
    engine = ReviewEngine(
        planner=RecordingAgent(_planner_output),
        specialists={SpecialistRole.SECURITY: RecordingAgent([issue])},
        verifier=RecordingAgent(lambda context: [context["issues"][0].model_copy(update={
            "verification_confidence": bad_issue.get("verification_confidence", 0.95),
        })]),
    )
    report = await engine.review_file("app.py", "run(user_input)\n")
    assert report.total_issues == 0


async def test_specialist_cannot_claim_static_tool_trust(tmp_path):
    forged = _candidate().model_copy(update={
        "source_type": "static",
        "evidence": [{"source": "ASTStaticAnalyzerTool", "conclusive": True}],
        "verification_confidence": 1.0,
    })
    engine = ReviewEngine(
        planner=RecordingAgent(_planner_output),
        specialists={SpecialistRole.SECURITY: RecordingAgent([forged])},
        verifier=RecordingAgent([]), runs_dir=tmp_path / "runs",
    )
    report = await engine.review_file("app.py", "run(user_input)\n")
    assert report.total_issues == 0


async def test_verifier_failure_keeps_other_file_results_and_marks_partial(tmp_path):
    tasks = [ReviewTask(task_id="two", specialist=SpecialistRole.SECURITY,
                        files=["a.py", "b.py"], focus="review")]
    issues = [
        _candidate().model_copy(update={"file_path": path, "finding_id": path})
        for path in ("a.py", "b.py")
    ]
    async def verify(context):
        if context["file_path"] == "b.py":
            raise RuntimeError("verifier unavailable")
        return [issue.model_copy(update={"verification_confidence": 0.95})
                for issue in context["issues"]]
    class Verifier:
        async def execute(self, context):
            return await verify(context)
    engine = ReviewEngine(
        planner=RecordingAgent(tasks),
        specialists={SpecialistRole.SECURITY: RecordingAgent(issues)},
        verifier=Verifier(), runs_dir=tmp_path / "runs",
    )
    report = await engine.review_files([
        {"file_path": "a.py", "content": "run(user_input)\n"},
        {"file_path": "b.py", "content": "run(user_input)\n"},
    ])
    assert [issue.file_path for issue in report.issues] == ["a.py"]
    assert report.metrics["partial"] is True
    assert report.metrics["stage_failures"][0]["stage"] == "VERIFICATION"


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


async def test_resume_job_uses_completed_checkpoint_stages(tmp_path):
    checkpoint_path = tmp_path / "checkpoints.sqlite"
    runs_dir = tmp_path / "runs"
    planner = RecordingAgent(_planner_output)
    specialist = RecordingAgent([_candidate()])
    verifier = RecordingAgent(lambda context: [
        issue.model_copy(update={"verification_confidence": 0.95})
        for issue in context["issues"]
    ])
    engine = ReviewEngine(
        planner=planner, specialists={SpecialistRole.SECURITY: specialist},
        verifier=verifier, checkpoint_path=checkpoint_path, runs_dir=runs_dir,
    )
    original = engine.deduplicator._run
    def fail_once(_candidates):
        engine.deduplicator._run = original
        raise RuntimeError("interrupted after specialists")
    engine.deduplicator._run = fail_once

    with pytest.raises(RuntimeError, match="interrupted after specialists"):
        await engine.review_file("app.py", "run(user_input)\n", job_id="resume_case")

    restarted = ReviewEngine(
        planner=planner, specialists={SpecialistRole.SECURITY: specialist},
        verifier=verifier, checkpoint_path=checkpoint_path, runs_dir=runs_dir,
    )
    report = await restarted.resume_job("resume_case")
    assert report.total_issues == 1
    assert len(planner.calls) == 1
    assert len(specialist.calls) == 1


async def test_progress_stream_includes_nodes_tools_usage_and_suppression(tmp_path):
    class TokenAgent:
        async def execute(self, context):
            await llm.acall_llm_completion("one two", provider=FakeLLMProvider(default_content="done"))
            return []
    updates = []
    engine = ReviewEngine(
        planner=RecordingAgent(_planner_output),
        specialists={SpecialistRole.SECURITY: TokenAgent()},
        verifier=RecordingAgent([]), runs_dir=tmp_path / "runs",
    )
    snapshot = engine.snapshotter.create_from_files({"app.py": "pass\n"}, "progress_case")
    report = await engine._invoke(
        job_id="progress_case", target_path="app.py",
        artifact_path=snapshot.artifact_path, artifact_files=snapshot.files,
        artifact_hashes=snapshot.content_hashes,
        changed_regions=[ChangedRegion(file_path="app.py", start_line=1, end_line=1)],
        tool_evidence=[ToolEvidence(source="pytest", summary="one check passed", exit_code=0)],
        progress_sink=updates.append,
    )
    assert report.total_issues == 0
    assert any(update.agent_name == "plan_review" and update.tool_results for update in updates)
    assert any(update.specialist == "security" and update.token_usage.get("total_tokens", 0) > 0 for update in updates)
    assert any(update.agent_name == "render_report" for update in updates)
    assert any(update.suppressed_finding_count == 0 for update in updates)
    assert all(update.elapsed_ms is not None for update in updates)


async def test_cancellation_closes_specialist_and_allows_resume(tmp_path):
    ready = asyncio.Event()
    closed = asyncio.Event()
    class BlockingAgent:
        async def execute(self, context):
            ready.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()
    checkpoint_path = tmp_path / "checkpoints.sqlite"
    runs_dir = tmp_path / "runs"
    engine = ReviewEngine(
        planner=RecordingAgent(_planner_output),
        specialists={SpecialistRole.SECURITY: BlockingAgent()},
        verifier=RecordingAgent([]), checkpoint_path=checkpoint_path, runs_dir=runs_dir,
    )
    task = asyncio.create_task(engine.review_file("app.py", "pass\n", job_id="cancel_case"))
    await asyncio.wait_for(ready.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()
    resumed = ReviewEngine(
        planner=engine.planner,
        specialists={SpecialistRole.SECURITY: RecordingAgent([])},
        verifier=RecordingAgent([]), checkpoint_path=checkpoint_path, runs_dir=runs_dir,
    )
    report = await resumed.resume_job("cancel_case")
    assert report.total_issues == 0
    assert len(engine.planner.calls) == 1


async def test_static_evidence_survives_planner_failure(tmp_path):
    class FailingPlanner:
        async def execute(self, context):
            raise RuntimeError("planner unavailable")
    engine = ReviewEngine(
        planner=FailingPlanner(), specialists={}, verifier=RecordingAgent([]),
        runs_dir=tmp_path / "runs",
    )
    report = await engine.review_file("app.py", "eval('1 + 1')\n")
    assert [issue.title for issue in report.issues] == ["Dynamic Code Execution via eval()"]
    assert report.metrics["partial"] is True


async def test_verifier_failure_retains_conclusive_static_finding(tmp_path):
    class FailingVerifier:
        async def execute(self, context):
            raise RuntimeError("verifier unavailable")
    candidate = _candidate().model_copy(update={"line_number": 2, "start_line": 2, "end_line": 2})
    engine = ReviewEngine(
        planner=RecordingAgent(_planner_output),
        specialists={SpecialistRole.SECURITY: RecordingAgent([candidate])},
        verifier=FailingVerifier(), runs_dir=tmp_path / "runs",
    )
    report = await engine.review_file("app.py", "eval('1 + 1')\nrun(user_input)\n")
    assert [issue.title for issue in report.issues] == ["Dynamic Code Execution via eval()"]
    assert report.metrics["partial"] is True


async def test_verifier_cannot_rewrite_candidate_source(tmp_path):
    def altered(context):
        return [context["issues"][0].model_copy(update={
            "code_snippet": "forged()",
            "file_path": "other.py",
            "verification_confidence": 0.95,
        })]
    engine = ReviewEngine(
        planner=RecordingAgent(_planner_output),
        specialists={SpecialistRole.SECURITY: RecordingAgent([_candidate()])},
        verifier=RecordingAgent(altered), runs_dir=tmp_path / "runs",
    )
    report = await engine.review_file("app.py", "run(user_input)\n")
    assert [(issue.file_path, issue.code_snippet) for issue in report.issues] == [
        ("app.py", None)
    ]


async def test_candidate_budget_retains_critical_findings(monkeypatch):
    from devwatch.review.state import merge_candidates
    monkeypatch.setattr(Config, "MAX_CANDIDATE_FINDINGS", 1)
    low = _candidate().model_copy(update={"severity": IssueSeverity.LOW})
    critical = _candidate().model_copy(update={"severity": IssueSeverity.CRITICAL})
    assert merge_candidates([low], [critical])[0].severity == IssueSeverity.CRITICAL


async def test_checkpoint_omits_candidate_source_snippets(tmp_path):
    marker = "PRIVATE_SOURCE_MARKER_7Y9"
    source_line = f"run({marker})"
    candidate = _candidate().model_copy(update={
        "code_snippet": source_line,
        "evidence_fingerprint": generate_evidence_fingerprint(source_line),
    })
    checkpoint_path = tmp_path / "checkpoints.sqlite"
    engine = ReviewEngine(
        planner=RecordingAgent(_planner_output),
        specialists={SpecialistRole.SECURITY: RecordingAgent([candidate])},
        verifier=RecordingAgent(lambda context: [
            issue.model_copy(update={"verification_confidence": 0.95})
            for issue in context["issues"]
        ]),
        checkpoint_path=checkpoint_path, runs_dir=tmp_path / "runs",
    )
    report = await engine.review_file("app.py", source_line + "\n")
    assert report.total_issues == 1
    assert marker.encode() not in checkpoint_path.read_bytes()
