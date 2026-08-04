import asyncio
from typing import List, Callable, Optional, Set
from devwatch.scanner import CodebaseScanner
from devwatch.agents.planner import PlannerAgent
from devwatch.agents.security import SecurityAuditorAgent
from devwatch.agents.quality import QualityAuditorAgent
from devwatch.agents.verifier import VerificationAgent
from devwatch.agents.synthesizer import ReportSynthesizerAgent
from devwatch.tools import IssueDeduplicatorTool
from devwatch.models import ReviewReport, CodeIssue, AgentStepUpdate
from devwatch.pipeline.dag import ReviewPipeline
from devwatch.pipeline.context import ReviewContext


class CodeReviewEngine:
    """Multi-Agent Code Review Engine delegating pipeline execution to ReviewPipeline."""

    def __init__(
        self,
        step_callback: Optional[Callable[[AgentStepUpdate], None]] = None,
        max_concurrent_files: int = 5,
        planner: Optional[PlannerAgent] = None,
        security_agent: Optional[SecurityAuditorAgent] = None,
        quality_agent: Optional[QualityAuditorAgent] = None,
        verifier: Optional[VerificationAgent] = None,
        synthesizer: Optional[ReportSynthesizerAgent] = None,
    ):
        self.planner = planner or PlannerAgent()
        self.security_agent = security_agent or SecurityAuditorAgent()
        self.quality_agent = quality_agent or QualityAuditorAgent()
        self.verifier = verifier or VerificationAgent()
        self.synthesizer = synthesizer or ReportSynthesizerAgent()
        self.deduplicator = IssueDeduplicatorTool()
        self.step_callback = step_callback
        self.max_concurrent_files = max_concurrent_files
        self._active_tasks: Set[asyncio.Task] = set()
        
        self.pipeline = ReviewPipeline(
            planner=self.planner,
            security_agent=self.security_agent,
            quality_agent=self.quality_agent,
            verifier=self.verifier,
            synthesizer=self.synthesizer,
            step_callback=self.step_callback,
            max_concurrent_files=self.max_concurrent_files,
        )

    def _notify(self, agent_name: str, status: str, message: str):
        if self.step_callback:
            self.step_callback(
                AgentStepUpdate(agent_name=agent_name, status=status, message=message)
            )

    def cancel_active_tasks(self):
        """Cancel all running tasks managed by this engine instance."""
        self.pipeline.cancel_active_tasks()
        for task in list(self._active_tasks):
            if not task.done():
                task.cancel()
        self._active_tasks.clear()

    async def arun(self, target_path: str, context: Optional[ReviewContext] = None) -> ReviewReport:
        """Asynchronously run multi-agent review pipeline."""
        return await self.pipeline.execute(target_path, context=context)

    def run(self, target_path: str) -> ReviewReport:
        """Synchronous entry point for CLI environment (raises RuntimeError if invoked inside active event loop)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            raise RuntimeError(
                "Cannot invoke synchronous run() within an active asyncio event loop. "
                "Use 'await engine.arun(target_path)' directly."
            )

        return asyncio.run(self.arun(target_path))

    async def arun_file_audit(self, file_path: str, code_content: str) -> ReviewReport:
        """Instant single-file audit for active IDE editor buffer (async)."""
        self._notify("Security Auditor", "RUNNING", f"Auditing active file: {file_path}")
        sec_task = self.security_agent.execute({"file_path": file_path, "code_content": code_content})

        self._notify("Quality Auditor", "RUNNING", f"Auditing active file: {file_path}")
        qual_task = self.quality_agent.execute({"file_path": file_path, "code_content": code_content})

        sec_issues, qual_issues = await asyncio.gather(sec_task, qual_task)
        raw_issues = sec_issues + qual_issues

        self._notify("Verification Agent", "RUNNING", f"Verifying active file findings: {file_path}")
        verified_issues = await self.verifier.execute({"file_path": file_path, "code_content": code_content, "issues": raw_issues})
        deduped = await asyncio.to_thread(self.deduplicator._run, verified_issues)

        report = ReviewReport(target_path=file_path, issues=deduped)
        report.summary = await self.synthesizer.execute({"report": report})
        self._notify(
            "Synthesizer Agent",
            "COMPLETED",
            f"Instant file audit complete: {report.total_issues} issues found",
        )
        return report

    def run_file_audit(self, file_path: str, code_content: str) -> ReviewReport:
        """Synchronous wrapper for single file audit (raises RuntimeError if inside active event loop)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            raise RuntimeError(
                "Cannot invoke synchronous run_file_audit() within an active asyncio event loop. "
                "Use 'await engine.arun_file_audit(...)' directly."
            )

        return asyncio.run(self.arun_file_audit(file_path, code_content))

    async def arun_files_audit(self, files: List[dict]) -> ReviewReport:
        """Audit multiple in-memory files (e.g. uploaded via web app)."""
        self._notify("Planner Agent", "RUNNING", f"Planning review for {len(files)} files")
        raw_issues: List[CodeIssue] = []
        semaphore = asyncio.Semaphore(self.max_concurrent_files)

        async def analyze_single_file(item: dict):
            rel_path = item.get("file_path", "file.txt")
            code = item.get("content", "")
            if not code or len(code.strip()) == 0:
                return []
            async with semaphore:
                self._notify("Security Auditor", "RUNNING", f"Auditing {rel_path} for OWASP vulnerabilities")
                sec_task = self.security_agent.execute({"file_path": rel_path, "code_content": code})
                self._notify("Quality Auditor", "RUNNING", f"Auditing {rel_path} for logic flaws")
                qual_task = self.quality_agent.execute({"file_path": rel_path, "code_content": code})

                sec_issues, qual_issues = await asyncio.gather(sec_task, qual_task)
                file_raw = sec_issues + qual_issues

                self._notify("Verification Agent", "RUNNING", f"Verifying findings in {rel_path}")
                verified = await self.verifier.execute({"file_path": rel_path, "code_content": code, "issues": file_raw})
                return verified

        file_tasks = [asyncio.create_task(analyze_single_file(f)) for f in files]
        for t in file_tasks:
            self._active_tasks.add(t)

        try:
            if file_tasks:
                results = await asyncio.gather(*file_tasks)
                for res in results:
                    raw_issues.extend(res)
        finally:
            for t in file_tasks:
                self._active_tasks.discard(t)

        self._notify("Synthesizer Agent", "RUNNING", "Deduplicating & prioritizing issues")
        deduped = await asyncio.to_thread(self.deduplicator._run, raw_issues)
        report = ReviewReport(target_path="uploaded_workspace", issues=deduped)
        report.summary = await self.synthesizer.execute({"report": report})
        self._notify("Synthesizer Agent", "COMPLETED", f"Audit complete: {report.total_issues} issues found")
        return report


# Backwards compatibility alias
CodeReviewCrew = CodeReviewEngine
