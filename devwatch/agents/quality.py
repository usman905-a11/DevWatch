import asyncio
from typing import List, Dict, Any, Optional

from devwatch.agents.base import BaseAgent, AgentMetadata
from devwatch.tools import LogicAnalyzerTool
from devwatch.tools.static_analyzer import ASTStaticAnalyzerTool
from devwatch.models import CodeIssue, IssueSeverity, StructuredQualityResponse
from devwatch.agents import llm
from devwatch.prompts.registry import prompt_registry, PromptRegistry
from devwatch.providers.factory import get_provider
from devwatch.providers.base import LLMProvider


class QualityAuditorAgent(BaseAgent):
    """Quality Auditor Agent: Detects runtime risks, unhandled exceptions, and anti-patterns."""

    def __init__(
        self,
        role: str = "Principal Code Quality Analyst",
        provider: Optional[LLMProvider] = None,
        prompt_reg: Optional[PromptRegistry] = None,
    ):
        self.role = role
        self.provider = provider or get_provider()
        self.prompt_reg = prompt_reg or prompt_registry
        self.tool = LogicAnalyzerTool()
        self.ast_analyzer = ASTStaticAnalyzerTool()

    @property
    def metadata(self) -> AgentMetadata:
        return AgentMetadata(
            agent_id="quality_auditor",
            version="1.0.0",
            purpose="Detect runtime risks, unhandled exceptions, resource leaks, and quality anti-patterns",
            prompt_id="quality:v1",
            prompt_version="1.0.0",
            input_schema="Dict[str, Any]",
            output_schema="List[CodeIssue]",
        )

    async def execute(self, context: Dict[str, Any]) -> List[CodeIssue]:
        file_path = context.get("file_path", "file.py")
        code_content = context.get("code_content", "")
        focus_areas = context.get("focus_areas")

        issues = await asyncio.to_thread(self.tool._run, file_path=file_path, code_content=code_content)
        ast_issues = await asyncio.to_thread(self.ast_analyzer.analyze_file, file_path, code_content)
        for issue in ast_issues:
            if issue.category == "Code Quality":
                issues.append(issue)

        if llm.is_llm_available(self.provider) and code_content.strip():

            focus_str = ""
            if focus_areas:
                focus_str = "Focus Areas for this review pass:\n- " + "\n- ".join(focus_areas) + "\n\n"

            evidence_str = ""
            if issues:
                evidence_str = "Baseline Static Analyzer Evidence:\n" + "\n".join(
                    [f"- Line {i.line_number or 'N/A'}: [{i.severity.value}] {i.title}" for i in issues[:10]]
                ) + "\n\n"

            numbered_code = llm.add_line_numbers(code_content)
            system_prompt = self.prompt_reg.get("quality:v1").template

            prompt = (
                f"Audit file: '{file_path}'\n"
                f"{focus_str}"
                f"{evidence_str}"
                f"Source code (with line numbers):\n<untrusted_source_code>\n```\n{numbered_code}\n```\n</untrusted_source_code>\n\n"
                "Execute your full defect taxonomy scan and return the JSON array."
            )
            qual_response = await llm.acall_llm_structured(
                prompt,
                response_model=StructuredQualityResponse,
                system_prompt=system_prompt,
                provider=self.provider,
            )

            if qual_response and qual_response.issues:
                for item in qual_response.issues:
                    if item.cwe_id or (item.category and item.category.lower() == "security"):
                        continue
                    issues.append(
                        CodeIssue(
                            file_path=file_path,
                            line_number=item.line_number,
                            severity=item.severity,
                            category=item.category or "Code Quality",
                            title=item.title,
                            description=item.description,
                            suggestion=item.suggestion,
                            code_snippet=item.code_snippet,
                            replacement_code=item.replacement_code,
                            confidence_score=item.confidence_score,
                            cwe_id=item.cwe_id,
                        )
                    )

        return issues

    def analyze(self, file_path: str, code_content: str, focus_areas: List[str] = None) -> List[CodeIssue]:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            raise RuntimeError("Cannot call synchronous analyze() within active event loop. Use 'await agent.execute(...)'.")

        return asyncio.run(self.execute({"file_path": file_path, "code_content": code_content, "focus_areas": focus_areas}))

    async def aanalyze(self, file_path: str, code_content: str, focus_areas: List[str] = None) -> List[CodeIssue]:
        return await self.execute({"file_path": file_path, "code_content": code_content, "focus_areas": focus_areas})
