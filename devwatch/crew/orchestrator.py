from typing import List, Callable, Optional
from devwatch.scanner import CodebaseScanner
from devwatch.agents.planner import PlannerAgent
from devwatch.agents.security import SecurityAuditorAgent
from devwatch.agents.quality import QualityAuditorAgent
from devwatch.agents.synthesizer import ReportSynthesizerAgent
from devwatch.tools import IssueDeduplicatorTool
from devwatch.models import ReviewReport, CodeIssue, AgentStepUpdate


class CodeReviewEngine:
    """Multi-Agent Code Review Engine orchestrating Planner, Security, Quality, and Synthesizer agents."""

    def __init__(self, step_callback: Optional[Callable[[AgentStepUpdate], None]] = None):
        self.planner = PlannerAgent()
        self.security_agent = SecurityAuditorAgent()
        self.quality_agent = QualityAuditorAgent()
        self.synthesizer = ReportSynthesizerAgent()
        self.deduplicator = IssueDeduplicatorTool()
        self.step_callback = step_callback

    def _notify(self, agent_name: str, status: str, message: str):
        if self.step_callback:
            self.step_callback(
                AgentStepUpdate(agent_name=agent_name, status=status, message=message)
            )

    def run(self, target_path: str) -> ReviewReport:
        # Step 1: Planner Agent
        self._notify("Planner Agent", "RUNNING", f"Mapping risk areas for {target_path}")
        scanner = CodebaseScanner(target_path)
        scope = self.planner.plan_review(target_path)
        self._notify(
            "Planner Agent",
            "COMPLETED",
            f"Scope planned: {len(scope.files_to_review)} files to analyze",
        )

        # Step 2: Parallel Analysis (Security Auditor + Quality Auditor)
        raw_issues: List[CodeIssue] = []

        for rel_path in scope.files_to_review:
            code = scanner.read_file(rel_path)

            self._notify(
                "Security Auditor", "RUNNING", f"Auditing {rel_path} for OWASP vulnerabilities"
            )
            sec_issues = self.security_agent.analyze(rel_path, code, focus_areas=scope.focus_areas)
            raw_issues.extend(sec_issues)
            self._notify(
                "Security Auditor",
                "COMPLETED",
                f"Found {len(sec_issues)} security issues in {rel_path}",
            )

            self._notify(
                "Quality Auditor", "RUNNING", f"Auditing {rel_path} for logic & exception flaws"
            )
            qual_issues = self.quality_agent.analyze(rel_path, code, focus_areas=scope.focus_areas)

            raw_issues.extend(qual_issues)
            self._notify(
                "Quality Auditor",
                "COMPLETED",
                f"Found {len(qual_issues)} quality issues in {rel_path}",
            )

        # Step 3: Issue Deduplication
        self._notify("Synthesizer Agent", "RUNNING", "Deduplicating & prioritizing issues")
        deduped_issues = self.deduplicator._run(raw_issues)

        # Step 4: Report Synthesis
        report = ReviewReport(target_path=target_path, issues=deduped_issues)
        report.summary = self.synthesizer.render_markdown(report)
        self._notify(
            "Synthesizer Agent",
            "COMPLETED",
            f"Report generated: {report.total_issues} total issues",
        )

        return report

    def run_file_audit(self, file_path: str, code_content: str) -> ReviewReport:
        """Instant single-file audit for active IDE editor buffer."""
        self._notify("Security Auditor", "RUNNING", f"Auditing active file: {file_path}")
        sec_issues = self.security_agent.analyze(file_path, code_content)

        self._notify("Quality Auditor", "RUNNING", f"Auditing active file: {file_path}")
        qual_issues = self.quality_agent.analyze(file_path, code_content)

        raw_issues = sec_issues + qual_issues
        deduped = self.deduplicator._run(raw_issues)

        report = ReviewReport(target_path=file_path, issues=deduped)
        report.summary = self.synthesizer.render_markdown(report)
        self._notify(
            "Synthesizer Agent",
            "COMPLETED",
            f"Instant file audit complete: {report.total_issues} issues found",
        )
        return report


# Backwards compatibility alias
CodeReviewCrew = CodeReviewEngine


