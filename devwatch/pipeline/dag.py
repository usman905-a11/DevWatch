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
from devwatch.chunker import SemanticCodeChunker
from devwatch.cache import IsolatedResponseCache


from devwatch.providers.exceptions import (
    ProviderError,
    CircuitBreakerOpenError,
    ProviderQuotaExhaustedError,
    ProviderAuthenticationError,
    ProviderAuthorizationError,
    ProviderConfigurationError,
)

logger = logging.getLogger("devwatch.pipeline.dag")




SEVERITY_RANK = {
    IssueSeverity.CRITICAL: 4,
    IssueSeverity.HIGH: 3,
    IssueSeverity.MEDIUM: 2,
    IssueSeverity.LOW: 1,
    IssueSeverity.INFO: 1,
}


class BoundedCandidateCollector:
    """Thread-safe incremental candidate finding collection bounded to max_capacity.
    Evicts lowest-severity findings immediately when max_capacity is exceeded to ensure flat memory usage.
    """
    def __init__(self, max_capacity: int = 1000):
        self.max_capacity = max_capacity
        self._lock = asyncio.Lock()
        self._items: List[CodeIssue] = []
        self.evicted_count: int = 0

    async def add_issues(self, issues: List[CodeIssue]):
        if not issues:
            return
        async with self._lock:
            for issue in issues:
                if len(self._items) < self.max_capacity:
                    self._items.append(issue)
                else:
                    min_idx = 0
                    min_rank = SEVERITY_RANK.get(self._items[0].severity, 1)
                    for idx, existing in enumerate(self._items[1:], 1):
                        rank = SEVERITY_RANK.get(existing.severity, 1)
                        if rank < min_rank:
                            min_rank = rank
                            min_idx = idx

                    incoming_rank = SEVERITY_RANK.get(issue.severity, 1)
                    if incoming_rank > min_rank:
                        self._items[min_idx] = issue
                        self.evicted_count += 1
                    else:
                        self.evicted_count += 1

    def get_candidates(self) -> List[CodeIssue]:
        return sorted(self._items, key=lambda x: SEVERITY_RANK.get(x.severity, 1), reverse=True)


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
        self.chunker = SemanticCodeChunker()
        self.response_cache = IsolatedResponseCache()
        self.step_callback = step_callback
        self.max_concurrent_files = min(max_concurrent_files, Config.MAX_CONCURRENT_FILES)
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
            ctx.selected_files = scope.files_to_review[:Config.MAX_FILES_PER_REVIEW]
        except Exception as err:
            logger.warning(f"Planner Agent failed: {err}. Falling back to default scope.")
            ctx.record_failure("PLANNING", "PlannerAgent", err)
            ctx.selected_files = all_files[:min(20, Config.MAX_FILES_PER_REVIEW)]
            ctx.scope = ReviewScope(
                target_path=target_path,
                files_to_review=ctx.selected_files,
                focus_areas=["OWASP Security Vulnerabilities", "Unhandled Exceptions & Logic Flaws"],
            )

        self._notify("Planner Agent", "COMPLETED", f"Scope planned: {len(ctx.selected_files)} files")

        # Stage 3: Isolated Parallel Audit (Security & Quality per file/chunk) with Bounded Collection
        ctx.check_cancellation()
        semaphore = asyncio.Semaphore(self.max_concurrent_files)
        collector = BoundedCandidateCollector(max_capacity=Config.MAX_CANDIDATE_FINDINGS)

        async def analyze_single_file(rel_path: str):
            async with semaphore:
                file_issues: List[CodeIssue] = []
                code = ""
                try:
                    code = await asyncio.to_thread(scanner.read_file, rel_path)
                except Exception as err:
                    logger.error(f"Failed to read file {rel_path}: {err}")
                    ctx.record_failure("FILE_READ", rel_path, err)
                    ctx.skipped_files.append(rel_path)
                    return

                if not code.strip():
                    return

                # Static analysis (AST, pattern, logic) - ALWAYS runs deterministically
                try:
                    ast_issues = await asyncio.to_thread(self.ast_analyzer_tool.analyze_file, rel_path, code)
                    file_issues.extend(ast_issues)
                except Exception as err:
                    ctx.record_failure("STATIC_AST", rel_path, err)

                # Stop scheduling new LLM tasks if shared circuit breaker is OPEN
                if ctx.circuit_open:
                    logger.warning(f"Skipping LLM analysis for {rel_path} because provider circuit is OPEN")
                    await collector.add_issues(file_issues)
                    return

                # Semantic Code Chunking if file is large (> 200 lines or > 20,000 bytes)
                chunks = self.chunker.chunk_file(rel_path, code, max_tokens=1500)
                if len(chunks) > 1:
                    ctx.chunked_inputs.append({"file_path": rel_path, "num_chunks": len(chunks)})

                for chunk in chunks:
                    if ctx.circuit_open:
                        break

                    sec_coro = self.security_agent.execute({
                        "file_path": rel_path,
                        "code_content": chunk.content,
                        "start_line": chunk.start_line,
                        "end_line": chunk.end_line,
                        "focus_areas": ctx.scope.focus_areas if ctx.scope else [],
                    })
                    qual_coro = self.quality_agent.execute({
                        "file_path": rel_path,
                        "code_content": chunk.content,
                        "start_line": chunk.start_line,
                        "end_line": chunk.end_line,
                        "focus_areas": ctx.scope.focus_areas if ctx.scope else [],
                    })

                    results = await asyncio.gather(sec_coro, qual_coro, return_exceptions=True)
                    sec_res = results[0]
                    qual_res = results[1]

                    for res, agent_name in [(sec_res, "SECURITY_ANALYSIS"), (qual_res, "QUALITY_ANALYSIS")]:
                        if isinstance(res, (CircuitBreakerOpenError, ProviderQuotaExhaustedError, ProviderAuthenticationError, ProviderAuthorizationError, ProviderConfigurationError)):
                            logger.error(f"Non-retryable provider failure [{type(res).__name__}] in {agent_name} for {rel_path}. Opening circuit flag.")
                            ctx.circuit_open = True
                            ctx.record_failure(agent_name, rel_path, res)
                        elif isinstance(res, Exception):
                            logger.warning(f"{agent_name} agent failed for {rel_path}: {res}")
                            ctx.record_failure(agent_name, rel_path, res)
                        elif isinstance(res, list):
                            file_issues.extend(res)

                # Incrementally add findings to bounded candidate collector
                await collector.add_issues(file_issues)

        file_tasks = [asyncio.create_task(analyze_single_file(f)) for f in ctx.selected_files]
        for t in file_tasks:
            self._active_tasks.add(t)

        try:
            if file_tasks:
                task_results = await asyncio.gather(*file_tasks, return_exceptions=True)
                for res in task_results:
                    if isinstance(res, asyncio.CancelledError):
                        self.cancel_active_tasks()
                        raise res
                    elif isinstance(res, Exception):
                        ctx.record_failure("PARALLEL_AUDIT", "file_task", res)
        finally:
            for t in file_tasks:
                self._active_tasks.discard(t)

        raw_candidates = collector.get_candidates()
        if collector.evicted_count > 0:
            logger.info(
                f"Candidate collection truncated: showing top {len(raw_candidates)} findings "
                f"({collector.evicted_count} lower-severity findings evicted)."
            )

        # Stage 4: Deduplication
        ctx.check_cancellation()
        self._notify("Synthesizer Agent", "RUNNING", "Deduplicating & normalizing candidate findings")
        try:
            deduped_issues = await asyncio.to_thread(self.deduplicator._run, raw_candidates)
        except Exception as err:
            logger.warning(f"Deduplication failed: {err}. Using raw candidates.")
            ctx.record_failure("DEDUPLICATION", "IssueDeduplicatorTool", err)
            deduped_issues = raw_candidates

        # Stage 5: Bounded Parallel Verification with Stale Finding Filtering
        ctx.check_cancellation()
        self._notify("Verification Agent", "RUNNING", "Verifying candidate findings against source code")
        verified_issues: List[CodeIssue] = []

        if deduped_issues:
            file_groups: Dict[str, List[CodeIssue]] = {}
            for issue in deduped_issues:
                file_groups.setdefault(issue.file_path, []).append(issue)

            v_semaphore = asyncio.Semaphore(self.max_concurrent_files)

            async def verify_single_file_group(rel_path: str, group_issues: List[CodeIssue]) -> List[CodeIssue]:
                async with v_semaphore:
                    try:
                        code = await asyncio.to_thread(scanner.read_file, rel_path)
                    except Exception as err:
                        logger.error(f"Failed to read file {rel_path} for verification: {err}")
                        return group_issues

                    # Item 8: Drop stale findings whose line number exceeds total file lines
                    file_lines = len(code.splitlines()) if code else 0
                    valid_group_issues = []
                    for issue in group_issues:
                        line_num = issue.line_number or issue.start_line or 1
                        if file_lines > 0 and line_num > file_lines:
                            logger.info(f"Dropping stale finding '{issue.title}' at line {line_num} (exceeds file {rel_path} line count {file_lines})")
                            continue
                        valid_group_issues.append(issue)

                    if not valid_group_issues:
                        return []

                    if ctx.circuit_open:
                        logger.warning(f"Circuit OPEN: Retaining candidate findings for {rel_path} without LLM verification")
                        return valid_group_issues

                    try:
                        v_res = await self.verifier.execute({
                            "file_path": rel_path,
                            "code_content": code,
                            "issues": valid_group_issues,
                        })
                        if isinstance(v_res, list):
                            return [
                                i for i in v_res
                                if not (file_lines > 0 and (i.line_number or i.start_line or 1) > file_lines)
                            ]
                        return valid_group_issues
                    except (CircuitBreakerOpenError, ProviderQuotaExhaustedError, ProviderAuthenticationError, ProviderAuthorizationError, ProviderConfigurationError) as err:
                        ctx.circuit_open = True
                        logger.warning(f"Verification Agent circuit open for {rel_path}: {err}. Retaining candidate issues.")
                        ctx.record_failure("VERIFICATION", rel_path, err)
                        return valid_group_issues
                    except Exception as err:
                        logger.warning(f"Verification Agent failed for {rel_path}: {err}. Retaining candidate issues.")
                        ctx.record_failure("VERIFICATION", rel_path, err)
                        return valid_group_issues

            v_tasks = [
                asyncio.create_task(verify_single_file_group(path, issues))
                for path, issues in file_groups.items()
            ]
            for t in v_tasks:
                self._active_tasks.add(t)

            try:
                if v_tasks:
                    v_results = await asyncio.gather(*v_tasks, return_exceptions=True)
                    for res in v_results:
                        if isinstance(res, list):
                            verified_issues.extend(res)
                        elif isinstance(res, Exception):
                            ctx.record_failure("VERIFICATION", "group_task", res)
            finally:
                for t in v_tasks:
                    self._active_tasks.discard(t)

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
