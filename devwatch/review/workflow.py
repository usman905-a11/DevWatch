"""Canonical seven-agent LangGraph execution consumed by DurableJobManager.

One executor owns the shared model semaphore. Job accounting/events remain in
their stores; graph/private-state checkpoints are separate. This workflow never
invokes legacy engines, mutates reviewed source or publishes an LLM-selected file.
"""

import asyncio
from contextlib import closing
from hashlib import sha256
import json
import sqlite3
from pathlib import PurePosixPath
from typing import Any, TypedDict

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from devwatch.review.budgets import BudgetManager
from devwatch.review.contracts import (
    AgentId, AgentPrivateState, AgentWorkItem, ReviewPlan, ReviewTask, SpecialistResult,
    VerificationPhaseResult, VerificationSynthesisResult, VerificationDecision, ReportDraft,
)
from devwatch.review.finalization import FinalAcceptanceGate, FinalizationWorkflow, assemble_report, render_accepted_report
from devwatch.review.pdf import render_accepted_pdf_async
from devwatch.review.jobs import EventStore, JobConflict, JobRecord, JobStore, _SQLiteStore, safe_stop_reason
from devwatch.review.repository import RepositoryContext, SharedBlackboard, StructuralEvidenceGate
from devwatch.review.stores import ArtifactStore, RepoCache, StoreLayout
from devwatch.review.subgraphs import AgentSubgraphs
from devwatch.review.tool_runtime import TrustedToolRuntime
from devwatch.review.database_tools import DatabaseTools
from devwatch.review.verification import validate_decision, validate_relations


class ReviewExecutionError(RuntimeError):
    """A mandatory agent did not produce an acceptable structured result."""


def _serializable(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _serializable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serializable(item) for item in value]
    return value


class AgentCheckpoints(_SQLiteStore):
    """Versioned private progress alongside LangGraph checkpoints, never job state."""
    def __init__(self, path):
        super().__init__(path, """CREATE TABLE IF NOT EXISTS agent_progress (
            thread_id TEXT NOT NULL, task_id TEXT NOT NULL, version TEXT NOT NULL,
            generation INTEGER NOT NULL, state TEXT NOT NULL, PRIMARY KEY(thread_id, task_id));""")

    def save(self, thread_id: str, state, generation: int):
        serialized = json.dumps(_serializable(state), sort_keys=True, allow_nan=False)
        with self._transaction() as db:
            db.execute("INSERT INTO agent_progress VALUES(?,?,?,?,?) ON CONFLICT(thread_id,task_id) "
                       "DO UPDATE SET generation=excluded.generation,state=excluded.state",
                       (thread_id, state["task"].task_id, "seven-agent-v1", generation, serialized))

    def load(self, thread_id: str, task_id: str):
        # WAL readers must not claim a writer lock while the async graph saver
        # is committing on the same event loop.
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT version,generation,state FROM agent_progress WHERE thread_id=? AND task_id=?",
                             (thread_id, task_id)).fetchone()
        if row is None:
            return None
        if row["version"] != "seven-agent-v1":
            raise ReviewExecutionError("checkpoint version requires migration")
        return {"generation": row["generation"], "state": json.loads(row["state"])}


class ReviewGraphState(TypedDict, total=False):
    snapshot_id: str
    intelligence: dict[str, Any]
    deterministic_signals: dict[str, Any]
    change_analysis: dict[str, Any]
    plan: dict[str, Any]
    tasks: list[dict[str, Any]]
    results: list[dict[str, Any]]
    rendered: dict[str, str]


