"""Compatibility interface for the LangGraph-backed review engine."""

import asyncio
from typing import Any, Callable, Dict, List, Mapping, Optional, Set

from langgraph.checkpoint.memory import InMemorySaver

from devwatch.agents.base import AgentMetadata, BaseAgent
from devwatch.agents.synthesizer import ReportSynthesizerAgent
from devwatch.config import Config
from devwatch.models import AgentStepUpdate, CodeIssue, IssueSeverity, ReviewReport, ReviewScope
from devwatch.pipeline.context import ReviewContext, ReviewOutcome
from devwatch.providers.factory import get_provider
from devwatch.review.agents import RiskPlannerAgent, RoleReviewAgent, StrictVerifierAgent
from devwatch.review.engine import ReviewEngine
from devwatch.review.models import ReviewTask, SpecialistRole


SEVERITY_RANK = {
    IssueSeverity.CRITICAL: 4,
    IssueSeverity.HIGH: 3,
    IssueSeverity.MEDIUM: 2,
    IssueSeverity.LOW: 1,
    IssueSeverity.INFO: 1,
}


class BoundedCandidateCollector:
    """Compatibility utility retaining only the highest-severity candidates."""

    def __init__(self, max_capacity: int = 1000):
        self.max_capacity = max_capacity
        self._lock = asyncio.Lock()
        self._items: List[CodeIssue] = []
        self.evicted_count = 0

    async def add_issues(self, issues: List[CodeIssue]):
        async with self._lock:
            for issue in issues:
                if len(self._items) < self.max_capacity:
                    self._items.append(issue)
                    continue
                lowest = min(
                    range(len(self._items)),
                    key=lambda index: SEVERITY_RANK.get(self._items[index].severity, 1),
                )
                if SEVERITY_RANK.get(issue.severity, 1) > SEVERITY_RANK.get(
                    self._items[lowest].severity, 1
                ):
                    self._items[lowest] = issue
                self.evicted_count += 1

    def get_candidates(self) -> List[CodeIssue]:
        return sorted(
            self._items,
            key=lambda issue: SEVERITY_RANK.get(issue.severity, 1),
            reverse=True,
        )


class _LegacyPlannerAdapter(BaseAgent):
    def __init__(self, agent: BaseAgent):
        self.agent = agent

    @property
    def metadata(self) -> AgentMetadata:
        return self.agent.metadata

    async def execute(self, context: Dict[str, Any]) -> List[ReviewTask]:
        result = await self.agent.execute(context)
        if isinstance(result, list):
            return result
        if not isinstance(result, ReviewScope):
            raise TypeError("legacy planner must return ReviewScope")
        regions = context.get("changed_regions", [])
        valid = set(context.get("files", []))
        files = [path for path in result.files_to_review if path in valid]
        if not files:
            return []
        file_set = set(files)
        assigned_regions = [
            region for region in regions if region.file_path in file_set
        ]
        focus = "; ".join(result.focus_areas)
        return [
            ReviewTask(
                task_id="legacy-security",
                specialist=SpecialistRole.SECURITY,
                files=files,
                focus=focus or "security defects",
                changed_regions=assigned_regions,
            ),
            ReviewTask(
                task_id="legacy-correctness",
                specialist=SpecialistRole.CORRECTNESS,
                files=files,
                focus=focus or "correctness defects",
                changed_regions=assigned_regions,
            ),
        ]


class _LegacySpecialistAdapter(BaseAgent):
    def __init__(self, agent: BaseAgent):
        self.agent = agent

    @property
    def metadata(self) -> AgentMetadata:
        return self.agent.metadata

    async def execute(self, context: Dict[str, Any]) -> List[CodeIssue]:
        task = context.get("task")
        file_items = list(context.get("files", {}).items())
        findings: List[CodeIssue] = []
        seen_findings: Set[str] = set()
        batch_size = max(1, Config.MAX_CONCURRENT_FILES)
        for offset in range(0, len(file_items), batch_size):
            batch = file_items[offset : offset + batch_size]
            results = await asyncio.gather(
                *(
                    self.agent.execute(
                        {
                            "file_path": file_path,
                            "code_content": content,
                            "focus_areas": [getattr(task, "focus", "")],
                        }
                    )
                    for file_path, content in batch
                )
            )
            for result in results:
                for finding in result or []:
                    finding.ensure_identity()
                    identity = finding.finding_id or repr(finding.model_dump())
                    if identity in seen_findings:
                        continue
                    seen_findings.add(identity)
                    findings.append(finding)
                    if len(findings) >= Config.MAX_CANDIDATE_FINDINGS:
                        return findings
        return findings


