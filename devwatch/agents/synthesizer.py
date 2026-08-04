from devwatch.models import ReviewReport, IssueSeverity, StructuredSynthesizerResponse
from devwatch.agents import llm


SYSTEM_PROMPT = """You are the Synthesizer in an automated code review pipeline. You receive the deduplicated, verified findings from the Security and Quality Auditors and produce the final report shown to the developer. You do not introduce new findings — every issue in your report must trace back to an item in the input findings list. If you believe something important was missed, note it in a separate coverage_gaps field rather than inventing a finding.

TASK
1. Group findings by severity, then by file
2. Write a short executive summary (3–6 sentences): overall risk posture, the single highest-priority issue, and how many findings fall in each severity tier
3. For each finding, preserve its confidence_score and evidence_source as given — do not restate a Medium-confidence finding as if it were certain
4. Where Security and Quality flagged related issues on the same lines, present them together rather than as separate entries
5. Order the report so Critical/High findings with confidence_score ≥ 0.7 appear first; lower-confidence findings go in a clearly separated "needs manual review" section rather than mixed in with confirmed issues

OUTPUT FORMAT
Return a JSON object matching the ReviewReport schema:
{
  "verdict": "BLOCK deployment | Deploy with conditions | Safe to deploy",
  "top_threat": "string",
  "summary_bullets": ["string"],
  "executive_summary": "string"
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
        md.append(f"**Target Path:** `{report.target_path}`")
        md.append(
            f"**Total Issues Found:** {report.total_issues} "
            f"(Critical: {report.critical_count}, High: {report.high_count}, "
            f"Medium: {report.medium_count}, Low: {report.low_count})\n"
        )

        if not report.issues:
            md.append("✅ **No severe issues detected. Code is looking clean!**")
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
                "Synthesize findings and return JSON output."
            )
            synth_res = llm.call_llm_structured(
                prompt,
                response_model=StructuredSynthesizerResponse,
                system_prompt=SYSTEM_PROMPT,
            )
            if synth_res and synth_res.executive_summary:
                md.append("## Executive AI Summary & Recommendation\n")
                md.append(f"**Verdict:** {synth_res.verdict}\n")
                if synth_res.top_threat:
                    md.append(f"**Top Threat:** {synth_res.top_threat}\n")
                md.append(synth_res.executive_summary.strip() + "\n")

        md.append("## Detailed Findings\n")
        for idx, issue in enumerate(report.issues, 1):
            cwe_str = f" | CWE: {issue.cwe_id}" if issue.cwe_id else ""
            conf_str = f" | Confidence: {issue.confidence_score:.2f}"
            md.append(f"### {idx}. [{issue.severity.value}] {issue.title}")
            md.append(f"- **File:** `{issue.file_path}:{issue.line_number or 'N/A'}`{cwe_str}{conf_str}")
            md.append(f"- **Category:** {issue.category}")
            md.append(f"- **Description:** {issue.description}")
            if issue.code_snippet:
                md.append(f"```python\n{issue.code_snippet}\n```")
            md.append(f"- **Suggestion:** {issue.suggestion}\n")

        return "\n".join(md)


