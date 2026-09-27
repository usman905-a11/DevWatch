from devwatch.models import CodeIssue, IssueSeverity
from devwatch.review.models import (
    ChangedRegion,
    ReviewTask,
    SpecialistRole,
    ToolEvidence,
)


def test_review_task_rejects_empty_file_assignment():
    """A planner bug that emits no files must not schedule an LLM worker."""
    try:
        ReviewTask(
            task_id="task-1",
            specialist=SpecialistRole.SECURITY,
            files=[],
            focus="authentication",
        )
    except ValueError as error:
        assert "files" in str(error)
    else:
        raise AssertionError("empty planner assignments must be rejected")


def test_finding_contract_is_backward_compatible_and_carries_evidence():
    """Existing CodeIssue callers keep working while graph findings add proof."""
    old_style = CodeIssue(
        file_path="app.py",
        line_number=3,
        severity=IssueSeverity.HIGH,
        category="Security",
        title="Unsafe call",
        description="User input reaches a shell.",
        suggestion="Use an argv-based process call.",
    )
    assert old_style.evidence == []
    assert old_style.specialist is None
    assert old_style.verification_confidence is None

    evidence = ToolEvidence(
        source="pytest",
        summary="test_shell_input failed",
        command=["python", "-m", "pytest", "-q"],
        exit_code=1,
    )
    region = ChangedRegion(file_path="app.py", start_line=2, end_line=4)
    task = ReviewTask(
        task_id="task-2",
        specialist=SpecialistRole.SECURITY,
        files=["app.py"],
        focus="command injection",
        changed_regions=[region],
        evidence=[evidence],
    )
    assert task.specialist == SpecialistRole.SECURITY
    assert task.changed_regions[0].start_line == 2
