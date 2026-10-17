import asyncio
import contextvars
import json
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.config import get_stream_writer
from langgraph.types import Send

from devwatch.agents.base import BaseAgent
from devwatch.agents import llm
from devwatch.config import Config
from devwatch.models import (
    AgentStepUpdate,
    CodeIssue,
    IssueSeverity,
    ReviewReport,
    VerificationStatus,
    generate_evidence_fingerprint,
)
from devwatch.review.models import ChangedRegion, ReviewTask, SpecialistRole, ToolEvidence
from devwatch.review.evidence import ContextSelector, GitChangeCollector
from devwatch.review.reporting import render_report
from devwatch.review.runner import RestrictedCommandRunner, WorkspaceSnapshotter, detect_commands
from devwatch.review.state import ReviewState, SpecialistState, candidate_sort_key
from devwatch.scanner import CodebaseScanner
from devwatch.tools.static_analyzer import ASTStaticAnalyzerTool
from devwatch.tools import IssueDeduplicatorTool


ProgressSink = Callable[[AgentStepUpdate], None]


class ReviewEngine:
    """Deep module exposing review operations while hiding LangGraph mechanics."""

    def __init__(
        self,
        planner: BaseAgent,
        specialists: Mapping[SpecialistRole, BaseAgent],
        verifier: BaseAgent,
        checkpointer: Any = None,
        verification_threshold: float = 0.8,
        runs_dir: Optional[str | Path] = None,
        run_commands: bool = True,
        checkpoint_path: Optional[str | Path] = None,
    ):
        self.planner = planner
        self.specialists = dict(specialists)
        self.verifier = verifier
        self.verification_threshold = verification_threshold
        self.run_commands = run_commands
        self._llm_semaphore = asyncio.Semaphore(max(1, Config.MAX_CONCURRENT_LLM_CALLS))
        self.change_collector = GitChangeCollector()
        self.snapshotter = WorkspaceSnapshotter(
            runs_dir or Path(Config.WORKSPACE_BASE_DIR) / ".devwatch" / "runs"
        )
        self.snapshotter.prune(Config.REVIEW_ARTIFACT_RETENTION_DAYS)
        self.deduplicator = IssueDeduplicatorTool()
        self.static_analyzer = ASTStaticAnalyzerTool()
        self._progress_sink: contextvars.ContextVar[Optional[ProgressSink]] = (
            contextvars.ContextVar("devwatch_progress_sink", default=None)
        )
        self._artifact_cache: contextvars.ContextVar[Dict[str, str]] = (
            contextvars.ContextVar("devwatch_artifact_cache", default={})
        )
        self._started_at: contextvars.ContextVar[Optional[float]] = (
            contextvars.ContextVar("devwatch_started_at", default=None)
        )
        self.checkpoint_path = Path(checkpoint_path).resolve() if checkpoint_path else None
        self.graph = self._build_graph(checkpointer or InMemorySaver()) if not self.checkpoint_path else None

    async def review_repository(
        self, target_path: str, progress_sink: Optional[ProgressSink] = None,
        *, job_id: Optional[str] = None,
    ) -> ReviewReport:
        root = Path(target_path).resolve()
        scanner = CodebaseScanner(str(root))
        available_files = scanner.get_files()
        source_artifacts: Dict[str, str] = {}
        snapshot = None
        job_id = job_id or f"job_{uuid.uuid4().hex[:12]}"
        materialize_snapshot = self._requires_expanded_snapshot(root, available_files)
        manifest_files = self._manifest_files(root, available_files)
        try:
            changed_regions = self.change_collector.collect(root)
        except ValueError:
            if available_files:
                snapshot = await asyncio.to_thread(
                    self.snapshotter.create,
                    root,
                    job_id,
                    source_artifacts,
                    set(available_files),
                    materialize_snapshot,
                    None if materialize_snapshot else set(available_files) | manifest_files,
                )
            changed_regions = [
                ChangedRegion(
                    file_path=path,
                    start_line=1,
                    end_line=snapshot.line_counts.get(path, 1) if snapshot else 1,
                )
                for path in available_files
            ]
        allowed_files = set(available_files)
        changed_regions = [
            region for region in changed_regions if region.file_path in allowed_files
        ]
        if not changed_regions:
            report = ReviewReport(target_path=str(root))
            if not available_files:
                detail = "Empty repository: no reviewable source files were found."
            else:
                detail = (
                    "No reviewable Git changes were found. Staged, unstaged, "
                    "and untracked source files are all clean."
                )
            report.summary = f"# DevWatch Code Review Report\n\n{detail}\n"
            return report

        changed_files = [region.file_path for region in changed_regions]
        context_files = ContextSelector(root).select(changed_files, available_files)
        selected_files = list(dict.fromkeys(changed_files + context_files))
        if snapshot is None:
            snapshot = await asyncio.to_thread(
                self.snapshotter.create,
                root,
                job_id,
                source_artifacts,
                set(selected_files),
                materialize_snapshot,
                None if materialize_snapshot else set(selected_files) | manifest_files,
            )
        artifacts = {
            path: source_artifacts[path]
            for path in selected_files
            if path in source_artifacts
        }
        evidence: List[ToolEvidence] = []
        if self.run_commands:
            commands = detect_commands(snapshot)
            runner = RestrictedCommandRunner(
                commands,
                timeout_seconds=Config.REVIEW_COMMAND_TIMEOUT_SECONDS,
                max_output_bytes=Config.REVIEW_COMMAND_MAX_OUTPUT_BYTES,
            )
            for command in commands:
                evidence.append(await asyncio.to_thread(runner.run, snapshot, command))
        static_findings = await self._static_findings(artifacts, changed_files)
        return await self._invoke(
            job_id=job_id,
            target_path=str(root),
            artifact_path=snapshot.artifact_path,
            artifact_files=selected_files,
            artifact_hashes={
                path: snapshot.content_hashes[path]
                for path in selected_files
                if path in snapshot.content_hashes
            },
            changed_regions=changed_regions,
            tool_evidence=evidence,
            progress_sink=progress_sink,
            initial_candidates=static_findings,
            runtime_artifacts=artifacts,
        )

    async def review_file(
        self,
        file_path: str,
        content: str,
        progress_sink: Optional[ProgressSink] = None,
        *, job_id: Optional[str] = None,
    ) -> ReviewReport:
        return await self.review_files(
            [{"file_path": file_path, "content": content}], progress_sink=progress_sink,
            job_id=job_id,
        )

    async def review_files(
        self,
        files: Iterable[Dict[str, str]],
        progress_sink: Optional[ProgressSink] = None,
        *, job_id: Optional[str] = None,
    ) -> ReviewReport:
        artifacts = {
            item.get("file_path", "file.txt"): item.get("content", "") for item in files
        }
        job_id = job_id or f"job_{uuid.uuid4().hex[:12]}"
        snapshot = await asyncio.to_thread(
            self.snapshotter.create_from_files, artifacts, job_id
        )
        target_path = next(iter(artifacts), "uploaded_workspace")
        if len(artifacts) != 1:
            target_path = "uploaded_workspace"
        return await self._invoke(
            job_id=job_id,
            target_path=target_path,
            artifact_path=snapshot.artifact_path,
            artifact_files=snapshot.files,
            artifact_hashes=snapshot.content_hashes,
            changed_regions=[
                ChangedRegion(
                    file_path=path,
                    start_line=1,
                    end_line=max(1, len(content.splitlines())),
                )
                for path, content in artifacts.items()
            ],
            tool_evidence=[],
            progress_sink=progress_sink,
            initial_candidates=await self._static_findings(artifacts, list(artifacts)),
            runtime_artifacts=artifacts,
        )

    async def resume_job(
        self, job_id: str, progress_sink: Optional[ProgressSink] = None
    ) -> ReviewReport:
        """Resume the last durable graph checkpoint for a previously started job."""
        if not job_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in job_id):
            raise ValueError("job_id contains invalid characters")
        if not self.checkpoint_path or not self.checkpoint_path.is_file():
            raise ValueError("a durable checkpoint is required to resume a job")
        config = {"configurable": {"thread_id": job_id}}
        token = self._progress_sink.set(progress_sink)
        started_token = self._started_at.set(time.perf_counter())
        job_token = llm.set_current_job(job_id)
        try:
            async with AsyncSqliteSaver.from_conn_string(str(self.checkpoint_path)) as saver:
                await saver.setup()
                graph = self._build_graph(saver)
                checkpoint = await graph.aget_state(config)
                state = checkpoint.values
                if not state or state.get("job_id") != job_id:
                    raise ValueError(f"no checkpoint exists for {job_id}")
                artifact = Path(state["artifact_path"]).resolve()
                if artifact.parent != self.snapshotter.runs_dir or not artifact.is_dir():
                    raise ValueError("run artifacts are unavailable for this job")
                if state.get("report"):
                    return state["report"]
                return await self._stream_graph(graph, None, config)
        finally:
            llm.reset_current_job(job_token)
            self._started_at.reset(started_token)
            self._progress_sink.reset(token)

    async def _invoke(
        self,
        job_id: str,
        target_path: str,
        artifact_path: str,
        artifact_files: List[str],
        artifact_hashes: Dict[str, str],
        changed_regions: List[ChangedRegion],
        tool_evidence: List[ToolEvidence],
        progress_sink: Optional[ProgressSink],
        initial_candidates: Optional[List[CodeIssue]] = None,
        runtime_artifacts: Optional[Dict[str, str]] = None,
    ) -> ReviewReport:
        token = self._progress_sink.set(progress_sink)
        artifact_token = self._artifact_cache.set(runtime_artifacts or {})
        started_token = self._started_at.set(time.perf_counter())
        job_token = llm.set_current_job(job_id)
        try:
            graph_input = {
                    "job_id": job_id,
                    "target_path": target_path,
                    "artifact_path": artifact_path,
                    "artifact_files": artifact_files,
                    "artifact_hashes": artifact_hashes,
                    "changed_regions": changed_regions,
                    "tool_evidence": tool_evidence,
                    "candidate_findings": [
                        issue.model_copy(update={"code_snippet": None})
                        for issue in (initial_candidates or [])
                    ],
                    "failures": [],
                }
            graph_config = {"configurable": {"thread_id": job_id}}
            if self.checkpoint_path:
                self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
                async with AsyncSqliteSaver.from_conn_string(str(self.checkpoint_path)) as saver:
                    await saver.setup()
                    return await self._stream_graph(self._build_graph(saver), graph_input, graph_config)
            else:
                return await self._stream_graph(self.graph, graph_input, graph_config)
        finally:
            llm.reset_current_job(job_token)
            self._started_at.reset(started_token)
            self._artifact_cache.reset(artifact_token)
            self._progress_sink.reset(token)

    async def _stream_graph(self, graph: Any, graph_input: Any, config: Dict[str, Any]) -> ReviewReport:
        if self._progress_sink.get() is None:
            result = await graph.ainvoke(graph_input, config)
            return result["report"]
        async for event in graph.astream(
            graph_input, config, stream_mode=["updates", "custom"], version="v2",
            durability="sync",
        ):
            sink = self._progress_sink.get()
            if sink is None:
                continue
            if event["type"] == "custom" and event["data"].get("type") == "agent_update":
                sink(AgentStepUpdate.model_validate(event["data"]))
            elif event["type"] == "updates":
                for node, update in event["data"].items():
                    if node == "__interrupt__":
                        continue
                    tool_results = []
                    if node == "plan_review" and graph_input:
                        tool_results = [item.model_dump(mode="json") for item in graph_input.get("tool_evidence", [])]
                    self._notify(node, "COMPLETED", f"{node} completed", tool_results=tool_results)
        checkpoint = await graph.aget_state(config)
        report = checkpoint.values.get("report")
        if report is None:
            raise RuntimeError("review graph stopped before rendering a report")
        return report

    def _build_graph(self, checkpointer: Any):
        builder = StateGraph(ReviewState)
        builder.add_node("plan_review", self._plan_review)
        builder.add_node("run_specialist", self._run_specialist)
        builder.add_node("deduplicate", self._deduplicate)
        builder.add_node("verify", self._verify)
        builder.add_node("strict_gate", self._strict_gate)
        builder.add_node("render_report", self._render_report)
        builder.add_edge(START, "plan_review")
        builder.add_conditional_edges("plan_review", self._dispatch_tasks)
        builder.add_edge("run_specialist", "deduplicate")
        builder.add_edge("deduplicate", "verify")
        builder.add_edge("verify", "strict_gate")
        builder.add_edge("strict_gate", "render_report")
        builder.add_edge("render_report", END)
        return builder.compile(checkpointer=checkpointer)

    async def _plan_review(self, state: ReviewState) -> Dict[str, Any]:
        self._notify("Planner Agent", "RUNNING", "Routing changed code to specialists")
        usage: Dict[str, int] = {}
        try:
            with llm.usage_tracking() as usage:
                async with self._llm_semaphore:
                    tasks = await self.planner.execute(
                        {
                            "target_path": state["target_path"],
                            "files": [region.file_path for region in state.get("changed_regions", [])],
                            "changed_regions": state.get("changed_regions", []),
                            "tool_evidence": state.get("tool_evidence", []),
                            "candidate_findings": state.get("candidate_findings", []),
                        }
                    )
            validated = [task if isinstance(task, ReviewTask) else ReviewTask.model_validate(task) for task in tasks]
            target_files = {region.file_path for region in state.get("changed_regions", [])}
            context_files = [
                path for path in state.get("artifact_files", []) if path not in target_files
            ]
            by_role: Dict[SpecialistRole, ReviewTask] = {}
            for task in validated:
                assigned = sorted(set(task.files) & target_files)
                if not assigned:
                    continue
                if task.specialist in by_role:
                    prior = by_role[task.specialist]
                    prior.files = sorted(set(prior.files) | set(assigned))
                else:
                    by_role[task.specialist] = task.model_copy(
                        deep=True,
                        update={
                            "files": assigned,
                            "context_files": sorted(set(task.context_files) & set(context_files)),
                            "focus": task.focus[:500],
                        },
                    )
            normalized = []
            for role in SpecialistRole:
                task = by_role.get(role)
                if task:
                    task.context_files = sorted(set(task.context_files) | set(context_files))
                    task.changed_regions = [
                        region for region in state.get("changed_regions", [])
                        if region.file_path in task.files
                    ]
                    normalized.append(task)
            self._notify("Planner Agent", "COMPLETED", f"Created {len(normalized)} specialist tasks", token_usage=usage)
            return {"review_tasks": normalized}
        except Exception as error:
            self._notify("Planner Agent", "FAILED", str(error), token_usage=usage)
            return {"review_tasks": [], "failures": [self._failure("PLANNING", "planner", error)]}

    def _dispatch_tasks(self, state: ReviewState):
        tasks = state.get("review_tasks", [])
        if not tasks:
            return "deduplicate"
        return [
            Send(
                "run_specialist",
                {
                    "task": task,
                    "artifact_path": state["artifact_path"],
                    "artifact_files": state.get("artifact_files", []),
                    "tool_evidence": state.get("tool_evidence", []),
                    "candidate_findings": [],
                    "failures": [],
                },
            )
            for task in tasks
        ]

    async def _run_specialist(self, state: SpecialistState) -> Dict[str, Any]:
        task = state["task"]
        agent = self.specialists.get(task.specialist)
        if agent is None:
            error = ValueError(f"no specialist registered for {task.specialist.value}")
            return {"failures": [self._failure("SPECIALIST", task.specialist.value, error)]}
        self._notify(task.specialist.value, "RUNNING", task.focus)
        usage: Dict[str, int] = {}
        try:
            with llm.usage_tracking() as usage:
                async with self._llm_semaphore:
                    result = await agent.execute(
                        {
                            "task": task,
                            "files": {
                                path: self._read_artifact(state["artifact_path"], path)
                                for path in task.files
                            },
                            "context_files": {
                                path: self._read_artifact(state["artifact_path"], path)
                                for path in task.context_files
                            },
                            "tool_evidence": state.get("tool_evidence", []),
                        }
                    )
            findings = [
                (issue if isinstance(issue, CodeIssue) else CodeIssue.model_validate(issue)).model_copy(deep=True)
                for issue in (result or [])
            ]
            findings = [
                finding for finding in findings
                if finding.file_path in task.files
                and (
                    not finding.code_snippet
                    or finding.evidence_fingerprint == generate_evidence_fingerprint(finding.code_snippet)
                )
            ]
            for finding in findings:
                finding.source_type = "agent"
                finding.evidence = []
                finding.code_snippet = None
                finding.specialist = finding.specialist or task.specialist.value
                finding.agent_id = finding.agent_id or task.specialist.value
                finding.ensure_identity()
            self._notify(task.specialist.value, "COMPLETED", f"Produced {len(findings)} candidates", token_usage=usage)
            return {"candidate_findings": findings}
        except Exception as error:
            self._notify(task.specialist.value, "FAILED", str(error), token_usage=usage)
            return {"failures": [self._failure("SPECIALIST", task.specialist.value, error)]}

    def _deduplicate(self, state: ReviewState) -> Dict[str, Any]:
        candidates = sorted(
            state.get("candidate_findings", []), key=candidate_sort_key,
        )[: Config.MAX_CANDIDATE_FINDINGS]
        return {"deduped_findings": self.deduplicator._run(candidates)}

    async def _verify(self, state: ReviewState) -> Dict[str, Any]:
        candidates = state.get("deduped_findings", [])
        self._notify("Verification Agent", "RUNNING", f"Verifying {len(candidates)} candidates")
        if not candidates:
            self._notify("Verification Agent", "COMPLETED", "No candidates required verification")
            return {"verified_findings": []}
        deterministic = [
            issue for issue in candidates if self._is_conclusive_tool_finding(issue)
        ]
        candidates_to_verify = [
            issue for issue in candidates if not self._is_conclusive_tool_finding(issue)
        ]
        if not candidates_to_verify:
            self._notify(
                "Verification Agent",
                "COMPLETED",
                f"Accepted {len(deterministic)} conclusive tool findings",
            )
            return {"verified_findings": deterministic}
        verified: List[CodeIssue] = list(deterministic)
        grouped: Dict[str, List[CodeIssue]] = defaultdict(list)
        for issue in candidates_to_verify:
            grouped[issue.file_path].append(issue)
        failures = []
        for file_path in sorted(grouped):
            issues = grouped[file_path]
            usage: Dict[str, int] = {}
            try:
                with llm.usage_tracking() as usage:
                    async with self._llm_semaphore:
                        result = await self.verifier.execute(
                            {
                                "file_path": file_path,
                                "code_content": self._read_artifact(
                                    state["artifact_path"], file_path
                                ),
                                "issues": issues,
                            }
                        )
                if not isinstance(result, list):
                    raise TypeError("verifier must return a list of findings")
                originals = {issue.finding_id: issue for issue in issues}
                seen_decisions = set()
                for item in result:
                    decision = item if isinstance(item, CodeIssue) else CodeIssue.model_validate(item)
                    original = originals.get(decision.finding_id)
                    if original is not None and decision.finding_id not in seen_decisions:
                        seen_decisions.add(decision.finding_id)
                        verified.append(original.model_copy(update={
                            "verification_status": decision.verification_status,
                            "verification_confidence": decision.verification_confidence,
                            "verification_rationale": decision.verification_rationale,
                        }))
            except Exception as error:
                failures.append(self._failure("VERIFICATION", file_path, error))
                self._notify("Verification Agent", "FAILED", f"{file_path}: {error}", token_usage=usage)
            else:
                self._notify("Verification Agent", "COMPLETED", f"Verified {file_path}", token_usage=usage)
        self._notify("Verification Agent", "COMPLETED", f"Verified {len(verified)} candidates")
        return {"verified_findings": verified, "failures": failures}

    def _strict_gate(self, state: ReviewState) -> Dict[str, Any]:
        confirmed: List[CodeIssue] = []
        manual: List[CodeIssue] = []
        for issue in state.get("verified_findings", []):
            if not self._has_valid_evidence(issue, state["artifact_path"]):
                continue
            confidence = issue.verification_confidence
            if (
                issue.verification_status == VerificationStatus.ACCEPTED
                and confidence is not None
                and confidence >= self.verification_threshold
            ):
                confirmed.append(issue)
            elif (
                issue.verification_status
                in (VerificationStatus.UNCERTAIN, VerificationStatus.NEEDS_HUMAN_REVIEW)
                and issue.severity in (IssueSeverity.CRITICAL, IssueSeverity.HIGH)
            ):
                manual.append(issue)
        return {"confirmed_findings": confirmed, "manual_review_candidates": manual}

    def _render_report(self, state: ReviewState) -> Dict[str, Any]:
        report = ReviewReport(
            target_path=state["target_path"],
            issues=state.get("confirmed_findings", []),
            manual_review_candidates=state.get("manual_review_candidates", []),
            metrics={
                "specialist_tasks": len(state.get("review_tasks", [])),
                "candidate_findings": len(state.get("candidate_findings", [])),
                "confirmed_findings": len(state.get("confirmed_findings", [])),
                "suppressed_findings": max(
                    0,
                    len(state.get("candidate_findings", []))
                    - len(state.get("confirmed_findings", [])),
                ),
                "stage_failures": state.get("failures", []),
                "partial": bool(state.get("failures")),
            },
        )
        report.summary = render_report(report, partial=bool(state.get("failures")))
        self._notify(
            "Report Renderer",
            "COMPLETED",
            f"Reported {report.total_issues} confirmed findings",
            suppressed_finding_count=report.metrics["suppressed_findings"],
        )
        return {"report": report}

    def _has_valid_evidence(self, issue: CodeIssue, artifact_path: str) -> bool:
        try:
            content = self._read_artifact(artifact_path, issue.file_path)
        except (OSError, ValueError):
            return False
        lines = content.splitlines()
        start = issue.start_line or issue.line_number
        end = issue.end_line or issue.line_number
        if not start or not end or start < 1 or end < start or end > len(lines):
            return False
        if issue.line_number is not None and not start <= issue.line_number <= end:
            return False
        source = "\n".join(lines[start - 1:end])
        source_hash = generate_evidence_fingerprint(source)
        if issue.source_type == "static":
            return any(
                item.get("source") == "ASTStaticAnalyzerTool"
                and item.get("conclusive") is True
                and item.get("source_hash") == source_hash
                for item in issue.evidence
            )
        return issue.source_type == "agent" and issue.evidence_fingerprint == source_hash

    def _read_artifact(self, artifact_path: str, file_path: str) -> str:
        cached = self._artifact_cache.get().get(file_path)
        if cached is not None:
            return cached
        root = Path(artifact_path).resolve()
        candidate = (root / file_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise ValueError("artifact path escaped the run directory") from error
        if not candidate.is_file() or candidate.is_symlink():
            bundle_path = root / "artifacts.bin"
            index_path = root / "artifacts.index.json"
            if not bundle_path.is_file() or not index_path.is_file():
                raise ValueError(f"artifact does not exist: {file_path}")
            try:
                index = json.loads(index_path.read_text(encoding="utf-8"))
                offset, length = index[file_path]
                with bundle_path.open("rb") as bundle:
                    bundle.seek(offset)
                    return bundle.read(length).decode("utf-8", errors="ignore")
            except (KeyError, ValueError, OSError, json.JSONDecodeError) as error:
                raise ValueError(f"artifact does not exist: {file_path}") from error
        return candidate.read_text(encoding="utf-8", errors="ignore")

    def _requires_expanded_snapshot(
        self, root: Path, available_files: List[str]
    ) -> bool:
        if not self.run_commands:
            return False
        if (root / ".devwatch.toml").is_file():
            return True
        if (root / "pyproject.toml").is_file():
            return True
        for file_path in available_files:
            if Path(file_path).name != "package.json":
                continue
            try:
                package = json.loads(
                    (root / file_path).read_text(encoding="utf-8", errors="ignore")
                )
            except (OSError, json.JSONDecodeError):
                continue
            if package.get("scripts", {}).get("test"):
                return True
        return False

    @staticmethod
    def _manifest_files(root: Path, available_files: List[str]) -> set[str]:
        manifests = {
            path for path in available_files if Path(path).name == "package.json"
        }
        if (root / "pyproject.toml").is_file():
            manifests.add("pyproject.toml")
        if (root / ".devwatch.toml").is_file():
            manifests.add(".devwatch.toml")
        return manifests

    @staticmethod
    def _is_conclusive_tool_finding(issue: CodeIssue) -> bool:
        return issue.source_type == "static" and any(
            item.get("source") == "ASTStaticAnalyzerTool"
            and item.get("conclusive") is True
            for item in issue.evidence
        )

    @staticmethod
    def _failure(stage: str, component: str, error: Exception) -> Dict[str, Any]:
        return {
            "stage": stage,
            "component": component,
            "error_type": type(error).__name__,
            "error_message": str(error),
        }

    def _notify(
        self,
        agent_name: str,
        status: str,
        message: str,
        suppressed_finding_count: Optional[int] = None,
        tool_results: Optional[List[Dict[str, Any]]] = None,
        token_usage: Optional[Dict[str, int]] = None,
    ) -> None:
        started_at = self._started_at.get()
        update = AgentStepUpdate(
            agent_name=agent_name,
            status=status,
            message=message,
            timestamp=time.time(),
            elapsed_ms=(time.perf_counter() - started_at) * 1000 if started_at else None,
            specialist=agent_name if agent_name in {role.value for role in SpecialistRole} else None,
            suppressed_finding_count=suppressed_finding_count,
            tool_results=tool_results or [],
            token_usage=token_usage or {},
        )
        sink = self._progress_sink.get()
        try:
            writer = get_stream_writer()
            writer({"type": "agent_update", **update.model_dump()})
        except RuntimeError:
            if sink:
                sink(update)

    async def _static_findings(
        self, artifacts: Dict[str, str], target_files: List[str]
    ) -> List[CodeIssue]:
        conclusive_titles = {
            "Hardcoded Secret Credential",
            "Dynamic Code Execution via eval()",
            "Dynamic Code Execution via exec()",
            "Bare Except Swallowing Exception",
        }
        def analyze_all() -> List[CodeIssue]:
            analyzed_findings: List[CodeIssue] = []
            for file_path in target_files:
                content = artifacts.get(file_path, "")
                if content.strip():
                    analyzed_findings.extend(
                        self.static_analyzer.analyze_file(file_path, content)
                    )
            return analyzed_findings

        findings: List[CodeIssue] = []
        for issue in await asyncio.to_thread(analyze_all):
            conclusive = issue.title in conclusive_titles
            source_lines = artifacts[issue.file_path].splitlines()
            source_range = "\n".join(source_lines[
                (issue.start_line or issue.line_number or 1) - 1:
                (issue.end_line or issue.line_number or 1)
            ])
            issue.source_type = "static"
            issue.specialist = issue.specialist or "deterministic_static_analysis"
            issue.evidence = [
                {
                    "source": "ASTStaticAnalyzerTool",
                    "summary": issue.title,
                    "conclusive": conclusive,
                    "source_hash": generate_evidence_fingerprint(source_range),
                }
            ]
            if conclusive:
                issue.verification_status = VerificationStatus.ACCEPTED
                issue.verification_confidence = 1.0
            issue.ensure_identity()
            findings.append(issue)
        return findings
