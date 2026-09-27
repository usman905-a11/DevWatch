from devwatch.models import ReviewReport


def render_report(report: ReviewReport, partial: bool = False) -> str:
    lines = [
        "# DevWatch Code Review Report",
        f"**Target:** `{report.target_path}`",
        "",
    ]
    if partial:
        lines.extend(
            [
                "> **Partial review:** one or more analysis stages failed; only evidence that passed the strict gate is shown.",
                "",
            ]
        )

    lines.extend(
        [
            "## Summary",
            f"- Confirmed findings: **{report.total_issues}**",
            f"- Manual review candidates: **{len(report.manual_review_candidates)}**",
            "",
        ]
    )
    if report.issues:
        lines.append("## Detailed Verified Findings")
        for index, issue in enumerate(report.issues, 1):
            lines.extend(
                [
                    f"### {index}. [{issue.severity.value}] {issue.title}",
                    f"- Location: `{issue.file_path}:{issue.line_number or issue.start_line or 'N/A'}`",
                    f"- Category: {issue.category}",
                    f"- Evidence: {issue.description}",
                    f"- Suggested remediation: {issue.suggestion}",
                    f"- Verification confidence: `{issue.verification_confidence:.2f}`",
                    "",
                ]
            )
    else:
        lines.extend(["## Confirmed Findings", "No confirmed issues were found.", ""])

    if report.manual_review_candidates:
        lines.append("## Manual Review Candidates")
        for issue in report.manual_review_candidates:
            lines.append(
                f"- [{issue.severity.value}] `{issue.file_path}:{issue.line_number or issue.start_line or 'N/A'}` — {issue.title}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
