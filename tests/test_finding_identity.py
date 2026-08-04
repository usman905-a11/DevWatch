import pytest
from unittest.mock import AsyncMock, patch
from devwatch.models import (
    CodeIssue,
    IssueSeverity,
    VerificationStatus,
    VerificationItem,
    StructuredVerificationResponse,
    generate_evidence_fingerprint,
    generate_finding_id,
)
from devwatch.tools import IssueDeduplicatorTool
from devwatch.agents.verifier import VerificationAgent
from devwatch.agents.fake_agent import FakeAgent


def test_stable_finding_id_generation():
    snippet = "   10 | query = f'SELECT * FROM users WHERE id={user_id}'"
    fp1 = generate_evidence_fingerprint(snippet)

    # Line number shifted from 10 to 125
    shifted_snippet = "  125 | query = f'SELECT * FROM users WHERE id={user_id}'"
    fp2 = generate_evidence_fingerprint(shifted_snippet)

    assert fp1 == fp2

    fid1 = generate_finding_id("app/db.py", "CWE-89", fp1)
    fid2 = generate_finding_id("app/db.py", "CWE-89", fp2)

    assert fid1 == fid2


def test_same_issue_from_two_agents_merged():
    issue1 = CodeIssue(
        file_path="server.py",
        line_number=10,
        severity=IssueSeverity.HIGH,
        category="Security",
        rule_id="CWE-89",
        title="SQL Injection",
        description="Raw query concatenation",
        suggestion="Use ORM parameters",
        code_snippet="query = f'SELECT * FROM users'",
        source_type="security_auditor",
    )

    issue2 = CodeIssue(
        file_path="server.py",
        line_number=12,
        severity=IssueSeverity.HIGH,
        category="Security",
        rule_id="CWE-89",
        title="SQL Injection in Server",
        description="Raw query concatenation in DB call",
        suggestion="Use ORM parameters",
        code_snippet="query = f'SELECT * FROM users'",
        source_type="ast_analyzer",
    )

    dedup = IssueDeduplicatorTool()
    unique = dedup._run([issue1, issue2])

    assert len(unique) == 1
    assert "security_auditor" in unique[0].metadata["sources"]
    assert "ast_analyzer" in unique[0].metadata["sources"]


def test_distinct_issues_near_each_other_preserved():
    # Line 10: SQL Injection vs Line 11: Command Injection
    sqli = CodeIssue(
        file_path="app.py",
        line_number=10,
        severity=IssueSeverity.HIGH,
        category="Security",
        rule_id="CWE-89",
        title="SQL Injection",
        description="Unsanitized query",
        suggestion="Use params",
        code_snippet="db.execute(f'SELECT {user_input}')",
    )

    cmdi = CodeIssue(
        file_path="app.py",
        line_number=11,
        severity=IssueSeverity.CRITICAL,
        category="Security",
        rule_id="CWE-78",
        title="Command Injection",
        description="Shell execution",
        suggestion="Use subprocess list",
        code_snippet="os.system(cmd)",
    )

    dedup = IssueDeduplicatorTool()
    unique = dedup._run([sqli, cmdi])

    assert len(unique) == 2


def test_different_cwe_on_same_line_preserved():
    sqli = CodeIssue(
        file_path="api.py",
        line_number=15,
        severity=IssueSeverity.HIGH,
        category="Security",
        rule_id="CWE-89",
        cwe_id="CWE-89",
        title="SQL Injection",
        description="Query concatenation",
        suggestion="Fix SQL",
        code_snippet="query_user(input)",
    )

    xss = CodeIssue(
        file_path="api.py",
        line_number=15,
        severity=IssueSeverity.MEDIUM,
        category="Security",
        rule_id="CWE-79",
        cwe_id="CWE-79",
        title="Cross-Site Scripting",
        description="Unescaped output",
        suggestion="Escape HTML",
        code_snippet="query_user(input)",
    )

    dedup = IssueDeduplicatorTool()
    unique = dedup._run([sqli, xss])

    assert len(unique) == 2


def test_similar_titles_different_locations_preserved():
    issue1 = CodeIssue(
        file_path="module1.py",
        line_number=5,
        severity=IssueSeverity.MEDIUM,
        category="Quality",
        title="Bare Except Clause",
        description="Bare except",
        suggestion="Fix except",
        code_snippet="except:",
    )

    issue2 = CodeIssue(
        file_path="module2.py",
        line_number=5,
        severity=IssueSeverity.MEDIUM,
        category="Quality",
        title="Bare Except Clause",
        description="Bare except",
        suggestion="Fix except",
        code_snippet="except:",
    )

    dedup = IssueDeduplicatorTool()
    unique = dedup._run([issue1, issue2])

    assert len(unique) == 2


def test_shifted_line_numbers_same_evidence_deduplicated():
    issue1 = CodeIssue(
        file_path="views.py",
        line_number=10,
        severity=IssueSeverity.HIGH,
        category="Security",
        rule_id="CWE-89",
        title="SQL Injection",
        description="Query building",
        suggestion="Fix SQL",
        code_snippet="execute_sql(raw_string)",
    )

    issue2 = CodeIssue(
        file_path="views.py",
        line_number=45,
        severity=IssueSeverity.HIGH,
        category="Security",
        rule_id="CWE-89",
        title="SQL Injection",
        description="Query building",
        suggestion="Fix SQL",
        code_snippet="execute_sql(raw_string)",
    )

    dedup = IssueDeduplicatorTool()
    unique = dedup._run([issue1, issue2])

    assert len(unique) == 1


@pytest.mark.asyncio
async def test_uncertain_critical_issue_escalated_to_needs_human_review():
    critical_issue = CodeIssue(
        file_path="auth.py",
        line_number=20,
        severity=IssueSeverity.CRITICAL,
        category="Security",
        rule_id="CWE-287",
        title="Authentication Bypass Potential",
        description="Complex JWT check condition",
        suggestion="Verify signature",
        code_snippet="if token.valid:",
    )
    critical_issue.ensure_identity()

    verifier = VerificationAgent()

    canned_v_item = VerificationItem(
        finding_id=critical_issue.finding_id,
        status=VerificationStatus.UNCERTAIN,
        confidence=0.4,
        reasoning="Data flow into JWT validator is ambiguous.",
    )
    mock_resp = StructuredVerificationResponse(verifications=[canned_v_item])

    with patch("devwatch.agents.verifier.llm.is_llm_available", return_value=True):
        with patch("devwatch.agents.verifier.llm.acall_llm_structured", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_resp

            verified = await verifier.execute({
                "file_path": "auth.py",
                "code_content": "if token.valid:",
                "issues": [critical_issue],
            })

            assert len(verified) == 1
            assert verified[0].verification_status == VerificationStatus.NEEDS_HUMAN_REVIEW
            assert "JWT validator" in verified[0].verification_rationale
