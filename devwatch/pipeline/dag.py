import asyncio
import logging
from typing import List, Callable, Optional, Set, Dict, Any

from devwatch.config import Config
from devwatch.scanner import CodebaseScanner
from devwatch.pipeline.context import ReviewContext, ReviewOutcome
from devwatch.models import ReviewReport, CodeIssue, ReviewScope, IssueSeverity, VerificationStatus, AgentStepUpdate

from devwatch.agents.planner import PlannerAgent
from devwatch.agents.security import SecurityAuditorAgent
from devwatch.agents.quality import QualityAuditorAgent
from devwatch.agents.verifier import VerificationAgent
from devwatch.agents.synthesizer import ReportSynthesizerAgent
from devwatch.tools import IssueDeduplicatorTool, GitDiffTool, SecurityPatternTool, LogicAnalyzerTool
from devwatch.tools.static_analyzer import ASTStaticAnalyzerTool

logger = logging.getLogger("devwatch.pipeline.dag")


class ReviewPipeline:
    """Typed, resilient DAG pipeline executing codebase audits with isolated stage recovery."""

    def __init__(
        self,
        planner: Optional[PlannerAgent] = None,
        security_agent: Optional[SecurityAuditorAgent] = None,
        quality_agent: Optional[QualityAuditorAgent] = None,
        verifier: Optional[VerificationAgent] = None,
        synthesizer: Optional[ReportSynthesizerAgent] = None,
        step_callback: Optional[Callable[[AgentStepUpdate], None]] = None,
        max_concurrent_files: int = 5,
    ):
        self.planner = planner or PlannerAgent()
        self.security_agent = security_agent or SecurityAuditorAgent()
        self.quality_agent = quality_agent or QualityAuditorAgent()
        self.verifier = verifier or VerificationAgent()
        self.synthesizer = synthesizer or ReportSynthesizerAgent()
        self.deduplicator = IssueDeduplicatorTool()
        self.git_tool = GitDiffTool()
        self.security_pattern_tool = SecurityPatternTool()
        self.logic_analyzer_tool = LogicAnalyzerTool()
        self.ast_analyzer_tool = ASTStaticAnalyzerTool()
        self.step_callback = step_callback
        self.max_concurrent_files = max_concurrent_files
        self._active_tasks: Set[asyncio.Task] = set()

    def _notify(self, agent_name: str, status: str, message: str):
        if self.step_callback:
            self.step_callback(
                AgentStepUpdate(agent_name=agent_name, status=status, message=message)
            )

    def cancel_active_tasks(self):
        """Cancel running async tasks."""
        for task in list(self._active_tasks):
            if not task.done():
                task.cancel()

    async def execute(self, target_path: str, context: Optional[ReviewContext] = None) -> ReviewReport:
        """Execute review pipeline with global deadline and partial failure recovery."""
        ctx = context or ReviewContext(target_path=target_path)
        ctx.target_path = target_path

        try:
            async with asyncio.timeout(Config.GLOBAL_REVIEW_TIMEOUT_SECONDS):
                return await self._run_pipeline(ctx)
        except TimeoutError:
            ctx.status = ReviewOutcome.FAILED
            ctx.record_failure("GLOBAL_DEADLINE", "Pipeline", TimeoutError(f"Global review timeout ({Config.GLOBAL_REVIEW_TIMEOUT_SECONDS}s) exceeded"))
            raise TimeoutError(f"Global review execution deadline ({Config.GLOBAL_REVIEW_TIMEOUT_SECONDS}s) exceeded for {target_path}")
        except asyncio.CancelledError:
            ctx.status = ReviewOutcome.CANCELLED
            raise

    async def _run_pipeline(self, ctx: ReviewContext) -> ReviewReport:
        target_path = ctx.target_path

        # Stage 1: Discovery
        ctx.check_cancellation()
        self._notify("Pipeline", "RUNNING", f"Discovering workspace: {target_path}")
        scanner = CodebaseScanner(target_path)
        all_files = await asyncio.to_thread(scanner.get_files)

        if not all_files:
            logger.info(f"Empty repository or no supported files at {target_path}")
            ctx.status = ReviewOutcome.COMPLETED
            report = ReviewReport(target_path=target_path, issues=[])
            report.summary = "# DevWatch Code Review Report\n\n✅ **Empty repository or no reviewable source code files found.**"
            return report

        # Stage 2: Planning
        ctx.check_cancellation()
        self._notify("Planner Agent", "RUNNING", f"Planning review for {target_path}")
        try:
            scope = await self.planner.execute({"target_path": target_path})
            ctx.scope = scope
            ctx.selected_files = scope.files_to_review
        except Exception as err:
            logger.warning(f"Planner Agent failed: {err}. Falling back to default scope.")
            ctx.record_failure("PLANNING", "PlannerAgent", err)
            ctx.selected_files = all_files[:20]
            ctx.scope = ReviewScope(
                target_path=target_path,
                files_to_review=ctx.selected_files,
                focus_areas=["OWASP Security Vulnerabilities", "Unhandled Exceptions & Logic Flaws"],
            )

        self._notify("Planner Agent", "COMPLETED", f"Scope planned: {len(ctx.selected_files)} files")

        # Stage 3: Isolated Parallel Audit (Security & Quality per file)
        ctx.check_cancellation()
        semaphore = asyncio.Semaphore(self.max_concurrent_files)
        raw_candidates: List[CodeIssue] = []

        async def analyze_single_file(rel_path: str) -> List[CodeIssue]:
            async with semaphore:
                file_issues: List[CodeIssue] = []
                code = ""
                try:
                    code = await asyncio.to_thread(scanner.read_file, rel_path)
                except Exception as err:
                    logger.error(f"Failed to read file {rel_path}: {err}")
                    ctx.record_failure("FILE_READ", rel_path, err)
                    return []

                # Static analysis (AST, pattern, logic)
                try:
                    ast_issues = await asyncio.to_thread(self.ast_analyzer_tool.analyze_file, rel_path, code)
                    file_issues.extend(ast_issues)
                except Exception as err:
                    ctx.record_failure("STATIC_AST", rel_path, err)

                # Security & Quality Agent Audits executed with return_exceptions=True
                sec_coro = self.security_agent.execute({
                    "file_path": rel_path,
                    "code_content": code,
                    "focus_areas": ctx.scope.focus_areas if ctx.scope else [],
                })
                qual_coro = self.quality_agent.execute({
                    "file_path": rel_path,
                    "code_content": code,
                    "focus_areas": ctx.scope.focus_areas if ctx.scope else [],
                })

                results = await asyncio.gather(sec_coro, qual_coro, return_exceptions=True)

                sec_res = results[0]
                qual_res = results[1]

                if isinstance(sec_res, Exception):
                    logger.warning(f"Security Auditor Agent failed for {rel_path}: {sec_res}")
                    ctx.record_failure("SECURITY_ANALYSIS", rel_path, sec_res)
                elif isinstance(sec_res, list):
                    file_issues.extend(sec_res)

                if isinstance(qual_res, Exception):
                    logger.warning(f"Quality Auditor Agent failed for {rel_path}: {qual_res}")
                    ctx.record_failure("QUALITY_ANALYSIS", rel_path, qual_res)
                elif isinstance(qual_res, list):
                    file_issues.extend(qual_res)

                return file_issues

        file_tasks = [asyncio.create_task(analyze_single_file(f)) for f in ctx.selected_files]
        for t in file_tasks:
            self._active_tasks.add(t)

        try:
            if file_tasks:
                task_results = await asyncio.gather(*file_tasks, return_exceptions=True)
                for res in task_results:
                    if isinstance(res, list):
                        raw_candidates.extend(res)
                    elif isinstance(res, Exception):
                        ctx.record_failure("PARALLEL_AUDIT", "file_task", res)
        finally:
            for t in file_tasks:
                self._active_tasks.discard(t)

        # Stage 4: Deduplication
        ctx.check_cancellation()
        self._notify("Synthesizer Agent", "RUNNING", "Deduplicating & normalizing candidate findings")
        try:
            deduped_issues = await asyncio.to_thread(self.deduplicator._run, raw_candidates)
        except Exception as err:
            logger.warning(f"Deduplication failed: {err}. Using raw candidates.")
            ctx.record_failure("DEDUPLICATION", "IssueDeduplicatorTool", err)
            deduped_issues = raw_candidates

        # Stage 5: Verification
        ctx.check_cancellation()
        self._notify("Verification Agent", "RUNNING", "Verifying candidate findings against source code")
        verified_issues: List[CodeIssue] = []

        if deduped_issues:
            # Group issues by file for verification pass
            file_groups: Dict[str, List[CodeIssue]] = {}
            for issue in deduped_issues:
                file_groups.setdefault(issue.file_path, []).append(issue)

            for rel_path, group_issues in file_groups.items():
                try:
                    code = await asyncio.to_thread(scanner.read_file, rel_path)
                    v_res = await self.verifier.execute({
                        "file_path": rel_path,
                        "code_content": code,
                        "issues": group_issues,
                    })
                    if isinstance(v_res, list):
                        verified_issues.extend(v_res)
                    else:
                        verified_issues.extend(group_issues)
                except Exception as err:
                    logger.warning(f"Verification Agent failed for {rel_path}: {err}. Retaining unverified candidate issues.")
                    ctx.record_failure("VERIFICATION", rel_path, err)
                    verified_issues.extend(group_issues)
        
        ctx.final_issues = verified_issues
        for issue in ctx.final_issues:
            issue.ensure_identity()

        report = ReviewReport(target_path=target_path, issues=ctx.final_issues)

        # Check if any findings require human review
        has_human_review = any(
            i.verification_status == VerificationStatus.NEEDS_HUMAN_REVIEW for i in ctx.final_issues
        )
        if has_human_review and ctx.status == ReviewOutcome.COMPLETED:
            ctx.status = ReviewOutcome.NEEDS_HUMAN_REVIEW

        # Stage 6: Deterministic Metric Calculation & Synthesis
        ctx.check_cancellation()
        self._notify("Synthesizer Agent", "RUNNING", "Rendering executive review report")

        # Compute metrics deterministically in Python
        ctx.metrics = {
            "total_issues": report.total_issues,
            "critical_count": report.critical_count,
            "high_count": report.high_count,
            "medium_count": report.medium_count,
            "low_count": report.low_count,
            "needs_human_review_count": sum(
                1 for i in ctx.final_issues if i.verification_status == VerificationStatus.NEEDS_HUMAN_REVIEW
            ),
            "deterministic_verdict": self._compute_deterministic_verdict(report),
        }


        try:
            report.summary = await self.synthesizer.execute({"report": report})
        except Exception as err:
            logger.warning(f"ReportSynthesizerAgent failed: {err}. Rendering deterministic Markdown report.")
            ctx.record_failure("SYNTHESIS", "ReportSynthesizerAgent", err)
            report.summary = self._render_deterministic_fallback_report(report, ctx)

        if ctx.stage_failures and ctx.status == ReviewOutcome.COMPLETED:
            ctx.status = ReviewOutcome.PARTIALLY_COMPLETED

        return report

    def _compute_deterministic_verdict(self, report: ReviewReport) -> str:
        """Compute verdict deterministically based on severity rules."""
        if report.critical_count > 0:
            return "BLOCK deployment"
        if report.high_count > 2 or report.total_issues > 10:
            return "Deploy with conditions"
        return "Safe to deploy"

    def _render_deterministic_fallback_report(self, report: ReviewReport, ctx: ReviewContext) -> str:
        """Render clean, deterministic Markdown report when LLM synthesis fails."""
        verdict = ctx.metrics.get("deterministic_verdict", "Safe to deploy")
        md = []
        md.append("# DevWatch Code Review Report")
        md.append(f"**Target Workspace / File:** `{report.target_path}`\n")
        
        if ctx.status == ReviewOutcome.PARTIALLY_COMPLETED:
            md.append("> ⚠️ **Partial Execution Warning:** Some analysis stages encountered errors. Partial findings have been preserved below.\n")

        md.append("## Executive Summary Metrics\n")
        md.append("| Metric | Count |")
        md.append("| :--- | :---: |")
        md.append(f"| **Total Findings** | `{report.total_issues}` |")
        md.append(f"| **Critical** | `{report.critical_count}` |")
        md.append(f"| **High** | `{report.high_count}` |")
        md.append(f"| **Medium** | `{report.medium_count}` |")
        md.append(f"| **Low / Info** | `{report.low_count}` |\n")
        md.append(f"**Deterministic Deployment Verdict:** `{verdict}`\n")

        if not report.issues:
            md.append("✅ **No severe security or quality issues detected.**")
            return "\n".join(md)

        md.append("## Detailed Verified Findings\n")
        for idx, issue in enumerate(report.issues, 1):
            cwe_str = f" | **CWE:** `{issue.cwe_id}`" if issue.cwe_id else ""
            md.append(f"### {idx}. [{issue.severity.value}] {issue.title}")
            md.append(f"- **Location:** `{issue.file_path}:{issue.line_number or 'N/A'}`{cwe_str}")
            md.append(f"- **Category:** {issue.category}")
            md.append(f"- **Description:** {issue.description}")
            if issue.suggestion:
                md.append(f"- **Suggested Fix:** {issue.suggestion}")
            md.append("\n---")

        return "\n".join(md)
