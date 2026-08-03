import pytest
from devwatch.models import (
    CodeIssue,
    IssueSeverity,
    ReviewReport,
    ReviewScope,
    AgentStepUpdate,
)

def test_code_issue_creation():
    issue = CodeIssue(
        file_path="src/auth.py",
        line_number=42,
        severity=IssueSeverity.HIGH,
        category="Security",
        title="Hardcoded Secret Key",
        description="JWT secret key is hardcoded in source.",
        suggestion="Move secret to environment variable.",
        code_snippet="SECRET_KEY = 'sk_live_123'"
    )
    assert issue.file_path == "src/auth.py"
    assert issue.line_number == 42
    assert issue.severity == IssueSeverity.HIGH
    assert issue.category == "Security"
    assert issue.title == "Hardcoded Secret Key"

def test_review_scope_creation():
    scope = ReviewScope(
        target_path="e:/dewatch/src",
        files_to_review=["auth.py", "db.py"],
        focus_areas=["Security", "Exceptions"]
    )
    assert scope.target_path == "e:/dewatch/src"
    assert len(scope.files_to_review) == 2
    assert "Security" in scope.focus_areas

def test_review_report_summary_counts():
    issue1 = CodeIssue(
        file_path="a.py",
        line_number=1,
        severity=IssueSeverity.CRITICAL,
        category="Security",
        title="SQL Injection",
        description="Raw SQL execute",
        suggestion="Use ORM"
    )
    issue2 = CodeIssue(
        file_path="b.py",
        line_number=5,
        severity=IssueSeverity.HIGH,
        category="Security",
        title="Hardcoded Credential",
        description="API Key",
        suggestion="Use env var"
    )
    issue3 = CodeIssue(
        file_path="c.py",
        line_number=12,
        severity=IssueSeverity.MEDIUM,
        category="Code Quality",
        title="Bare Except",
        description="Catching all exceptions",
        suggestion="Catch specific exception"
    )
    issue4 = CodeIssue(
        file_path="d.py",
        line_number=20,
        severity=IssueSeverity.LOW,
        category="Code Quality",
        title="Print Statement",
        description="Leftover print",
        suggestion="Use logger"
    )
    report = ReviewReport(
        target_path=".",
        issues=[issue1, issue2, issue3, issue4],
        summary="Found 4 issues"
    )
    assert report.total_issues == 4
    assert report.critical_count == 1
    assert report.high_count == 1
    assert report.medium_count == 1
    assert report.low_count == 1

def test_agent_step_update():
    update = AgentStepUpdate(
        agent_name="Security Auditor",
        status="RUNNING",
        message="Scanning src/auth.py for OWASP vulnerabilities"
    )
    assert update.agent_name == "Security Auditor"
    assert update.status == "RUNNING"
    assert "auth.py" in update.message
