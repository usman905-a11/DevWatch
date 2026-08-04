import asyncio
from typing import List, Dict, Any, Optional

from devwatch.agents.base import BaseAgent, AgentMetadata
from devwatch.scanner import CodebaseScanner
from devwatch.models import ReviewScope, StructuredPlannerResponse
from devwatch.agents import llm
from devwatch.config import Config, ModelTier
from devwatch.tools import GitDiffTool
from devwatch.prompts.registry import prompt_registry, PromptRegistry
from devwatch.providers.factory import get_provider
from devwatch.providers.base import LLMProvider


class PlannerAgent(BaseAgent):
    """Planner Agent: Analyzes workspace risk and outputs focused audit plan."""

    def __init__(
        self,
        role: str = "Lead Security Architect",
        provider: Optional[LLMProvider] = None,
        prompt_reg: Optional[PromptRegistry] = None,
    ):
        self.role = role
        self.provider = provider or get_provider()
        self.prompt_reg = prompt_reg or prompt_registry
        self.git_tool = GitDiffTool()

    @property
    def metadata(self) -> AgentMetadata:
        return AgentMetadata(
            agent_id="planner_agent",
            version="1.0.0",
            purpose="Scope and sequence codebase review priority files and focus areas",
            prompt_id="planner:v1",
            prompt_version="1.0.0",
            input_schema="Dict[str, Any]",
            output_schema="ReviewScope",
        )

    async def execute(self, context: Dict[str, Any]) -> ReviewScope:
        target_path = context.get("target_path", ".")
        scanner = CodebaseScanner(target_path)
        all_files = await asyncio.to_thread(scanner.get_files)
        diff_text = await asyncio.to_thread(self.git_tool._run, target_path)

        diff_summary = ""
        if diff_text and "No uncommitted git changes" not in diff_text:
            diff_summary = f"Git Diff Context:\n```\n{diff_text[:2000]}\n```\n"

        default_focus = [
            "OWASP Top 10 Security Vulnerabilities",
            "Unhandled Exceptions & Panic Recovery",
            "Hardcoded Secrets & API Keys",
            "Performance Bottlenecks & N+1 Queries",
        ]

        priority_files = all_files[:20]
        focus_areas = default_focus

        if llm.is_llm_available(self.provider) and len(all_files) > 0:

            file_list_str = "\n".join(all_files[:200])
            system_prompt = self.prompt_reg.get("planner:v1").template
            prompt = (
                f"Repository root: '{target_path}'\n"
                f"Total files discovered: {len(all_files)}\n\n"
                f"File listing:\n{file_list_str}\n\n"
                f"{diff_summary}\n"
                "Analyze these files and identify the top priority files and focus areas."
            )

            planner_res = await llm.acall_llm_structured(
                prompt,
                response_model=StructuredPlannerResponse,
                system_prompt=system_prompt,
                model_tier=ModelTier.FAST,
                provider=self.provider,
            )

            if planner_res:
                if planner_res.priority_files:
                    valid_files = [f for f in planner_res.priority_files if f in all_files]
                    if valid_files:
                        priority_files = valid_files
                if planner_res.focus_areas:
                    focus_areas = planner_res.focus_areas

        return ReviewScope(
            target_path=target_path,
            files_to_review=priority_files,
            focus_areas=focus_areas,
        )

    def plan_review(self, target_path: str) -> ReviewScope:
        """Backwards compatibility method delegating to execute."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            raise RuntimeError("Cannot invoke synchronous plan_review() inside running event loop. Use 'await agent.execute(...)'.")

        return asyncio.run(self.execute({"target_path": target_path}))
