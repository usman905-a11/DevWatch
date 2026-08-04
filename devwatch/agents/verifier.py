import logging
import asyncio
from typing import List, Dict, Any, Optional

from devwatch.agents.base import BaseAgent, AgentMetadata
from devwatch.models import CodeIssue, IssueSeverity, VerificationStatus, StructuredVerificationResponse
from devwatch.agents import llm
from devwatch.config import ModelTier
from devwatch.prompts.registry import prompt_registry, PromptRegistry
from devwatch.providers.factory import get_provider
from devwatch.providers.base import LLMProvider

logger = logging.getLogger("devwatch.verifier")


class VerificationAgent(BaseAgent):
    """Verification Agent: Filters false positives, escalates high-severity uncertainty, and attaches finding_id verification decisions."""

    def __init__(
        self,
        role: str = "Verification Specialist",
        provider: Optional[LLMProvider] = None,
        prompt_reg: Optional[PromptRegistry] = None,
    ):
        self.role = role
        self.provider = provider or get_provider()
        self.prompt_reg = prompt_reg or prompt_registry

    @property
    def metadata(self) -> AgentMetadata:
        return AgentMetadata(
            agent_id="verifier_agent",
            version="1.0.0",
            purpose="Verify candidate findings against exact code context using stable finding IDs",
            prompt_id="verifier:v1",
            prompt_version="1.0.0",
            input_schema="Dict[str, Any]",
            output_schema="List[CodeIssue]",
        )

    async def execute(self, context: Dict[str, Any]) -> List[CodeIssue]:
        file_path = context.get("file_path", "file.py")
        code_content = context.get("code_content", "")
        issues: List[CodeIssue] = context.get("issues", [])

        if not issues:
            return []

        # Ensure all candidate issues have stable finding_ids
        for issue in issues:
            issue.ensure_identity()

        if not code_content.strip() or not llm.is_llm_available(self.provider):
            return issues

        candidates_summary = "\n".join(
            [
                f"- [finding_id: {i.finding_id}] [{i.severity.value}] '{i.title}' at line {i.line_number or 'N/A'}: {i.description}"
                for i in issues
            ]
        )

        numbered_code = llm.add_line_numbers(code_content)
        system_prompt = self.prompt_reg.get("verifier:v1").template

        prompt = (
            f"File to verify: '{file_path}'\n"
            f"Candidate Issues to verify (by finding_id):\n{candidates_summary}\n\n"
            f"Source code (with line numbers):\n<untrusted_source_code>\n```\n{numbered_code}\n```\n</untrusted_source_code>\n\n"
            "Verify each candidate issue by finding_id and return the JSON verification array."
        )

        resp = await llm.acall_llm_structured(
            prompt,
            response_model=StructuredVerificationResponse,
            system_prompt=system_prompt,
            model_tier=ModelTier.FAST,
            provider=self.provider,
        )

        if not resp or not resp.verifications:
            return issues

        # Map verifications by finding_id and fallback issue_title
        id_map = {}
        title_map = {}

        for item in resp.verifications:
            if item.finding_id:
                id_map[item.finding_id.strip()] = item
            if item.issue_title:
                title_map[item.issue_title.lower().strip()] = item

        filtered_issues: List[CodeIssue] = []

        for issue in issues:
            fid = issue.finding_id
            v_item = id_map.get(fid) if fid else None

            if not v_item and issue.title:
                v_item = title_map.get(issue.title.lower().strip())

            if not v_item:
                filtered_issues.append(issue)
                continue

            status = v_item.status
            if isinstance(status, str):
                try:
                    status = VerificationStatus(status.upper())
                except ValueError:
                    status = VerificationStatus.ACCEPTED if v_item.is_true_positive else VerificationStatus.REJECTED

            issue.verification_rationale = v_item.reasoning

            # Decision Logic:
            if status == VerificationStatus.REJECTED or not v_item.is_true_positive:
                logger.info(f"Verification Agent REJECTED false positive [{fid}]: '{issue.title}' in {file_path}")
                continue

            if status in (VerificationStatus.UNCERTAIN, VerificationStatus.NEEDS_HUMAN_REVIEW) or v_item.confidence < 0.6:
                if issue.severity in (IssueSeverity.CRITICAL, IssueSeverity.HIGH):
                    logger.warning(
                        f"Escalating uncertain high-severity finding [{fid}] '{issue.title}' to NEEDS_HUMAN_REVIEW"
                    )
                    issue.verification_status = VerificationStatus.NEEDS_HUMAN_REVIEW
                    filtered_issues.append(issue)
                else:
                    logger.info(f"Dropping low-confidence non-critical finding [{fid}]: '{issue.title}'")
                    continue
            else:
                issue.verification_status = VerificationStatus.ACCEPTED
                filtered_issues.append(issue)

        return filtered_issues

    def verify_issues(self, file_path: str, code_content: str, issues: List[CodeIssue]) -> List[CodeIssue]:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            raise RuntimeError("Cannot call synchronous verify_issues() within active event loop. Use 'await agent.execute(...)'.")

        return asyncio.run(self.execute({"file_path": file_path, "code_content": code_content, "issues": issues}))

    async def averify_issues(self, file_path: str, code_content: str, issues: List[CodeIssue]) -> List[CodeIssue]:
        return await self.execute({"file_path": file_path, "code_content": code_content, "issues": issues})
