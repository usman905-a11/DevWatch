import asyncio
from typing import List, Callable, Optional
from devwatch.scanner import CodebaseScanner
from devwatch.agents.planner import PlannerAgent
from devwatch.agents.security import SecurityAuditorAgent
from devwatch.agents.quality import QualityAuditorAgent
from devwatch.agents.verifier import VerificationAgent
from devwatch.agents.synthesizer import ReportSynthesizerAgent
from devwatch.tools import IssueDeduplicatorTool
from devwatch.models import ReviewReport, CodeIssue, AgentStepUpdate


class CodeReviewEngine:
    """Multi-Agent Code Review Engine orchestrating Planner, Security, Quality, Verifier, and Synthesizer agents."""

    def __init__(
        self,
        step_callback: Optional[Callable[[AgentStepUpdate], None]] = None,
        max_concurrent_files: int = 5,
    ):
        self.planner = PlannerAgent()
        self.security_agent = SecurityAuditorAgent()
        self.quality_agent = QualityAuditorAgent()
        self.verifier = VerificationAgent()
        self.synthesizer = ReportSynthesizerAgent()
        self.deduplicator = IssueDeduplicatorTool()
        self.step_callback = step_callback
        self.max_concurrent_files = max_concurrent_files

    def _notify(self, agent_name: str, status: str, message: str):
        if self.step_callback:
            self.step_callback(
                AgentStepUpdate(agent_name=agent_name, status=status, message=message)
            )

    async def arun(self, target_path: str) -> ReviewReport:
        """Asynchronously run multi-agent review with parallel fan-out/fan-in execution."""
        # Step 1: Planner Agent
        self._notify("Planner Agent", "RUNNING", f"Mapping risk areas for {target_path}")
        scanner = CodebaseScanner(target_path)
        scope = self.planner.plan_review(target_path)
        self._notify(
            "Planner Agent",
            "COMPLETED",
            f"Scope planned: {len(scope.files_to_review)} files to analyze",
        )

        # Step 2: Parallel Analysis with asyncio.gather()
        semaphore = asyncio.Semaphore(self.max_concurrent_files)
        raw_issues: List[CodeIssue] = []

        async def analyze_file(rel_path: str):
            async with semaphore:
                code = scanner.read_file(rel_path)

                self._notify(
                    "Security Auditor", "RUNNING", f"Auditing {rel_path} for OWASP vulnerabilities"
                )
                sec_task = self.security_agent.aanalyze(
                    rel_path, code, focus_areas=scope.focus_areas
                )

                self._notify(
                    "Quality Auditor", "RUNNING", f"Auditing {rel_path} for logic & exception flaws"
                )
                qual_task = self.quality_agent.aanalyze(
                    rel_path, code, focus_areas=scope.focus_areas
                )

                sec_issues, qual_issues = await asyncio.gather(sec_task, qual_task)
                file_raw = sec_issues + qual_issues

                # Step 2.5: Verification Pass per file
                self._notify("Verification Agent", "RUNNING", f"Verifying candidate issues in {rel_path}")
                verified_file_issues = await self.verifier.averify_issues(rel_path, code, file_raw)

                self._notify(
                    "Security Auditor",
                    "COMPLETED",
                    f"Found {len(sec_issues)} security issues in {rel_path}",
                )
                self._notify(
                    "Quality Auditor",
                    "COMPLETED",
                    f"Found {len(qual_issues)} quality issues in {rel_path}",
                )
                self._notify(
                    "Verification Agent",
                    "COMPLETED",
                    f"Verified {len(verified_file_issues)} true positive findings in {rel_path}",
                )
                return verified_file_issues

        file_tasks = [analyze_file(f) for f in scope.files_to_review]
        if file_tasks:
            task_results = await asyncio.gather(*file_tasks)
            for res in task_results:
                raw_issues.extend(res)

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

    def run(self, target_path: str) -> ReviewReport:
        """Synchronous wrapper for backwards compatibility."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import nest_asyncio

            nest_asyncio.apply()
            return loop.run_until_complete(self.arun(target_path))
        else:
            return asyncio.run(self.arun(target_path))

    async def arun_file_audit(self, file_path: str, code_content: str) -> ReviewReport:
        """Instant single-file audit for active IDE editor buffer (async)."""
        self._notify("Security Auditor", "RUNNING", f"Auditing active file: {file_path}")
        sec_task = self.security_agent.aanalyze(file_path, code_content)

        self._notify("Quality Auditor", "RUNNING", f"Auditing active file: {file_path}")
        qual_task = self.quality_agent.aanalyze(file_path, code_content)

        sec_issues, qual_issues = await asyncio.gather(sec_task, qual_task)
        raw_issues = sec_issues + qual_issues

        self._notify("Verification Agent", "RUNNING", f"Verifying active file findings: {file_path}")
        verified_issues = await self.verifier.averify_issues(file_path, code_content, raw_issues)
        deduped = self.deduplicator._run(verified_issues)

        report = ReviewReport(target_path=file_path, issues=deduped)
        report.summary = self.synthesizer.render_markdown(report)
        self._notify(
            "Synthesizer Agent",
            "COMPLETED",
            f"Instant file audit complete: {report.total_issues} issues found",
        )
        return report

    def run_file_audit(self, file_path: str, code_content: str) -> ReviewReport:
        """Synchronous wrapper for single file audit."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import nest_asyncio

            nest_asyncio.apply()
            return loop.run_until_complete(self.arun_file_audit(file_path, code_content))
        else:
            return asyncio.run(self.arun_file_audit(file_path, code_content))


# Backwards compatibility alias
CodeReviewCrew = CodeReviewEngine