class CanonicalReviewExecutor:
    def __init__(self, layout: StoreLayout, artifacts: ArtifactStore, cache: RepoCache,
                 jobs: JobStore, events: EventStore, provider, *, models, trusted_commands=(), databases=()):
        self.layout, self.artifacts, self.cache = layout, artifacts, cache
        self.jobs, self.events, self.provider, self.models = jobs, events, provider, dict(models)
        self.checkpoints = AgentCheckpoints(layout.checkpoints)
        self.model_slots = asyncio.Semaphore(3)
        self.trusted_commands = tuple(trusted_commands)
        self.databases = tuple(databases)

    async def render_report(self, job, accepted):
        rendered = render_accepted_report(accepted)
        data = await render_accepted_pdf_async(accepted)
        # Publication happens only after successful, drained rendering. There is
        # no await between the cancellation check and the bounded atomic write.
        if asyncio.current_task().cancelling():
            raise asyncio.CancelledError
        with self.jobs.publication(job.job_id, owner=job.owner):
            reference = self.artifacts.put_report_pdf(job.job_id, job.request["snapshot_id"], owner=job.owner, data=data)
        return {**rendered, "pdf_artifact": reference}

    def reconcile_models(self, job, budget):
        pending, started, cursor = dict(budget.ledger.inflight), {}, 0
        if pending:
            self.jobs.dispatch_events(self.events)
            while True:
                page = self.events.replay(job.job_id, after=cursor)
                for event in page:
                    if event.kind == "model_call_started" and event.payload.operation_id in pending:
                        started[event.payload.operation_id] = event.payload
                if not page or len(started) == len(pending):
                    break
                cursor = page[-1].sequence
        reconciled = []
        for ticket, reservation in pending.items():
            budget.record_model(ticket, prompt_tokens=reservation.tokens, completion_tokens=0)
            if ticket in started:
                reconciled.append(started[ticket].model_copy(update={"outcome": "unknown", "total_tokens": reservation.tokens}))
        # Cost settlement and its unknown-completion events share the Job Store
        # transaction/outbox. Reservations without a start never invent a call.
        self.jobs.update_ledger(job.job_id, owner=job.owner, ledger=budget.ledger, model_completions=reconciled)
        self.jobs.dispatch_events(self.events)

    async def recover_timeout(self, job: JobRecord):
        """Revalidate persisted evidence after workers drain; never call a model."""
        if job.workflow_version != "seven-agent-v1" or job.ledger.elapsed_seconds < job.limits.review_seconds:
            raise ReviewExecutionError("deadline recovery requires an exhausted canonical job")
        repository = RepositoryContext(self.artifacts, self.cache, job.request["snapshot_id"], owner=job.owner)
        budget = BudgetManager(job.limits, job.ledger.model_copy(deep=True))
        self.reconcile_models(job, budget)
        session = _ReviewSession(self, job, repository, budget, [])
        async with AsyncSqliteSaver.from_conn_string(str(self.layout.checkpoints)) as saver:
            graph = session.compile(saver)
            with tracing_context(enabled=False, parent=False):
                checkpoint = await graph.aget_state({"configurable": {"thread_id": session.thread_id}})
        raw_tasks = checkpoint.values.get("tasks", checkpoint.values.get("plan", {}).get("review_tasks", []))
        tasks = {item["task_id"]: ReviewTask.model_validate(item) for item in raw_tasks}
        # Initial candidates remain on the blackboard even if a later follow-up
        # supplies an empty/replacement set. Rebuild those results before merging
        # private follow-up progress through the same structural evidence gate.
        for raw in checkpoint.values.get("results", []):
            result = SpecialistResult.model_validate(raw)
            if result.task_id not in tasks:
                raise ReviewExecutionError("checkpoint result belongs to an unknown task")
            session.publish(tasks[result.task_id], result, record_events=False)
        for task in tasks.values():
            saved = self.checkpoints.load(session.thread_id, task.task_id)
            private = session.private(task.task_id) or AgentPrivateState()
            admitted_followup = (job.followup_admission is not None and job.followup_admission.task_id == task.task_id)
            finished = (private.stop_reason is not None and private.stop_reason != "cancelled"
                        and (not admitted_followup or (saved is not None and saved["generation"] == 2)))
            reason = private.stop_reason if finished else "review_time_exhausted"
            if not finished:
                private.coverage.failed[task.task_id] = reason
            session.publish(task, SpecialistResult(task_id=task.task_id, agent_id=task.agent_id,
                candidates=private.local_findings, coverage=private.coverage, stop_reason=reason), record_events=False)
        private = session.private("__final") or AgentPrivateState()
        private.stop_reason = "review_time_exhausted"
        final_checkpoint = self.checkpoints.load(session.thread_id, "__final")
        verification = None
        if final_checkpoint and final_checkpoint["generation"] == budget.ledger.review_round:
            raw = final_checkpoint["state"]
            current = {key: candidate.model_dump(mode="json") for key, candidate in session.board.candidates.items()}
            if raw.get("candidates") == current and raw.get("verification") is not None:
                verification = VerificationPhaseResult.model_validate(raw["verification"])
        result = session.partial_result(private, phase="review", verification=verification)
        result.coverage_summary.failed["__job"] = "review_time_exhausted"
        async def partial(state):
            return result
        async def no_followup(state):
            raise ReviewExecutionError("an exhausted review cannot admit follow-up")
        refs = {ref for candidate in session.board.candidates.values() for ref in candidate.evidence_refs}
        refs.update(ref for decision in result.decisions for ref in decision.evidence_refs)
        def accept(draft, decisions):
            return FinalAcceptanceGate(session.board.candidates, evidence_refs=refs,
                inspected_evidence={ref for ref, receipt in private.evidence_progress.items() if receipt.fully_inspected()},
                snapshot_id=repository.snapshot_id, duplicate_groups=result.duplicate_groups, verification=result,
                provenance=session.board.provenance(), allow_unreviewed=True).accept(draft, decisions)
        workflow = FinalizationWorkflow(partial, no_followup, accept, budget=budget, tasks=tasks,
                                        renderer=lambda accepted: self.render_report(job, accepted), emit=session.emit)
        return (await workflow.run())["rendered"]

    async def __call__(self, job: JobRecord):
        if job.workflow_version != "seven-agent-v1" or set(job.request) - {"snapshot_id", "changed_files"}:
            raise ReviewExecutionError("unsupported workflow version or request")
        repository = RepositoryContext(self.artifacts, self.cache, job.request["snapshot_id"], owner=job.owner)
        changed = job.request.get("changed_files", sorted(repository.manifest.entries))
        if not isinstance(changed, list) or any(path not in repository.manifest.entries for path in changed):
            raise ValueError("changed files must belong to the immutable snapshot")
        budget = BudgetManager(job.limits, job.ledger.model_copy(deep=True))
        # Unknown provider completion after restart is charged before admission.
        self.reconcile_models(job, budget)
        session = _ReviewSession(self, job, repository, budget, changed)
        async with AsyncSqliteSaver.from_conn_string(str(self.layout.checkpoints)) as saver:
            graph = session.compile(saver)
            config = {"configurable": {"thread_id": session.thread_id}}
            with tracing_context(enabled=False, parent=False):
                previous = await graph.aget_state(config)
                try:
                    if previous.values.get("rendered") and not previous.next:
                        return previous.values["rendered"]
                    result = await graph.ainvoke(None if previous.values else {"snapshot_id": repository.snapshot_id}, config)
                    return result["rendered"]
                finally:
                    budget.refresh_time()
                    self.jobs.update_ledger(job.job_id, owner=job.owner, ledger=budget.ledger)


