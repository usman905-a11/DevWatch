import asyncio
from typing import Dict, Any, Optional

from devwatch.agents.base import BaseAgent, AgentMetadata
from devwatch.models import ReviewReport, IssueSeverity, StructuredSynthesizerResponse
from devwatch.agents import llm
from devwatch.prompts.registry import prompt_registry, PromptRegistry
from devwatch.providers.factory import get_provider
from devwatch.providers.base import LLMProvider


class ReportSynthesizerAgent(BaseAgent):
    """Synthesizer Agent: Deduplicates issues and renders formatted Markdown reports."""

    def __init__(
        self,
        role: str = "Technical Review Editor",
        provider: Optional[LLMProvider] = None,
        prompt_reg: Optional[PromptRegistry] = None,
    ):
        self.role = role
        self.provider = provider or get_provider()
        self.prompt_reg = prompt_reg or prompt_registry

    @property
    def metadata(self) -> AgentMetadata:
        return AgentMetadata(
            agent_id="report_synthesizer",
            version="1.0.0",
            purpose="Synthesize executive code review summaries and render formatted Markdown reports",
            prompt_id="synthesizer:v1",
            prompt_version="1.0.0",
            input_schema="ReviewReport",
            output_schema="str",
        )

    async def execute(self, context: Dict[str, Any]) -> str:
        report: ReviewReport = context.get("report")
        if not report:
            raise ValueError("ReportSynthesizerAgent requires 'report' parameter in context")

        md = []
        md.append("# DevWatch Code Review Report")
        md.append(f"**Target Workspace / File:** `{report.target_path}`\n")
        
        # Summary Statistics Table
        md.append("## Executive Summary Metrics\n")
        md.append("| Metric | Count |")
        md.append("| :--- | :---: |")
        md.append(f"| **Total Findings** | `{report.total_issues}` |")
        md.append(f"| **Critical** | `{report.critical_count}` |")
        md.append(f"| **High** | `{report.high_count}` |")
        md.append(f"| **Medium** | `{report.medium_count}` |")
        md.append(f"| **Low / Info** | `{report.low_count}` |\n")

        if not report.issues:
            md.append("✅ **No severe security or quality issues detected. Codebase is clean!**")
            return "\n".join(md)

        if llm.is_llm_available(self.provider) and report.issues:

            issues_summary = "\n".join(
                [
                    f"- [{i.severity.value}] {i.title} in `{i.file_path}:{i.line_number or 'N/A'}` "
                    f"(CWE: {i.cwe_id or 'N/A'}, Confidence: {i.confidence_score:.2f}): {i.description}"
                    for i in report.issues[:20]
                ]
            )
            system_prompt = self.prompt_reg.get("synthesizer:v1").template

            prompt = (
                f"Repository: '{report.target_path}'\n"
                f"Total findings: {report.total_issues} "
                f"(Critical: {report.critical_count}, High: {report.high_count}, "
                f"Medium: {report.medium_count}, Low: {report.low_count})\n\n"
                f"Findings:\n{issues_summary}\n\n"
                "Synthesize findings and return JSON output matching the required schema."
            )
            synth_res = await llm.acall_llm_structured(
                prompt,
                response_model=StructuredSynthesizerResponse,
                system_prompt=system_prompt,
                provider=self.provider,
            )

            if synth_res and synth_res.executive_summary:
                md.append("## AI Risk Verdict & Recommendations\n")
                md.append(f"**Deployment Verdict:** `{synth_res.verdict}`\n")
                if synth_res.top_threat:
                    md.append(f"> **Top Priority Threat:** {synth_res.top_threat}\n")
                
                if synth_res.summary_bullets:
                    md.append("### Key Takeaways")
                    for bullet in synth_res.summary_bullets:
                        md.append(f"- {bullet}")
                    md.append("")
                
                md.append("### Executive Risk Summary")
                md.append(synth_res.executive_summary.strip() + "\n")

        md.append("## Detailed Verified Findings\n")
        for idx, issue in enumerate(report.issues, 1):
            cwe_str = f" | **CWE:** `{issue.cwe_id}`" if issue.cwe_id else ""
            conf_str = f" | **Confidence:** `{issue.confidence_score:.2f}`"
            
            md.append(f"### {idx}. [{issue.severity.value}] {issue.title}")
            md.append(f"- **Location:** `{issue.file_path}:{issue.line_number or 'N/A'}`{cwe_str}{conf_str}")
            md.append(f"- **Category:** {issue.category}")
            md.append(f"- **Description:** {issue.description}")
            
            if issue.code_snippet:
                md.append("```python")
                md.append(issue.code_snippet)
                md.append("```")
                
            md.append(f"- **Suggested Fix:** {issue.suggestion}")
            if issue.replacement_code:
                md.append("\n**Proposed Code Replacement (IDE Quick-Fix Ready):**")
                md.append("```python")
                md.append(issue.replacement_code)
                md.append("```")
            md.append("\n---")

        return "\n".join(md)

    def render_markdown(self, report: ReviewReport) -> str:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            raise RuntimeError("Cannot call synchronous render_markdown() inside active event loop. Use 'await agent.execute(...)'.")

        return asyncio.run(self.execute({"report": report}))
