import pytest
from unittest.mock import patch
from pydantic import BaseModel
from devwatch.models import (
    CodeIssue,
    IssueSeverity,
    StructuredCodeIssue,
    StructuredSecurityResponse,
    StructuredQualityResponse,
    StructuredPlannerResponse,
)
from devwatch.agents.llm import call_llm_structured
from devwatch.agents.quality import QualityAuditorAgent
from devwatch.agents.security import SecurityAuditorAgent


class DummySchema(BaseModel):
    name: str
    count: int


def test_code_issue_cwe_and_confidence():
    issue = CodeIssue(
        file_path="app.py",
        severity=IssueSeverity.HIGH,
        category="Security",
        title="SQL Injection",
        description="SQL injection in query",
        suggestion="Use params",
        confidence_score=0.95,
        cwe_id="CWE-89",
    )
    assert issue.confidence_score == 0.95
    assert issue.cwe_id == "CWE-89"


def test_call_llm_structured_success():
    mock_response = '{"name": "test_agent", "count": 42}'
    with patch("devwatch.agents.llm.is_llm_available", return_value=True):
        with patch("devwatch.agents.llm.call_llm_completion", return_value=mock_response):
            res = call_llm_structured("prompt", DummySchema)
            assert res is not None
            assert res.name == "test_agent"
            assert res.count == 42


def test_call_llm_structured_self_correction_retry():
    # First response fails validation (count is string not int or missing name)
    invalid_response = '{"name": "test_agent", "count": "not_an_int"}'
    valid_response = '{"name": "test_agent", "count": 100}'

    calls = [invalid_response, valid_response]

    def mock_completion(prompt, system_prompt="", **kwargs):
        return calls.pop(0)

    with patch("devwatch.agents.llm.is_llm_available", return_value=True):
        with patch("devwatch.agents.llm.call_llm_completion", side_effect=mock_completion) as mock_llm:
            res = call_llm_structured("prompt", DummySchema, max_retries=3)
            assert res is not None
            assert res.count == 100
            # Confirm second call received error feedback in prompt
            assert mock_llm.call_count == 2
            second_call_prompt = mock_llm.call_args_list[1][0][0]
            assert "[SYSTEM FEEDBACK:" in second_call_prompt


def test_quality_agent_defers_cwe_to_security():
    agent = QualityAuditorAgent()

    cwe_issue = StructuredCodeIssue(
        line_number=10,
        severity=IssueSeverity.HIGH,
        category="Security",
        title="Command Injection",
        description="OS command injection",
        suggestion="Sanitize",
        cwe_id="CWE-78",
    )
    quality_issue = StructuredCodeIssue(
        line_number=20,
        severity=IssueSeverity.MEDIUM,
        category="Code Quality",
        title="Unclosed File Handle",
        description="File handle not closed",
        suggestion="Use with statement",
        cwe_id=None,
    )
    mock_resp = StructuredQualityResponse(issues=[cwe_issue, quality_issue])

    with patch("devwatch.agents.llm.is_llm_available", return_value=True):
        with patch("devwatch.agents.llm.call_llm_structured", return_value=mock_resp), \
             patch("devwatch.agents.llm.acall_llm_structured", return_value=mock_resp):
            issues = agent.analyze("test.py", "def foo(): pass")
            # Only non-CWE/non-security quality issue should be returned
            titles = [i.title for i in issues]
            assert "Unclosed File Handle" in titles
            assert "Command Injection" not in titles