class _ReviewSession:
    def __init__(self, executor, job, repository, budget, changed):
        self.executor, self.job, self.repository, self.budget, self.changed = executor, job, repository, budget, changed
        self.thread_id = sha256((job.owner + "\0" + job.job_id).encode()).hexdigest()
        self.board = SharedBlackboard(StructuralEvidenceGate(repository), runtime_limitations=(
            ("Worker crash recovered; uncertain elapsed time and outstanding model usage are charged conservatively.",)
            if job.crash_recoveries else ()))
        self.review_tasks = {}
        self._persistence_lock = asyncio.Lock()
        self.command_runtime = TrustedToolRuntime(repository, executor.jobs, job, commands=executor.trusted_commands)
        self.database_runtime = DatabaseTools(repository, job, policies=executor.databases)
        self.agents = AgentSubgraphs(executor.provider, repository.tools(self.command_runtime, self.database_runtime), budget, self.context,
            models=executor.models, persist=self.persist_agent, model_slots=executor.model_slots, emit=self.emit)

    def emit(self, kind, **payload):
        if kind == "model_call_completed":
            self.budget.refresh_time()
            self.executor.jobs.update_ledger(self.job.job_id, owner=self.job.owner,
                ledger=self.budget.ledger, model_completions=[payload])
        else:
            self.executor.jobs.emit(self.job.job_id, owner=self.job.owner, kind=kind, payload=payload)
        self.executor.jobs.dispatch_events(self.executor.events)

    async def persist_agent(self, state, ledger):
        async with self._persistence_lock:
            self.executor.jobs.update_ledger(self.job.job_id, owner=self.job.owner,
                                            ledger=self.budget.ledger.model_dump(mode="json"))
            # LangGraph's async saver may hold this SQLite writer lock. Keep its
            # event loop free to finish the transaction while private state waits.
            operation = asyncio.create_task(asyncio.to_thread(self.executor.checkpoints.save, self.thread_id, state,
                                                              self.budget.ledger.review_round))
            cancelled = False
            # Cancellation cannot stop a running SQLite writer thread. Keep both
            # persistence and execution ownership until it finishes, even when
            # shutdown/cancel requests arrive repeatedly.
            while not operation.done():
                try:
                    await asyncio.shield(operation)
                except asyncio.CancelledError:
                    cancelled = True
            operation.result()
            if cancelled:
                raise asyncio.CancelledError

    def context(self, state):
        selected = self.repository.context(state)
        if not isinstance(selected, dict):
            return selected
        from devwatch.review.contracts import AGENT_CONTRACTS
        selected["approved_commands"] = [{"command_id": command.command_id, "tool": command.tool,
                                          "files": command.files, "timeout_seconds": command.timeout_seconds}
            for command in self.executor.trusted_commands if command.tool in AGENT_CONTRACTS[state["task"].agent_id].allowed_tools
            and set(command.files).issubset(state["task"].files)][:10]
        selected["approved_databases"] = [{"database_id": policy.database_id} for policy in self.executor.databases
            if self.job.owner in policy.owners and state["task"].agent_id.value == "performance_scalability"]
        if state["task"].agent_id == AgentId.PLANNER:
            selected["repository_metadata"] = {
                "snapshot_id": self.repository.snapshot_id,
                "file_count": len(self.repository.manifest.entries),
                "selected_file_count": len(self.changed),
                "file_extensions": sorted({PurePosixPath(path).suffix.lower() for path in self.repository.manifest.entries}),
            }
            selected["changes"] = self.changed
            selected["intelligence"] = {path: {
                "status": facts["status"], "symbol_count": len(facts["symbols"]),
                "selected_symbols": facts["symbols"][:3], "call_count": len(facts["calls"]),
                "branches": facts["branch_count"], "limitations": facts["limitations"],
            } for path in self.changed for facts in [self.repository.analyze()[path]]}
            omitted = 0
            while len(json.dumps(selected, ensure_ascii=False).encode("utf-8")) > self.repository.CONTEXT_BYTES:
                if selected["intelligence"]:
                    selected["intelligence"].pop(next(reversed(selected["intelligence"])))
                    omitted += 1
                    selected["omitted_intelligence_count"] = omitted
                elif selected["evidence"]:
                    selected["evidence"].pop()
                    selected["omitted_evidence_count"] += 1
                else:
                    raise ReviewExecutionError("scope metadata exceeds the selective context limit")
        if state["task"].agent_id == AgentId.SYNTHESIZER_VERIFIER:
            selected["coverage"] = self.board.coverage().model_dump(mode="json")
            selected["review_tasks"] = {identity: {"files": task.files, "symbols": task.symbols, "focus": task.focus[:200]}
                                        for identity, task in self.review_tasks.items()}
            selected["candidate_tasks"] = dict(self.board.candidate_tasks)
            selected['candidate_provenance'] = self.board.provenance()
        return selected

    def private(self, identity):
        checkpoint = self.executor.checkpoints.load(self.thread_id, identity)
        return AgentPrivateState.model_validate(checkpoint["state"]["private_state"]) if checkpoint else None

    def compile(self, saver):
        from devwatch.review.observability import observed_node
        builder = StateGraph(ReviewGraphState)
        nodes = {"repository_intelligence": self.intelligence, "deterministic_analysis": self.deterministic,
                 "change_analyzer": self.change_analysis, "planner_agent": self.planner,
                 "context_manager": self.selected_context, "budget_manager": self.admission,
                 "deterministic_router": self.route, "specialist_subgraphs": self.specialists,
                 "shared_blackboard": self.blackboard, "structural_evidence_gate": self.structural_gate,
                 "completion_workflow": self.finalize}
        previous = START
        def emit_node(kind, state, **payload):
            self.emit(kind, **payload)
        for name, node in nodes.items():
            builder.add_node(name, observed_node(name, node, emit_node, scope="review"))
            builder.add_edge(previous, name)
            previous = name
        builder.add_edge(previous, END)
        return builder.compile(checkpointer=saver)

    def intelligence(self, state):
        return {"intelligence": self.repository.analyze()}

    def deterministic(self, state):
        return {"deterministic_signals": {path: {"parse_status": facts["status"], "branches": facts["branch_count"]}
                                         for path, facts in state["intelligence"].items()}}

    def change_analysis(self, state):
        return {"change_analysis": {"changed_files": self.changed, "scope": "snapshot-files"}}

    async def planner(self, state):
        if not self.changed:
            plan = ReviewPlan(selected_agents=[], priority_files=[], priority_symbols=[], risk_areas=[],
                review_tasks=[], review_strategy="No changed files selected; source is not inspected.",
                coverage_expectations=[], limitations=["Empty change selection; no AI investigation requested."])
            return {"plan": plan.model_dump(mode="json")}
        checkpoint = self.executor.checkpoints.load(self.thread_id, "__planner")
        if checkpoint and checkpoint["state"].get("output"):
            plan = ReviewPlan.model_validate(checkpoint["state"]["output"])
            self.emit("agent_reused", agent_id=AgentId.PLANNER, task_id="__planner", phase="planning")
        else:
            output = await self.agents.run_planner(snapshot_id=self.repository.snapshot_id,
                files=sorted(self.repository.manifest.entries), private_state=self.private("__planner"),
                complexity=min(1, len(self.changed) / 20), restored_state=checkpoint["state"] if checkpoint else None)
            if output["output"] is None:
                plan = ReviewPlan(selected_agents=[], priority_files=[], priority_symbols=[], risk_areas=[],
                    review_tasks=[], review_strategy="Partial review: planner unavailable; no specialist work dispatched.",
                    coverage_expectations=[], limitations=["Planner failed: " + output["private_state"].stop_reason])
            else:
                plan = output["output"]
        return {"plan": plan.model_dump(mode="json")}

    def selected_context(self, state):
        plan = ReviewPlan.model_validate(state["plan"])
        for task in plan.review_tasks:
            if any(path not in self.repository.manifest.entries for path in task.files):
                raise ReviewExecutionError("planner requested source outside the snapshot")
        return {"tasks": [task.model_dump(mode="json") for task in plan.review_tasks]}

    def admission(self, state):
        self.budget.refresh_time()
        self.executor.jobs.update_ledger(self.job.job_id, owner=self.job.owner, ledger=self.budget.ledger)
        return {}

    def route(self, state):
        return {"tasks": sorted(state["tasks"], key=lambda task: (task["agent_id"], task["task_id"]))}

    async def run_task(self, task, *, followup=None):
        if self.command_runtime.grants_measurement(task):
            self.agents.tools.grant_measurement_artifact(task)
        checkpoint = self.executor.checkpoints.load(self.thread_id, task.task_id)
        if followup is None and checkpoint:
            if checkpoint["generation"] != 1 or checkpoint["state"].get("task") != task.model_dump(mode="json"):
                raise ReviewExecutionError("worker checkpoint belongs to another assignment or generation")
        if followup is None and checkpoint and checkpoint["state"].get("output"):
            try:
                output = SpecialistResult.model_validate(checkpoint["state"]["output"])
            except ValueError as exc:
                raise ReviewExecutionError("worker checkpoint contains an invalid result") from exc
            if output.task_id != task.task_id or output.agent_id != task.agent_id:
                raise ReviewExecutionError("worker checkpoint result belongs to another assignment")
            if output.stop_reason != "cancelled":
                self.emit("agent_reused", agent_id=task.agent_id, task_id=task.task_id,
                          phase="investigation", stop_reason=safe_stop_reason(output.stop_reason))
                return output
        if followup is not None:
            task = task.model_copy(update={"focus": task.focus + "\nFollow-up question: " + followup.question
                                          + "\nEvidence needed: " + followup.evidence_needed})
        output = await self.agents.run_specialist(task, private_state=self.private(task.task_id),
            complexity=min(1, sum(self.repository.analyze()[path]["branch_count"] for path in task.files) / 30),
            restored_state=checkpoint["state"] if checkpoint and checkpoint["state"].get("task") == task.model_dump(mode="json") else None)
        return output["output"]

    async def run_task_safely(self, task, *, followup=None):
        try:
            result = SpecialistResult.model_validate(await self.run_task(task, followup=followup))
            if result.task_id != task.task_id or result.agent_id != task.agent_id:
                raise ValueError("worker result belongs to another assignment")
            return result
        except (OSError, sqlite3.Error, JobConflict, ReviewExecutionError):
            # Persistence/ownership/integrity failures are infrastructure failures,
            # not a specialist's unavailable result. Drain siblings and fail closed.
            raise
        except Exception:
            # A task-local crash must not cancel valid sibling work or erase
            # initial findings during follow-up. Cancellation propagates. If
            # durable state cannot be loaded/saved, fail the job normally.
            private = self.private(task.task_id) or AgentPrivateState(current_task=task.task_id)
            private.stop_reason = "specialist_failed"
            private.coverage.failed[task.task_id] = "specialist_failed"
            result = SpecialistResult(task_id=task.task_id, agent_id=task.agent_id,
                candidates=private.local_findings, quarantined=private.quarantined_candidates,
                coverage=private.coverage, stop_reason="specialist_failed")
            await self.persist_agent({"task": task, "private_state": private, "output": result, "action": None},
                                     self.budget.ledger.model_dump(mode="json"))
            self.emit("error_occurred", agent_id=task.agent_id, task_id=task.task_id,
                      phase="investigation", error_code="specialist_failed", stop_reason="specialist_failed")
            return result

    async def specialists(self, state):
        tasks = [ReviewTask.model_validate(task) for task in state["tasks"]]
        if len({task.task_id for task in tasks}) != len(tasks):
            raise ReviewExecutionError("duplicate specialist task IDs in dispatch")
        semaphore = asyncio.Semaphore(self.budget.limits.concurrent_model_calls)
        async def bounded(task):
            async with semaphore:
                return await self.run_task_safely(task)
        async with asyncio.TaskGroup() as group:
            executions = [group.create_task(bounded(task)) for task in tasks]
        results = [execution.result() for execution in executions]
        return {"results": [result.model_dump(mode="json") for result in results]}

    def blackboard(self, state, *, replay=False):
        try:
            assigned = [ReviewTask.model_validate(task) for task in state["tasks"]]
            results = [SpecialistResult.model_validate(raw) for raw in state["results"]]
        except ValueError as exc:
            raise ReviewExecutionError("invalid task or result in aggregation") from exc
        tasks = {task.task_id: task for task in assigned}
        identities = [result.task_id for result in results]
        if (len(tasks) != len(assigned) or len(set(identities)) != len(identities)
                or set(identities) != set(tasks)
                or any(result.agent_id != tasks[result.task_id].agent_id for result in results)):
            raise ReviewExecutionError("aggregation requires exactly one matching result per assigned task")
        # Check the entire join before changing shared candidates or coverage.
        for result in results:
            self.publish(tasks[result.task_id], result, record_events=not replay)
        return {}

    def publish(self, task, result, *, record_events=True):
        previous = set(self.board.candidates)
        rejected = {item.model_dump_json() for item in self.board.quarantined.get(task.task_id, [])}
        incoming = {item.model_dump_json() for item in result.quarantined}
        self.board.publish(task, result)
        if not record_events:
            return
        for identity in sorted(set(self.board.candidates) - previous):
            self.emit("finding_created", agent_id=result.agent_id, task_id=result.task_id,
                      phase="structural_gate", finding_id=identity, count=1)
        count = sum(item.model_dump_json() not in rejected | incoming
                    for item in self.board.quarantined.get(task.task_id, []))
        if count:
            self.emit("candidate_rejected", agent_id=result.agent_id, task_id=result.task_id,
                      phase="structural_gate", outcome="failed", count=count)

    def structural_gate(self, state):
        rejected = sum(len(items) for items in self.board.quarantined.values())
        self.emit("validation_failed" if rejected else "validation_passed", phase="structural_gate",
                  outcome="failed" if rejected else "succeeded", count=rejected or len(self.board.candidates))
        return {}

    async def finalize(self, state):
        if not self.board.results:
            self.blackboard(state, replay=True)
        tasks = {task["task_id"]: ReviewTask.model_validate(task) for task in state["tasks"]}
        self.review_tasks = tasks
        admitted = self.executor.jobs.get(self.job.job_id, owner=self.job.owner)
        if admitted.followup_admission is not None:
            request = admitted.followup_admission
            task = tasks[request.task_id]
            checkpoint = self.executor.checkpoints.load(self.thread_id, task.task_id)
            if checkpoint and checkpoint["generation"] == 2 and checkpoint["state"].get("output"):
                output = SpecialistResult.model_validate(checkpoint["state"]["output"])
                if output.stop_reason != "cancelled":
                    self.publish(task, output)
                    self.executor.jobs.complete_followup(self.job.job_id, owner=self.job.owner)
                    admitted.followup_completed = True
            if not admitted.followup_completed:
                self.publish(task, await self.run_task_safely(task, followup=request))
                self.executor.jobs.complete_followup(self.job.job_id, owner=self.job.owner)
        async def synthesize(final_state):
            if not self.changed:
                coverage = self.board.coverage()
                draft = ReportDraft(snapshot_id=self.repository.snapshot_id,
                    summary="No changed files selected; source was not inspected. Consult coverage for capture omissions.",
                    coverage=coverage, limitations=["Empty change selection; no AI investigation requested."])
                return VerificationSynthesisResult(decisions=[], report_draft=draft, coverage_summary=coverage)
            planner = self.private("__planner")
            if planner is not None and planner.stop_reason != "evidence_complete":
                result = self.partial_result(planner, phase="planner")
                result.coverage_summary.failed["__planner"] = planner.stop_reason
                return result
            candidates = {identity: candidate.model_dump(mode="json") for identity, candidate in self.board.candidates.items()}
            checkpoint = self.executor.checkpoints.load(self.thread_id, "__final")
            restored = (checkpoint["state"] if checkpoint and checkpoint["generation"] == self.budget.ledger.review_round
                        and checkpoint["state"].get("candidates") == candidates else None)
            if restored is not None and restored.get("output"):
                result = VerificationSynthesisResult.model_validate(restored["output"])
                private = AgentPrivateState.model_validate(restored["private_state"])
                self.emit("agent_reused", agent_id=AgentId.SYNTHESIZER_VERIFIER, task_id="__final",
                          phase="synthesis", stop_reason=safe_stop_reason(private.stop_reason))
            else:
                output = await self.agents.run_final(snapshot_id=self.repository.snapshot_id,
                    files=sorted(self.repository.manifest.entries), private_state=self.private("__final"),
                    candidates=candidates, restored_state=restored, review_tasks=set(tasks))
                if output["output"] is None:
                    result = self.partial_result(output["private_state"], verification=output.get("verification"))
                else:
                    result = output["output"]
                private = output["private_state"]
            authoritative = self.board.coverage()
            if private.stop_reason != "evidence_complete":
                authoritative.failed["__final"] = private.stop_reason
                authoritative.limitations.extend(private.coverage.limitations)
            result.coverage_summary = authoritative
            return result
        async def followup(final_state):
            request = final_state["followup"]
            task = tasks[request.task_id]
            self.publish(task, await self.run_task_safely(task, followup=request))
            self.executor.jobs.complete_followup(self.job.job_id, owner=self.job.owner)
        def accept(draft, decisions):
            private = self.private("__final") or AgentPrivateState()
            inspected = {ref for ref, receipt in private.evidence_progress.items() if receipt.fully_inspected()}
            checkpoint = self.executor.checkpoints.load(self.thread_id, "__final")
            recorded = None
            current = {key: candidate.model_dump(mode="json") for key, candidate in self.board.candidates.items()}
            if (checkpoint and checkpoint["generation"] == self.budget.ledger.review_round
                    and checkpoint["state"].get("candidates") == current
                    and checkpoint["state"].get("verification") is not None):
                recorded = VerificationPhaseResult.model_validate(checkpoint["state"]["verification"])
            def gate_for(records, groups, *, verification=None, allow_unreviewed=False):
                refs = {ref for candidate in self.board.candidates.values() for ref in candidate.evidence_refs}
                work = AgentWorkItem(task_id='__final', agent_id=AgentId.SYNTHESIZER_VERIFIER,
                    files=list(self.repository.manifest.entries), focus='Revalidate final evidence')
                for decision in records:
                    for ref in decision.evidence_refs:
                        self.repository.scoped_evidence(ref, work)
                        refs.add(ref)
                    if decision.verdict != 'rejected' and decision.causal_review is not None:
                        self.repository.validate_confirmation(self.board.candidates[decision.finding_id].model_dump(),
                                                              decision, work, private)
                return FinalAcceptanceGate(self.board.candidates, evidence_refs=refs, inspected_evidence=inspected,
                    snapshot_id=self.repository.snapshot_id, duplicate_groups=groups, verification=verification,
                    provenance=self.board.provenance(), allow_unreviewed=allow_unreviewed)
            try:
                same_decisions = (recorded is not None and len(recorded.decisions) == len(decisions)
                                  and {item.finding_id: item for item in recorded.decisions}
                                  == {item.finding_id: item for item in decisions})
                groups = recorded.duplicate_groups if same_decisions else []
                return gate_for(decisions, groups, verification=recorded if same_decisions else None,
                    allow_unreviewed=private.stop_reason != 'evidence_complete').accept(draft, decisions)
            except (ValueError, KeyError, FileNotFoundError, PermissionError):
                # One deterministic repair uses authoritative recorded decisions,
                # revalidating inspection and preserving the remaining claims as uncertain.
                self.emit("validation_failed", agent_id=AgentId.SYNTHESIZER_VERIFIER, task_id="__final",
                          phase="acceptance", outcome="failed")
                safe = self.partial_result(private.model_copy(update={"stop_reason": "final_consistency_failure"}),
                                           phase="final acceptance", verification=recorded)
                safe.report_draft.coverage = draft.coverage.model_copy(deep=True)
                safe.report_draft.coverage.failed.setdefault("__final", "final_consistency_failure")
                safe.report_draft.limitations.append("Inconsistent synthesis replaced by deterministic verified findings.")
                return gate_for(safe.decisions, safe.duplicate_groups, verification=safe,
                    allow_unreviewed=True).accept(safe.report_draft, safe.decisions)
        async def admit(request, ledger):
            self.executor.jobs.update_ledger(self.job.job_id, owner=self.job.owner, ledger=ledger, followup=request)
        workflow = FinalizationWorkflow(synthesize, followup, accept, budget=self.budget,
                                        tasks=tasks, admit=admit, emit=self.emit,
                                        renderer=lambda accepted: self.executor.render_report(self.job, accepted))
        final = await workflow.run()
        return {"rendered": final["rendered"]}

    def partial_result(self, private, *, phase="verification/synthesis", verification=None):
        """A bounded failure does not manufacture a verified defect or clean bill."""
        reason = private.stop_reason or "finished_without_result"
        rationale = f"{phase} stopped ({reason}); causal claim and impact remain unverified."
        preserved = {decision.finding_id: decision for decision in verification.decisions} if verification else {}
        work = AgentWorkItem(task_id="__final", agent_id=AgentId.SYNTHESIZER_VERIFIER,
                             files=list(self.repository.manifest.entries), focus="Validate persisted verification")
        decisions = []
        for identity, candidate in sorted(self.board.candidates.items()):
            if identity in preserved:
                decision = preserved[identity]
                try:
                    if decision.causal_review is not None and any(
                            item.status == 'unsupported' for item in decision.causal_review.assessments):
                        decision = decision.model_copy(update={'verdict': 'rejected',
                            'rationale': 'Rejected: recorded causal review identifies an unsupported clause.'})
                    validate_decision(candidate, decision)
                    for ref in decision.evidence_refs:
                        self.repository.scoped_evidence(ref, work)
                    if decision.verdict != 'rejected':
                        if (decision.verdict == 'confirmed' and decision.confidence < .8) or not decision.evidence_refs or any(
                            ref not in private.evidence_progress or not private.evidence_progress[ref].fully_inspected()
                            for ref in decision.evidence_refs):
                            raise ValueError("persisted confirmation lacks inspection receipts")
                        self.repository.validate_confirmation(candidate.model_dump(), decision, work, private)
                    if decision.verdict != "rejected" and not decision.evidence_refs:
                        raise ValueError("persisted decision lacks evidence")
                    decisions.append(decision)
                    continue
                except (ValueError, KeyError, FileNotFoundError, PermissionError):
                    pass  # Retain the candidate below without asserting verification.
            confidence = min(candidate.confidence, 0.5)
            decisions.append(VerificationDecision(finding_id=identity, verdict='uncertain',
                confidence=confidence, rationale=rationale, evidence_refs=candidate.evidence_refs))
        metadata = VerificationPhaseResult(**{field: getattr(verification, field)
            for field in VerificationPhaseResult.model_fields}) if verification else VerificationPhaseResult(decisions=[])
        metadata.decisions = decisions
        relation_limitations = []
        try:
            validate_relations(self.board.candidates, metadata,
                {ref for ref, receipt in private.evidence_progress.items() if receipt.fully_inspected()})
        except ValueError:
            relation_limitations = ['Unvalidated duplicate/disagreement relations were not reused.']
            relation_limitations.extend('Unresolved relation: ' + item.rationale for item in metadata.disagreements)
            metadata.duplicate_groups, metadata.duplicate_reviews, metadata.disagreements = [], [], []
        coverage = self.board.coverage()
        coverage.failed['__planner' if phase == 'planner' else '__final'] = reason
        draft = assemble_report(self.repository.snapshot_id, self.board.candidates, decisions,
            summary=f"Partial review: {phase} stopped ({reason})", coverage=coverage,
            duplicate_groups=metadata.duplicate_groups,
            limitations=[f"Partial result: {phase} stopped ({reason}); recorded verification preserved; remaining claims unverified.",
                         *relation_limitations])
        return VerificationSynthesisResult(**metadata.model_dump(), report_draft=draft, coverage_summary=draft.coverage)
