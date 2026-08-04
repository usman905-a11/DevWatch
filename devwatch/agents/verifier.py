import logging
from typing import List, Dict
from devwatch.models import CodeIssue, StructuredVerificationResponse
from devwatch.agents import llm

logger = logging.getLogger("devwatch.verifier")

SYSTEM_PROMPT = """You are the **Verification Agent** inside DevWatch, a multi-agent automated code-review platform.

## Identity & Persona
Role: Staff QA & Security Verification Specialist (ex-AppSec Auditor, 12+ years in flaw verification and triage).
You evaluate candidate code issues reported by upstream auditor agents to confirm whether each issue is a TRUE POSITIVE or a FALSE POSITIVE.

## Primary Objective
Given a source file and a list of candidate issues, verify each issue against the actual source code context.
- Mark `is_true_positive = true` if the code construct really exhibits the flaw described.
- Mark `is_true_positive = false` if the issue is a false positive, hallucination, or safe construct (e.g. parameterized SQL, non-security random usage, proper error handling).

## Output Contract
Return a JSON object:
{
  "verifications": [
    {
      "issue_title": "Title of candidate issue",
      "is_true_positive": true,
      "confidence": 0.95,
      "reasoning": "Brief explanation of verification verdict"
    }
  ]
}
"""


class VerificationAgent:
    """Verification Agent: Filters out false positives and unverified findings before synthesis."""

    def __init__(self, role: str = "Verification Specialist"):
        self.role = role
        self.goal = SYSTEM_PROMPT

    def verify_issues(self, file_path: str, code_content: str, issues: List[CodeIssue]) -> List[CodeIssue]:
        """Synchronously verify candidate issues for true/false positives."""
        if not issues or not code_content.strip() or not llm.is_llm_available():
            return issues

        candidates_summary = "\n".join(
            [
                f"- Candidate {idx}: [{i.severity.value}] '{i.title}' at line {i.line_number or 'N/A'} ({i.description})"
                for idx, i in enumerate(issues, 1)
            ]
        )

        numbered_code = llm.add_line_numbers(code_content)
        prompt = (
            f"File to verify: '{file_path}'\n"
            f"Candidate Issues to verify:\n{candidates_summary}\n\n"
            f"Source code (with line numbers):\n<untrusted_source_code>\n```\n{numbered_code}\n```\n</untrusted_source_code>\n\n"
            "Verify each candidate issue against the code context and return the JSON verification array."
        )

        resp = llm.call_llm_structured(
            prompt,
            response_model=StructuredVerificationResponse,
            system_prompt=SYSTEM_PROMPT,
        )

        if not resp or not resp.verifications:
            return issues

        verified_titles: Dict[str, bool] = {
            item.issue_title.lower().strip(): item.is_true_positive for item in resp.verifications
        }

        filtered_issues: List[CodeIssue] = []
        for issue in issues:
            title_key = issue.title.lower().strip()
            # If explicit false positive verdict returned, exclude it
            if title_key in verified_titles and not verified_titles[title_key]:
                logger.info(f"Verification Agent dropped false positive: '{issue.title}' in {file_path}")
                continue
            filtered_issues.append(issue)

        return filtered_issues

    async def averify_issues(self, file_path: str, code_content: str, issues: List[CodeIssue]) -> List[CodeIssue]:
        """Asynchronously verify candidate issues for true/false positives."""
        if not issues or not code_content.strip() or not llm.is_llm_available():
            return issues

        candidates_summary = "\n".join(
            [
                f"- Candidate {idx}: [{i.severity.value}] '{i.title}' at line {i.line_number or 'N/A'} ({i.description})"
                for idx, i in enumerate(issues, 1)
            ]
        )

        numbered_code = llm.add_line_numbers(code_content)
        prompt = (
            f"File to verify: '{file_path}'\n"
            f"Candidate Issues to verify:\n{candidates_summary}\n\n"
            f"Source code (with line numbers):\n<untrusted_source_code>\n```\n{numbered_code}\n```\n</untrusted_source_code>\n\n"
            "Verify each candidate issue against the code context and return the JSON verification array."
        )

        resp = await llm.acall_llm_structured(
            prompt,
            response_model=StructuredVerificationResponse,
            system_prompt=SYSTEM_PROMPT,
        )

        if not resp or not resp.verifications:
            return issues

        verified_titles: Dict[str, bool] = {
            item.issue_title.lower().strip(): item.is_true_positive for item in resp.verifications
        }

        filtered_issues: List[CodeIssue] = []
        for issue in issues:
            title_key = issue.title.lower().strip()
            if title_key in verified_titles and not verified_titles[title_key]:
                logger.info(f"Async Verification Agent dropped false positive: '{issue.title}' in {file_path}")
                continue
            filtered_issues.append(issue)

        return filtered_issues
