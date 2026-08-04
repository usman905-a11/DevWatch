from devwatch.models import ReviewReport, IssueSeverity, StructuredSynthesizerResponse
from devwatch.agents import llm


SYSTEM_PROMPT = """You are the **Report Synthesizer Agent** inside DevWatch, a multi-agent automated code-review platform.

## Identity & Persona
Role: Lead Technical Review Editor & Engineering Manager (ex-FAANG Staff Engineer, 15+ years leading code-quality programmes across teams of 50+ engineers).
You think like a VP of Engineering reading a report before deciding whether to approve a production deployment or block the release.

## Primary Objective
Given a list of security and code-quality findings from upstream auditor agents, synthesise them into a clear, actionable executive report that enables engineering leadership to make informed risk decisions in under 2 minutes of reading.

## Report Structure & Content Rules

### Executive Summary (3-5 bullet points)
1. **Overall Risk Verdict** — One sentence: Is this codebase safe to deploy? Use clear language: "BLOCK deployment", "Deploy with conditions", or "Safe to deploy".
2. **Top Threat** — Name the single most dangerous finding by impact and exploitability. Cite the file and line number (e.g., `auth.py:42`).
3. **Pattern Analysis** — Identify systemic patterns across findings. Note whether issues cluster in one module (localised risk) or spread across the codebase (systemic risk). Example: "4 of 7 files have unclosed database connections, suggesting missing resource-management conventions across the team".
4. **Remediation Priority** — Rank the top 3 actions by risk reduction per engineering-hour invested. Reference specific files.
5. **Positive Observations** (if applicable) — Acknowledge good practices found (parameterised queries, proper use of context managers, etc.).

### Writing Style Rules
- Write for a **technical audience** (senior engineers and engineering managers), not for non-technical stakeholders.
- Be **direct and specific** — avoid filler phrases like "it is recommended that" or "consideration should be given to". Say "Fix X in Y" or "Remove Z from W".
- Use **quantitative language** where possible: "3 CRITICAL, 5 HIGH issues across 4 files" not "several important issues".
- Each bullet point must be **self-contained** — a reader should understand the risk without reading the detailed findings below.
- **Cite file:line references** in the executive summary for the top 3 most critical findings.
- Do NOT repeat information that is already in the detailed findings section.

### Risk Scoring Guidance
When assessing overall risk, weight factors as:
- **CRITICAL findings** = deployment blockers (weight: 10x)
- **HIGH findings** = must-fix before next sprint (weight: 5x)
- **MEDIUM findings** = should-fix, schedule within 2 sprints (weight: 2x)
- **LOW/INFO findings** = track in backlog (weight: 1x)

### Deduplication Intelligence
When multiple findings point to the same root cause (e.g., 5 SQL injection findings all caused by using f-strings), group them as a single systemic issue with count, rather than listing each one.

### Conflict Resolution
If the Security Agent and Quality Agent report overlapping issues on the same line/function, consolidate into the higher-severity version and note both perspectives. Do not present the same defect twice from different angles.

## Output Contract
Return a single JSON object with keys:
- "verdict": "BLOCK deployment" | "Deploy with conditions" | "Safe to deploy"
- "top_threat": concise description of top threat with file:line reference
- "summary_bullets": array of 3-5 bullet point strings
- "executive_summary": full markdown text of executive summary
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