class ReviewPipeline:
    """Backward-compatible facade; orchestration is owned by ReviewEngine."""

    def __init__(
        self,
        planner: Optional[BaseAgent] = None,
        security_agent: Optional[BaseAgent] = None,
        quality_agent: Optional[BaseAgent] = None,
        verifier: Optional[BaseAgent] = None,
        synthesizer: Optional[BaseAgent] = None,
        step_callback: Optional[Callable[[AgentStepUpdate], None]] = None,
        max_concurrent_files: int = 5,
    ):
        provider = get_provider()
        self.planner = planner or RiskPlannerAgent(provider=provider)
        self.security_agent = security_agent or RoleReviewAgent(
            SpecialistRole.SECURITY, provider=provider
        )
        self.quality_agent = quality_agent or RoleReviewAgent(
            SpecialistRole.CORRECTNESS, provider=provider
        )
        self.verifier = verifier or StrictVerifierAgent(provider=provider)
        self.synthesizer = synthesizer or ReportSynthesizerAgent(provider=provider)
        self.step_callback = step_callback
        self.max_concurrent_files = min(max_concurrent_files, Config.MAX_CONCURRENT_FILES)
        self._active_tasks: Set[asyncio.Task] = set()

        planner_for_graph: BaseAgent = self.planner
        if not isinstance(self.planner, RiskPlannerAgent):
            planner_for_graph = _LegacyPlannerAdapter(self.planner)
        security_for_graph: BaseAgent = self.security_agent
        if not isinstance(self.security_agent, RoleReviewAgent):
            security_for_graph = _LegacySpecialistAdapter(self.security_agent)
        quality_for_graph: BaseAgent = self.quality_agent
        if not isinstance(self.quality_agent, RoleReviewAgent):
            quality_for_graph = _LegacySpecialistAdapter(self.quality_agent)

        injected = any(
            value is not None
            for value in (planner, security_agent, quality_agent, verifier, synthesizer)
        )
        specialists: Mapping[SpecialistRole, BaseAgent] = {
            SpecialistRole.SECURITY: security_for_graph,
            SpecialistRole.ARCHITECTURE_API: RoleReviewAgent(
                SpecialistRole.ARCHITECTURE_API, provider=provider
            ),
            SpecialistRole.CORRECTNESS: quality_for_graph,
            SpecialistRole.PERFORMANCE: RoleReviewAgent(
                SpecialistRole.PERFORMANCE, provider=provider
            ),
        }
        engine_options: Dict[str, Any] = {
            "planner": planner_for_graph,
            "specialists": specialists,
            "verifier": self.verifier,
            "verification_threshold": Config.VERIFICATION_CONFIDENCE_THRESHOLD,
            "runs_dir": Config.REVIEW_RUNS_DIR,
            "run_commands": Config.REVIEW_COMMANDS_ENABLED,
        }
        if injected:
            engine_options["checkpointer"] = InMemorySaver()
        else:
            engine_options["checkpoint_path"] = Config.CHECKPOINT_DB_PATH
        self.engine = ReviewEngine(**engine_options)

    async def execute(
        self, target_path: str, context: Optional[ReviewContext] = None
    ) -> ReviewReport:
        ctx = context or ReviewContext(target_path=target_path)
        ctx.target_path = target_path
        current = asyncio.current_task()
        if current:
            self._active_tasks.add(current)
        try:
            ctx.check_cancellation()
            async with asyncio.timeout(Config.GLOBAL_REVIEW_TIMEOUT_SECONDS):
                report = await self.engine.review_repository(
                    target_path, progress_sink=self.step_callback
                )
            self._update_context(ctx, report)
            return report
        except TimeoutError as error:
            ctx.status = ReviewOutcome.FAILED
            ctx.record_failure("GLOBAL_DEADLINE", "ReviewEngine", error)
            raise TimeoutError("Global review execution deadline exceeded") from error
        except asyncio.CancelledError:
            ctx.status = ReviewOutcome.CANCELLED
            raise
        finally:
            if current:
                self._active_tasks.discard(current)

    async def arun_file_audit(self, file_path: str, code_content: str) -> ReviewReport:
        return await self.engine.review_file(
            file_path, code_content, progress_sink=self.step_callback
        )

    async def arun_files_audit(self, files: List[dict]) -> ReviewReport:
        return await self.engine.review_files(files, progress_sink=self.step_callback)

    def cancel_active_tasks(self):
        for task in list(self._active_tasks):
            if not task.done():
                task.cancel()

    @staticmethod
    def _update_context(ctx: ReviewContext, report: ReviewReport) -> None:
        failures = []
        for failure in report.metrics.get("stage_failures", []):
            failure = dict(failure)
            if failure.get("stage") == "SPECIALIST":
                failure["stage"] = {
                    "security": "SECURITY_ANALYSIS",
                    "correctness": "QUALITY_ANALYSIS",
                }.get(failure.get("component"), "SPECIALIST_ANALYSIS")
            failures.append(failure)
        ctx.stage_failures.extend(failures)
        ctx.final_issues = report.issues
        ctx.metrics.update(report.metrics)
        ctx.circuit_open = any(
            failure.get("error_type") == "CircuitBreakerOpenError"
            for failure in failures
        )
        if failures:
            ctx.status = ReviewOutcome.PARTIALLY_COMPLETED
