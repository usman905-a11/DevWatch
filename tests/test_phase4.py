import pytest
from unittest.mock import patch
from devwatch.models import CodeIssue, IssueSeverity, StructuredVerificationResponse, VerificationItem
from devwatch.agents.verifier import VerificationAgent
from devwatch.tools import IssueDeduplicatorTool
from devwatch.pipeline.dag import ReviewPipeline


def test_verification_agent_filtering():
    verifier = VerificationAgent()
    sample_issues = [
        CodeIssue(
            file_path="app.py",
            line_number=10,
            severity=IssueSeverity.HIGH,
            category="Security",
            title="Real SQL Injection",
            description="String formatting in SQL",
            suggestion="Fix it",
        ),
        CodeIssue(
            file_path="app.py",
            line_number=20,
            severity=IssueSeverity.LOW,
            category="Code Quality",
            title="False Alarm Defect",
            description="Imaginary issue",
            suggestion="N/A",
        ),
    ]

    mock_resp = StructuredVerificationResponse(
        verifications=[
            VerificationItem(issue_title="Real SQL Injection", is_true_positive=True, confidence=1.0),
            VerificationItem(issue_title="False Alarm Defect", is_true_positive=False, confidence=0.9),
        ]
    )

    with patch("devwatch.agents.llm.is_llm_available", return_value=True):
        with patch("devwatch.agents.llm.acall_llm_structured", return_value=mock_resp):
            verified = verifier.verify_issues("app.py", "some code", sample_issues)
            assert len(verified) == 1
            assert verified[0].title == "Real SQL Injection"


def test_line_range_proximity_deduplication():
    dedup = IssueDeduplicatorTool()
    issues = [
        CodeIssue(
            file_path="service.py",
            line_number=15,
            severity=IssueSeverity.HIGH,
            category="Security",
            title="SQL Injection",
            description="First issue at line 15",
            suggestion="Fix",
            cwe_id="CWE-89",
        ),
        CodeIssue(
            file_path="service.py",
            line_number=17,  # Within +/- 3 lines
            severity=IssueSeverity.CRITICAL,  # Higher severity
            category="Security",
            title="SQL Injection",
            description="Nearby issue at line 17",
            suggestion="Fix",
            cwe_id="CWE-89",
        ),
        CodeIssue(
            file_path="service.py",
            line_number=50,  # Far away line
            severity=IssueSeverity.HIGH,
            category="Security",
            title="SQL Injection",
            description="Distant issue at line 50",
            suggestion="Fix",
            cwe_id="CWE-89",
        ),
    ]

    deduped = dedup._run(issues)
    assert len(deduped) == 2
    # Should have retained the CRITICAL severity for the line 15-17 group
    severities = [i.severity for i in deduped]
    assert IssueSeverity.CRITICAL in severities


@pytest.mark.asyncio
async def test_engine_includes_verifier_agent():
    updates = []

    def callback(update):
        updates.append(update.agent_name)

    pipeline = ReviewPipeline(step_callback=callback)
    report = await pipeline.arun_file_audit("test.py", "x = 1")
    assert "Verification Agent" in updates
    assert report is not None
