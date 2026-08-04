from devwatch.models import ReviewReport, IssueSeverity, StructuredSynthesizerResponse
from devwatch.agents import llm


SYSTEM_PROMPT = """You are the Synthesizer in an automated code review pipeline. You receive the deduplicated, verified findings from the Security and Quality Auditors and produce the final report shown to the developer. You do not introduce new findings — every issue in your report must trace back to an item in the input findings list. If you believe something important was missed, note it in a separate coverage_gaps field rather than inventing a finding.

TASK
1. Group findings by severity, then by file
2. Write a short executive summary (3–6 sentences): overall risk posture, the single highest-priority issue, and how many findings fall in each severity tier
3. For each finding, preserve its confidence_score as given — do not restate a 0.5-confidence finding as if it were certain
4. Where Security and Quality flagged related issues on the same lines, present them together rather than as separate entries
5. Identify systemic patterns across findings — do issues cluster in one module (localized risk) or spread across the codebase (systemic risk)? Example: "4 of 7 files have unclosed database connections, suggesting missing resource-management conventions"

RISK SCORING — Determine the verdict using these severity weights:
- CRITICAL findings = deployment blockers (weight: 10×)
- HIGH findings = must-fix before next sprint (weight: 5×)
- MEDIUM findings = should-fix, schedule within 2 sprints (weight: 2×)
- LOW findings = track in backlog (weight: 1×)
If any CRITICAL findings exist → verdict MUST be "BLOCK deployment"
If total weighted score > 15 with no CRITICAL → "Deploy with conditions"
Otherwise → "Safe to deploy"

WRITING STYLE
- Write for a technical audience (senior engineers), not non-technical stakeholders
- Be direct and specific — say "Fix X in Y" not "it is recommended that consideration be given to"
- Use quantitative language: "3 CRITICAL, 5 HIGH issues across 4 files" not "several important issues"
- Cite file:line references for the top 3 most critical findings in the executive summary
- Each summary bullet must be self-contained — readable without the detailed findings

DEDUPLICATION
When multiple findings point to the same root cause (e.g., 5 SQL injection findings all caused by f-string queries), group them as a single systemic issue with count rather than listing each individually.

OUTPUT FORMAT
Return a JSON object with these exact keys:
{
  "verdict": "BLOCK deployment | Deploy with conditions | Safe to deploy",
  "top_threat": "concise description of the single most dangerous finding with file:line reference",
  "summary_bullets": ["3-5 self-contained bullet point strings"],
  "executive_summary": "full executive summary in markdown (3-6 sentences)"
}

Do not soften or omit a Critical finding to make the report read more positively. Your job is accuracy, not reassurance.
"""


class ReportSynthesizerAgent:
    """Synthesizer Agent: Deduplicates issues and renders formatted Markdown reports."""

    def __init__(self, role: str = "Technical Review Editor"):
        self.role = role
        self.goal = SYSTEM_PROMPT

    def render_markdown(self, report: ReviewReport) -> str:
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

        if llm.is_llm_available() and report.issues:
            issues_summary = "\n".join(
                [
                    f"- [{i.severity.value}] {i.title} in `{i.file_path}:{i.line_number or 'N/A'}` "
                    f"(CWE: {i.cwe_id or 'N/A'}, Confidence: {i.confidence_score:.2f}): {i.description}"
                    for i in report.issues[:20]
                ]
            )
            prompt = (
                f"Repository: '{report.target_path}'\n"
                f"Total findings: {report.total_issues} "
                f"(Critical: {report.critical_count}, High: {report.high_count}, "
                f"Medium: {report.medium_count}, Low: {report.low_count})\n\n"
                f"Findings:\n{issues_summary}\n\n"
                "Synthesize findings and return JSON output matching the required schema."
            )
            synth_res = llm.call_llm_structured(
                prompt,
                response_model=StructuredSynthesizerResponse,
                system_prompt=SYSTEM_PROMPT,
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




