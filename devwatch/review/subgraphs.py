"""Iterative specialist LangGraph subgraphs and a permissioned tool boundary.

Source/tool payloads are retrieved through the context callback, not retained in
private state. The service must supply bounded context, artifact-backed evidence,
persist accounting before effects, and share its model-call semaphore across jobs.
"""

import asyncio
import inspect
import json
import time
from typing import Any, Awaitable, Callable, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context
from pydantic import Field, ValidationError

from devwatch.providers.base import LLMProvider, LLMRequest, LLMResponse
from devwatch.providers.exceptions import (ProviderAuthenticationError, ProviderRateLimitError,
    ProviderQuotaExhaustedError, ProviderTemporaryError, ProviderTimeoutError)
from devwatch.review.budgets import BudgetExceeded, BudgetManager
from devwatch.review.jobs import UnknownToolCompletion, safe_stop_reason
from devwatch.review.tool_catalogue import TOOL_ARGUMENTS, CommandArguments, describe_tool
from devwatch.review.tool_errors import ToolFailure, diagnose, failure_identity, safe_arguments
from devwatch.review import investigation, tool_selection, prompts
from devwatch.review.contracts import (
    AGENT_CONTRACTS, SPECIALISTS, AgentAction, AgentId, AgentPrivateState, AgentWorkItem,
    ContractModel, EvidenceProgress, ModelTier, ReviewPlan, ReviewTask, SpecialistResult, TokenUsage,
    SynthesisSummary, VerificationPhaseResult, VerificationSynthesisResult,
)


class ToolObservation(ContractModel):
    evidence_ref: str = Field(min_length=1)
    inspected: list[str] = Field(default_factory=list)
    offset: int = Field(default=0, ge=0)
    max_chars: int = Field(default=1500, ge=1, le=3000)


ToolHandler = Callable[[dict[str, Any], ReviewTask | AgentWorkItem], Awaitable[ToolObservation]]


class IncompleteCompletion(RuntimeError):
    def __init__(self, reason, *, recoverable=False):
        super().__init__(reason)
        self.recoverable = recoverable


class PromptContextLimit(RuntimeError):
    pass


class ContextRetrievalTimeout(RuntimeError):
    pass


class CandidateSchemaError(ValueError):
    def __init__(self, rejections):
        super().__init__('Return complete candidates: category, title, description, impact, confidence, '
                         'location, evidence_refs, kind and remediation. Preserve valid findings.')
        self.rejections = rejections


class EventPersistenceError(OSError):
    """Durable telemetry failure must propagate through specialist isolation."""


class PermissionedTools:
    def __init__(self):
        self._handlers: dict[str, ToolHandler] = {}
        self._arguments = dict(TOOL_ARGUMENTS)
        self._availability = {}
        self._measurement_tasks: set[str] = set()
        self.validate_confirmation = None
        self.validate_candidate = None

    def register(self, name: str, handler: ToolHandler, *, arguments_model=None, available=None) -> None:
        known = set().union(*(contract.allowed_tools for contract in AGENT_CONTRACTS.values())) | {"write_artifact"}
        if name not in known or name in self._handlers:
            raise ValueError("unknown or already registered tool")
        self._handlers[name] = handler
        if arguments_model is not None:
            self._arguments[name] = arguments_model
        if available is not None:
            self._availability[name] = available

    def catalogue(self, task) -> list[dict[str, Any]]:
        contract = AGENT_CONTRACTS[task.agent_id]
        allowed = set(contract.allowed_tools)
        if task.agent_id == AgentId.PERFORMANCE_SCALABILITY and task.task_id in self._measurement_tasks:
            allowed.add("write_artifact")
        return [describe_tool(name, self._arguments[name]) for name in sorted(allowed & self._handlers.keys())]

    def for_model(self, state, context):
        catalogue=self.catalogue(state['task'])
        available=[tool for tool in catalogue if tool['name'] not in self._availability
                   or self._availability[tool['name']](state['task'])]
        stage,selected=tool_selection.select(available,state,context)
        def size(tools):
            return len(json.dumps(tools,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8'))
        return selected,dict(stage=stage,selected_names=[tool['name'] for tool in selected],
            role_tool_count=len(catalogue),selected_tool_count=len(selected),
            role_catalogue_bytes=size(catalogue),selected_catalogue_bytes=size(selected))

    def grant_measurement_artifact(self, task: ReviewTask) -> None:
        # Operator/runtime API, never exposed as an agent action or planner field.
        if task.agent_id != AgentId.PERFORMANCE_SCALABILITY:
            raise PermissionError("only performance measurement tasks can write artifacts")
        self._measurement_tasks.add(task.task_id)

    def authorize(self, task: ReviewTask, action: AgentAction) -> None:
        AGENT_CONTRACTS[task.agent_id].validate_action(
            action, produces_measurement_artifact=task.task_id in self._measurement_tasks)
        if action.kind in {"call_tool", "request_context"}:
            parsed = self._arguments[action.tool or "read_source"].model_validate(action.arguments)
            path = getattr(parsed, "file_path", None)
            if path is not None and path not in task.files:
                raise PermissionError("source is outside the assigned scope")
            return parsed.model_dump(mode="json", exclude_unset=True)

    async def execute(self, task: ReviewTask, action: AgentAction) -> ToolObservation:
        arguments = self.authorize(task, action)
        handler = self._handlers.get(action.tool)
        if handler is None:
            raise ToolFailure("tool_unavailable", "Choose another permitted tool or report unavailable coverage.")
        return ToolObservation.model_validate(await handler(arguments, task))


class AgentExecutionState(TypedDict, total=False):
    task: ReviewTask | AgentWorkItem
    private_state: AgentPrivateState
    action: AgentAction | None
    output: SpecialistResult | ReviewPlan | VerificationSynthesisResult | None
    snapshot_id: str
    phase: str
    verification: VerificationPhaseResult | None
    candidates: dict[str, Any]
    model_tier: ModelTier
    escalation_count: int
    proposed_followups: list[Any]
    review_tasks: list[str]
    retry_operation: str | None
    batch_ids: list[str]
    validation_error: str
    last_tool_error: dict[str, str] | None
    run_id: str
    model_call_id: str
    provider_observation: dict[str, Any]
    provider_observations: list[dict[str, Any]]
    tool_selection: dict[str, Any]
    tool_selections: list[dict[str, Any]]
    prompt_revision: dict[str, Any]


class ModelRouter:
    """One policy-bounded escalation from deterministic runtime signals."""
    @staticmethod
    def select(agent: AgentId, *, complexity: float = 0, confidence: float = 1):
        if not 0 <= complexity <= 1 or not 0 <= confidence <= 1:
            raise ValueError("routing signals must be finite values between zero and one")
        policy = AGENT_CONTRACTS[agent].model_policy
        if policy.escalation_tier and policy.max_escalations and (complexity >= 0.7 or confidence < 0.6):
            return policy.escalation_tier, 1
        return policy.initial_tier, 0


async def _resolve(value):
    return await value if inspect.isawaitable(value) else value


class AgentSubgraphs:
    def __init__(self, provider: LLMProvider, tools: PermissionedTools, budget: BudgetManager,
                 context: Callable[[AgentExecutionState], Any], *, models: dict[ModelTier, str],
                 persist: Callable[[AgentExecutionState, dict[str, Any]], Any] | None = None,
                 model_slots: asyncio.Semaphore | None = None, emit: Callable | None = None):
        if set(models) != set(ModelTier) or any(not name.strip() for name in models.values()):
            raise ValueError("explicit small, medium and strong model names are required")
        self.provider, self.tools, self.budget, self.context = provider, tools, budget, context
        self.models, self.persist = dict(models), persist
        self.emit = emit
        self.budget.begin_execution()
        self.model_slots = model_slots or asyncio.Semaphore(budget.limits.concurrent_model_calls)
        self.graphs = {agent: self._build() for agent in SPECIALISTS}
        self.control_graph = self._build()

    def _build(self):
        builder = StateGraph(AgentExecutionState)
        builder.add_node("investigate", self._investigate)
        builder.add_node("execute_action", self._execute_action)
        builder.add_edge(START, "investigate")
        builder.add_conditional_edges("investigate", lambda state: END if state["private_state"].stop_reason else "execute_action")
        builder.add_conditional_edges("execute_action", lambda state: END if state["private_state"].stop_reason else "investigate")
        # Private agent progress is persisted explicitly before effects; do not
        # inherit the root graph's serializer/checkpointer implicitly.
        return builder.compile(checkpointer=False)

    async def _save(self, state: AgentExecutionState) -> None:
        if self.persist is not None:
            saved = dict(state)
            action = state.get("action")
            if action is not None and action.kind in {"call_tool", "request_context"}:
                arguments, _ = safe_arguments(action.arguments, state["task"].files)
                saved["action"] = action.model_copy(update={"arguments": arguments})
            await _resolve(self.persist(saved, self.budget.ledger.model_dump(mode="json")))

    async def _event(self, kind, state, **metadata):
        if self.emit is not None:
            payload = dict(agent_id=state["task"].agent_id, task_id=state["task"].task_id,
                phase=state.get("phase", "investigation"), iteration=state["private_state"].iteration_count,
                run_id=state.get("run_id"))
            payload.update(metadata)
            try:
                await _resolve(self.emit(kind, **payload))
            except Exception as exc:
                raise EventPersistenceError("durable event persistence failed") from exc

    async def _invoke(self, graph, state):
        state["run_id"] = uuid4().hex
        started, outcome = time.monotonic(), "failed"
        await self._event("agent_started", state)
        try:
            with tracing_context(enabled=False, parent=False):
                result = await graph.ainvoke(state, config={
                    "recursion_limit": 2 * self.budget.limits.iterations_per_task + 4})
            state = result
            outcome = "succeeded" if state["private_state"].stop_reason == "evidence_complete" else "failed"
            return result
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        finally:
            reason = state["private_state"].stop_reason or ("cancelled" if outcome == "cancelled" else "execution_failed")
            await self._event("agent_completed", state, outcome=outcome, stop_reason=safe_stop_reason(reason),
                              duration_seconds=time.monotonic() - started, total_tokens=state["private_state"].usage.total_tokens)

    def _stop(self, state: AgentExecutionState, reason: str, *, explanation: str = "") -> AgentExecutionState:
        private = state["private_state"]
        if state["task"].agent_id in SPECIALISTS and private.investigation is not None:
            reason = investigation.finish(private, reason)
        private.stop_reason = reason
        private.stop_explanation = explanation
        if reason == "evidence_complete" and private.coverage.failed.get(state["task"].task_id) in {"evidence_incomplete", "no_progress"}:
            private.coverage.failed.pop(state["task"].task_id)
        if reason != "evidence_complete":
            private.coverage.failed[state["task"].task_id] = reason
        if state["task"].agent_id in SPECIALISTS:
            state["output"] = SpecialistResult(
                task_id=state["task"].task_id, agent_id=state["task"].agent_id,
                candidates=private.local_findings, quarantined=private.quarantined_candidates,
                coverage=private.coverage, stop_reason=reason, stop_explanation=explanation)
        state["action"] = None
        return state

    def _parse_action(self, raw: str, state: AgentExecutionState) -> AgentAction:
        task = state["task"]
        action = AgentAction.model_validate_json(raw)
        private = state["private_state"]
        if action.kind in {'call_tool','request_context'} and state.get('tool_selections'):
            name=action.tool or 'read_source'
            selection=state['tool_selections'][-1]
            selection.update(proposed_tool=name if name in TOOL_ARGUMENTS else 'unrecognized_tool',
                             advertised=name in selection['selected_names'])
        for identity in action.inspected_evidence:
            receipt = private.evidence_progress.get(identity)
            if receipt is None or not receipt.delivered:
                raise ValueError("cannot inspect evidence which has not been delivered")
        # Receipt acknowledgements apply only to pages sent in a completed model
        # request. Tool execution and context selection cannot create inspection.
        for identity in action.inspected_evidence:
            receipt = private.evidence_progress[identity]
            span = receipt.last_delivered or receipt.delivered[-1]
            if span not in receipt.inspected:
                receipt.inspected.append(span)
            for path in [receipt.source_file] if receipt.source_file is not None and receipt.fully_inspected() else []:
                if path not in private.coverage.inspected_files:
                    private.coverage.inspected_files.append(path)
                if path not in private.inspected_files_and_symbols:
                    private.inspected_files_and_symbols.append(path)
                if private.coverage.skipped.get(path) == "not_inspected":
                    private.coverage.skipped.pop(path)
        if private.investigation is not None:
            investigation.refresh(private)
        if action.kind == "submit_candidates":
            output = SpecialistResult.model_validate(action.payload)
            if output.task_id != task.task_id or output.agent_id != task.agent_id:
                raise ValueError("result does not belong to the assigned agent/task")
            if task.agent_id in SPECIALISTS:
                if not output.candidates and output.quarantined:
                    raise CandidateSchemaError(output.quarantined)
                output = investigation.admit(task, private, output, self.tools.validate_candidate)
                action.payload = output.model_dump(mode="json")
        elif action.kind == "submit_plan":
            plan = ReviewPlan.model_validate(action.payload)
            requested = set(plan.priority_files) | {path for task in plan.review_tasks for path in task.files}
            if not requested.issubset(task.files) or any(t.task_id.startswith("__") for t in plan.review_tasks):
                raise ValueError("plan requests source outside its scope or a runtime-reserved task ID")
            if task.files and not plan.review_tasks:
                raise ValueError("a nonempty review scope requires specialist investigation tasks")
            evidence = set(private.evidence_refs) | set(task.evidence_refs)
            if any(not set(item.evidence_refs).issubset(evidence) for item in plan.review_tasks):
                raise ValueError("plan tasks reference evidence not retrieved by the Planner")
            if any(self.budget.model_allowance(agent) == 0 for agent in plan.selected_agents):
                raise BudgetExceeded("no investigation budget remains for a selected specialist")
        elif action.kind == "submit_verification":
            if state.get("phase") != "verification":
                raise ValueError("verification has already been recorded")
            result = VerificationPhaseResult.model_validate(action.payload)
            known = {key: state["candidates"][key] for key in state.get("batch_ids", state["candidates"])}
            if {d.finding_id for d in result.decisions} != set(known) or len(result.decisions) != len(known):
                raise ValueError("every known candidate requires exactly one decision")
            for decision in result.decisions:
                allowed = set(known[decision.finding_id]["evidence_refs"]) | set(private.evidence_refs)
                if not set(decision.evidence_refs).issubset(allowed):
                    raise ValueError("verification cites unknown evidence")
                if decision.verdict != "rejected" and not decision.evidence_refs:
                    raise ValueError("non-rejected decisions require evidence")
                if decision.verdict == "confirmed":
                    if decision.confidence < .8 or any(
                        not private.evidence_progress.get(ref, EvidenceProgress()).inspected for ref in decision.evidence_refs
                    ):
                        raise ValueError("confirmation requires delivered and inspected evidence with confidence >=0.8")
                    if self.tools.validate_confirmation is not None:
                        self.tools.validate_confirmation(known[decision.finding_id], decision, task, private)
            if any(len(group) < 2 or len(group) != len(set(group)) or not set(group).issubset(state["candidates"])
                   for group in result.duplicate_groups):
                raise ValueError("duplicate groups contain unknown candidates")
            if state.get("review_tasks") is not None and any(request.task_id not in state["review_tasks"] for request in result.followup_requests):
                raise ValueError("follow-up must target an existing review task")
        elif action.kind == "submit_synthesis":
            if state.get("phase") != "synthesis" or state.get("verification") is None:
                raise ValueError("verification must precede synthesis")
            from devwatch.review.finalization import assemble_report, FinalAcceptanceGate
            if "report_draft" not in action.payload:
                prose = SynthesisSummary.model_validate(action.payload)
                verified = state["verification"]
                draft = assemble_report(state["snapshot_id"], state["candidates"], verified.decisions,
                                        summary=prose.summary, limitations=prose.limitations,
                                        duplicate_groups=verified.duplicate_groups)
                action.payload = VerificationSynthesisResult(**verified.model_dump(), report_draft=draft,
                                                            coverage_summary=draft.coverage).model_dump(mode="json")
            result = VerificationSynthesisResult.model_validate(action.payload)
            verification = VerificationPhaseResult.model_validate({
                field: getattr(result, field) for field in VerificationPhaseResult.model_fields})
            if verification != state["verification"] or result.report_draft.snapshot_id != state["snapshot_id"]:
                raise ValueError("synthesis cannot change verification or snapshot identity")
            from devwatch.review.contracts import FindingCandidate
            FinalAcceptanceGate({key: FindingCandidate.model_validate(raw) for key, raw in state["candidates"].items()},
                evidence_refs={ref for decision in verification.decisions for ref in decision.evidence_refs},
                inspected_evidence={ref for ref, receipt in private.evidence_progress.items() if receipt.inspected},
                snapshot_id=state["snapshot_id"], duplicate_groups=verification.duplicate_groups
                ).accept(result.report_draft, verification.decisions)
        elif action.kind == "request_followup":
            # Follow-up proposals belong to the verification output; runtime
            # Completion Assessment alone may admit and dispatch a follow-up.
            from devwatch.review.contracts import FollowupRequest
            if state.get("phase") != "verification":
                raise ValueError("follow-up proposals must be recorded before synthesis")
            request = FollowupRequest.model_validate(action.payload)
            if state.get("review_tasks") is not None and request.task_id not in state["review_tasks"]:
                raise ValueError("follow-up must target an existing review task")
        return action

    def _prepare_prompt(self, state, selected_context, *, repair):
        task, private = state["task"], state["private_state"]
        contract = AGENT_CONTRACTS[task.agent_id]
        result_schema = (ReviewPlan if task.agent_id == AgentId.PLANNER else
                         VerificationPhaseResult if state.get("phase") == "verification" else
                         SynthesisSummary if task.agent_id == AgentId.SYNTHESIZER_VERIFIER else
                         SpecialistResult)
        known = state.get("candidates", {})
        active = {key: known[key] for key in state.get("batch_ids", known)}
        large_synthesis = state.get("phase") == "synthesis" and len(known) > 8
        if large_synthesis:
            active = {}
        compact = private.model_dump(mode="json", exclude={"local_findings", "pending_actions", "evidence_progress", "coverage", "quarantined_candidates", "tool_diagnostics", "investigation"})
        compact["hypotheses"] = [{**item, "claim": item["claim"][:300]} for item in compact["hypotheses"][-3:]]
        compact["evidence_refs"] = compact["evidence_refs"][-12:]
        compact["evidence_progress"] = {ref: {"processed": receipt.processed, "delivered": bool(receipt.delivered), "inspected": bool(receipt.inspected)}
            for ref in compact["evidence_refs"] if (receipt := private.evidence_progress.get(ref)) is not None}
        compact["local_finding_count"] = len(private.local_findings)
        verified = state["verification"].model_dump(mode="json") if state.get("verification") else None
        if state.get("phase") == "verification" and verified:
            verified = {"completed_ids": [item["finding_id"] for item in verified["decisions"]],
                        "assembly": "Return decisions only for the current candidates batch."}
        if large_synthesis:
            verified = {"decision_count": len(state["verification"].decisions), "assembly": "Runtime retains all recorded decisions and findings; return SynthesisSummary only."}
        catalogue,selection=self.tools.for_model(state,selected_context)
        state['tool_selection']=selection
        skills,revision=prompts.guidance(task.agent_id.value,contract.system_prompt,
                                        state.get('phase','investigation'),selected_context)
        state['prompt_revision']=revision
        body = {
            'prompt_revision':revision,
            'policy_skills':skills,
            "task": task.model_dump(mode="json"),
            "tool_catalogue": catalogue,
            "private_state": compact,
            "selected_context": selected_context,
            "action_schema": AgentAction.model_json_schema(),
            "result_schema": result_schema.model_json_schema(),
            "phase": state.get("phase", "investigation"),
            "verified": verified, "candidates": active, "candidate_count": len(known),
            "context_omissions": ["private_state_compacted"] if len(private.hypotheses) > 3 or private.local_findings else [],
            "repair": state.get("validation_error", "Previous response failed validation. Return one valid structured action.") if repair else None,
            "last_tool_error": state.get("last_tool_error"),
            "investigation": investigation.context(private) if private.investigation is not None else None,
            "tool_diagnostic": private.tool_diagnostics[-1].model_dump(exclude={"fingerprint"})
                if state.get("last_tool_error") and private.tool_diagnostics else None,
        }
        actions = set(contract.allowed_actions)
        if state.get("phase") == "verification":
            actions.discard("submit_synthesis")
        elif state.get("phase") == "synthesis":
            actions.difference_update({"submit_verification", "request_followup"})
        if not catalogue:
            actions.difference_update({'call_tool','request_context'})
        body['action_schema']['properties']['tool']['enum']=[None,*selection['selected_names']]
        body["action_schema"]["properties"]["kind"]["enum"] = sorted(actions)
        # Bound the complete serialized request, keeping schemas, permissions and
        # individual candidate claims intact. Optional context can be retrieved.
        while True:
            max_output = (min(8192, 2048 + 1024 * len(active)) if task.agent_id == AgentId.SYNTHESIZER_VERIFIER
                          else self.budget.limits.planner_output_tokens if task.agent_id == AgentId.PLANNER else 8192)
            prompt = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            input_bound = len(prompt.encode("utf-8")) + len(contract.system_prompt.encode("utf-8")) + 512
            allowance = self.budget.model_allowance(task.agent_id) if task.agent_id == AgentId.PLANNER else None
            if allowance is not None:
                max_output = min(max_output, allowance - input_bound)
            if max_output > 0 and input_bound + max_output <= self.budget.limits.model_context_tokens:
                return prompt, max_output
            optional = {key: value for key, value in selected_context.items() if key not in {"evidence", "snapshot_id", "scope"}} if isinstance(selected_context, dict) else {}
            if optional:
                key = max(optional, key=lambda item: len(json.dumps(optional[item], ensure_ascii=False).encode("utf-8")))
                selected_context.pop(key)
                body["context_omissions"].append(key)
            elif isinstance(selected_context, dict) and selected_context.get("evidence"):
                # Retrieved pages must be deliverable before acknowledgment.
                # Fit the response reservation first; it is a ceiling, not a
                # reason to discard evidence that fits the actual context.
                headroom = self.budget.limits.model_context_tokens - input_bound
                if task.agent_id != AgentId.PLANNER and headroom >= 512:
                    return prompt, min(max_output, headroom)
                selected_context["evidence"].pop()
                body["context_omissions"].append("evidence_page; retrieve via read_evidence")
            elif compact.get("hypotheses"):
                compact["hypotheses"].pop(0)
                body["context_omissions"].append("hypothesis")
            elif state.get("phase") == "verification" and len(active) > 1:
                active.pop(next(reversed(active)))
                state["batch_ids"] = list(active)
            else:
                # Optional context is already removed. A response reservation
                # is a ceiling, not a minimum: retain mandatory schemas/claims
                # and fit output to the remaining context without raising limits.
                headroom = self.budget.limits.model_context_tokens - input_bound
                if task.agent_id != AgentId.PLANNER and headroom >= 512:
                    return prompt, min(max_output, headroom)
                if allowance is not None and allowance <= input_bound:
                    raise BudgetExceeded("remaining Planner budget cannot admit the required prompt")
                raise PromptContextLimit("required request fields exceed model context")

    async def _call_model(self, state: AgentExecutionState, *, repair: bool, attempt: int = 1) -> str:
        task, private = state["task"], state["private_state"]
        contract = AGENT_CONTRACTS[task.agent_id]
        if state.get("phase") == "verification":
            decided = {decision.finding_id for decision in state["verification"].decisions} if state.get("verification") else set()
            state["batch_ids"] = [key for key in state["candidates"] if key not in decided][:8]
            task = task.model_copy(update={"evidence_refs": list(dict.fromkeys(ref for key in state["batch_ids"]
                                             for ref in state["candidates"][key]["evidence_refs"]))})
        try:
            selected_context = await asyncio.wait_for(_resolve(self.context({**state, "task": task})),
                                                      timeout=self.budget.timeout_for("command"))
        except TimeoutError as exc:
            raise ContextRetrievalTimeout from exc
        prompt, max_output = self._prepare_prompt(state, selected_context, repair=repair)
        # UTF-8 bytes plus framing margin conservatively reserve input, rather than
        # estimating from words. Admission and provider output share one ceiling.
        reserved = len(prompt.encode("utf-8")) + len(contract.system_prompt.encode("utf-8")) + 512 + max_output
        async with self.model_slots:
            ticket = self.budget.reserve_model(task.agent_id, reserved)
            observation_limit = ((self.budget.limits.iterations_per_task + self.budget.limits.schema_repairs_per_task)
                                 * (1 + self.budget.limits.transient_retries))
            state['tool_selections']=(state.get('tool_selections',[])+[
                {**state['tool_selection'],'operation_id':ticket}])[-observation_limit:]
            await self._save(state)
            state["model_call_id"] = ticket
            started = time.monotonic()
            await self._event("model_call_started", state, operation_id=ticket, attempt=attempt)
            try:
                response = await asyncio.wait_for(self.provider.generate_completion(LLMRequest(
                    prompt=prompt, system_prompt=contract.system_prompt,
                    model=self.models[state.get("model_tier", contract.model_policy.initial_tier)], temperature=0,
                    max_tokens=max_output,
                    json_mode=True,
                    reasoning_effort="low",
                )), timeout=self.budget.timeout_for("provider"))
                response = LLMResponse.model_validate(response)
            except BaseException as exc:
                # A timeout/cancel can still consume provider tokens. Charge the
                # reservation conservatively; never free unknown consumption.
                private.usage = TokenUsage(prompt_tokens=private.usage.prompt_tokens + reserved,
                                           completion_tokens=private.usage.completion_tokens)
                private.coverage.limitations.append("Provider completion unknown; reserved tokens charged conservatively.")
                self.budget.record_model(ticket, prompt_tokens=reserved, completion_tokens=0)
                code = ("provider_authentication" if isinstance(exc, ProviderAuthenticationError) else
                        "provider_quota" if isinstance(exc, ProviderQuotaExhaustedError) else
                        "provider_rate_limit" if isinstance(exc, ProviderRateLimitError) else
                        "provider_temporary" if isinstance(exc, ProviderTemporaryError) else
                        "provider_timeout" if isinstance(exc, (TimeoutError, ProviderTimeoutError)) else "provider_failure")
                await self._event("model_call_completed", state, operation_id=ticket, attempt=attempt,
                    outcome="cancelled" if isinstance(exc, asyncio.CancelledError) else "failed",
                    error_code=None if isinstance(exc, asyncio.CancelledError) else code,
                    total_tokens=reserved, duration_seconds=time.monotonic() - started)
                raise
            finally:
                self.budget.refresh_time()
            reported = response.usage
            state["provider_observation"] = {**self._provider_observation(response, max_output),
                                             'prompt_revision':state['prompt_revision']}
            observations = state.get("provider_observations", []) + [
                {**state["provider_observation"], "operation_id": ticket}]
            state["provider_observations"] = observations[-observation_limit:]
            prompt_tokens, completion_tokens = reported.prompt_tokens, reported.completion_tokens
            split_total = prompt_tokens + completion_tokens
            if min(prompt_tokens, completion_tokens, reported.total_tokens) < 0 or max(split_total, reported.total_tokens) == 0:
                prompt_tokens, completion_tokens = reserved, 0
                private.coverage.limitations.append("Provider token usage unavailable; reserved tokens charged conservatively.")
            elif reported.total_tokens > split_total:
                prompt_tokens += reported.total_tokens - split_total
                private.coverage.limitations.append("Provider token split incomplete; total usage charged conservatively.")
            elif "total_tokens" in reported.model_fields_set and reported.total_tokens != split_total:
                private.coverage.limitations.append("Provider usage totals disagree; larger consumption charged.")
            private.usage = TokenUsage(
                prompt_tokens=private.usage.prompt_tokens + prompt_tokens,
                completion_tokens=private.usage.completion_tokens + completion_tokens)
            try:
                self.budget.record_model(ticket, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
            finally:
                await self._event("model_call_completed", state, operation_id=ticket, attempt=attempt,
                    outcome="succeeded" if response.finish_reason == "stop" and not response.refusal else "failed",
                    finish_reason=response.finish_reason if response.finish_reason in {"stop", "length", "content_filter"} else "other",
                    total_tokens=prompt_tokens + completion_tokens, duration_seconds=time.monotonic() - started)
            if isinstance(selected_context, dict):
                for page in selected_context.get("evidence", []):
                    if not isinstance(page, dict) or "excerpt" not in page:
                        continue
                    receipt = private.evidence_progress.setdefault(page["evidence_ref"], EvidenceProgress())
                    span = (page["offset"], page["end_offset"])
                    if span not in receipt.delivered:
                        receipt.delivered.append(span)
                    receipt.last_delivered = span
                    receipt.source_scope = page.get("source_scope", [])
                    if page.get("source_file") in task.files:
                        receipt.source_file = page["source_file"]
                    receipt.provenance = page.get("provenance", {})
                    receipt.total_chars = page["total_chars"]
                    await self._event("evidence_delivered", state, evidence_ref=page["evidence_ref"],
                                      operation_id=ticket, offset=span[0], end_offset=span[1])
            await self._save(state)
            if response.finish_reason != "stop" or response.refusal:
                raise IncompleteCompletion("provider_truncated" if response.finish_reason == "length" else "provider_incomplete",
                    recoverable=not response.refusal and response.finish_reason in {"length", "unknown"})
            return response.content

    @staticmethod
    def _provider_observation(response, max_output):
        """Bounded structural diagnostics, never source, response prose or thoughts."""
        try:
            value = json.loads(response.content)
            shape = "object" if isinstance(value, dict) else "other_json"
        except (ValueError, RecursionError):
            shape = "invalid_json" if response.content else "empty"
        return {"finish_reason": response.finish_reason if response.finish_reason in {
                    "stop", "length", "content_filter", "tool_calls", "unknown"} else "other",
                "content_chars": len(response.content), "json_shape": shape,
                "refusal": response.refusal, "requested_output_tokens": max_output,
                "reported_prompt_tokens": response.usage.prompt_tokens,
                "reported_completion_tokens": response.usage.completion_tokens,
                "reported_total_tokens": response.usage.total_tokens,
                "reported_reasoning_tokens": response.usage.reasoning_tokens}

    async def _investigate(self, state: AgentExecutionState) -> AgentExecutionState:
        task, private = state["task"], state["private_state"]
        try:
            if not state.get("retry_operation"):
                self.budget.consume_iteration(task.task_id)
                private.iteration_count += 1
                await self._event("iteration_started", state)
            await self._save(state)
            repair = bool(state.get("validation_error")) or (state.get("retry_operation") or "").endswith(".1")
            while True:
                try:
                    raw = await self._call_with_retries(state, repair=repair)
                except IncompleteCompletion as exc:
                    if task.agent_id != AgentId.PLANNER or not exc.recoverable:
                        raise
                    try:
                        self.budget.consume_schema_repair(task.task_id)
                    except BudgetExceeded:
                        return self._stop(state, str(exc))
                    state["validation_error"] = ("Previous provider response was incomplete. Return one complete JSON "
                        "AgentAction: kind=submit_plan, payload=ReviewPlan. Use the supplied repository metadata.")
                    await self._save(state)
                    await self._event("retry_started", state, attempt=2, stop_reason=str(exc))
                    repair = True
                    continue
                inspected = {ref: len(receipt.inspected) for ref, receipt in private.evidence_progress.items()}
                try:
                    state["action"] = self._parse_action(raw, state)
                    state["validation_error"] = ""
                    return state
                except ValueError as exc:
                    # Validation errors contain no source/tool payloads in the
                    # repair instruction; the specific invariant guides repair.
                    if isinstance(exc, ValidationError):
                        # Error inputs may contain private content; field paths
                        # and error types alone provide useful repair guidance.
                        fields = set(AgentAction.model_fields) | set(ReviewPlan.model_fields) | {"agent_id", "task_id", "files", "focus", "evidence_refs"}
                        state["validation_error"] = "Return a JSON action with kind and payload. " + "; ".join(
                            ".".join(str(part) if isinstance(part, int) or part in fields else "field" for part in error["loc"])
                            + ":" + error["type"] for error in exc.errors())[:155]
                    else:
                        state["validation_error"] = str(exc).splitlines()[0][:200]
                    await self._event("validation_failed", state, error_code="invalid_schema", outcome="failed")
                    try:
                        self.budget.consume_schema_repair(task.task_id)
                        await self._save(state)
                    except BudgetExceeded:
                        if isinstance(exc, (investigation.EvidenceInspectionRequired, CandidateSchemaError)):
                            private.quarantined_candidates.extend(item for item in exc.rejections if item not in private.quarantined_candidates)
                            reason = 'invalid_schema' if isinstance(exc, CandidateSchemaError) else 'evidence_incomplete'
                            await self._event("candidate_rejected", state, count=len(exc.rejections),
                                              error_code="invalid_schema", stop_reason=reason, outcome="failed")
                            return self._stop(state, reason, explanation=str(exc))
                        return self._stop(state, "invalid_schema")
                    repair = True
                finally:
                    for ref, receipt in private.evidence_progress.items():
                        for start, end in receipt.inspected[inspected.get(ref, 0):]:
                            await self._event("evidence_inspected", state, evidence_ref=ref, offset=start, end_offset=end)
        except EventPersistenceError:
            raise
        except PromptContextLimit:
            return self._stop(state, "prompt_context_limit")
        except ContextRetrievalTimeout:
            return self._stop(state, "context_timeout")
        except ToolFailure as exc:
            self._tool_diagnostic(state, exc)
            return self._stop(state, "tools_unavailable")
        except PermissionError:
            return self._stop(state, "permission_denied")
        except IncompleteCompletion as exc:
            return self._stop(state, str(exc))
        except BudgetExceeded:
            return self._stop(state, "budget_exhausted")
        except asyncio.CancelledError:
            await self._save(self._stop(state, "cancelled"))
            raise
        except Exception:
            return self._stop(state, "model_unavailable")
        finally:
            await self._save(state)

    async def _call_with_retries(self, state, *, repair):
        # A read-only model completion is replay-safe only for classified
        # throttling/server rejection. Timeout/unknown completion is never replayed.
        operation = state.get("retry_operation") or f"{state['task'].task_id}.{state['private_state'].iteration_count}.{int(repair)}"
        while True:
            try:
                # Once a call is dispatched its completion may be unknown. A
                # restart must not mistake that for the safe pending backoff.
                state["retry_operation"] = None
                return await self._call_model(state, repair=repair,
                    attempt=self.budget.ledger.operation_retries.get(operation, 0) + 1)
            except (ProviderRateLimitError, ProviderTemporaryError) as exc:
                if isinstance(exc, ProviderQuotaExhaustedError):
                    raise
                if exc.raw_error is not None:
                    status = getattr(exc.raw_error, "status_code", None)
                    if status is None:
                        status = getattr(getattr(exc.raw_error, "response", None), "status_code", None)
                    safe = {429} if isinstance(exc, ProviderRateLimitError) else {500, 502, 503}
                    if status not in safe:
                        raise
                if self.budget.ledger.operation_retries.get(operation, 0) >= self.budget.limits.transient_retries:
                    raise
                self.budget.consume_retry(operation, replay_safe=True)
                state["retry_operation"] = operation
                await self._save(state)
                await self._event("retry_started", state, operation_id=state.get("model_call_id"),
                    attempt=self.budget.ledger.operation_retries[operation] + 1)
                delay = .1 * self.budget.ledger.operation_retries[operation]
                await asyncio.sleep(min(delay, self.budget.timeout_for("provider")))

    async def _execute_action(self, state: AgentExecutionState) -> AgentExecutionState:
        task, private, action = state["task"], state["private_state"], state["action"]
        operation_id, observation, tool_error, started = None, None, None, None
        name = action.tool or "read_source"
        fingerprint = failure_identity(name, action.arguments, self.tools._arguments.get(name))
        repeated = any(item.fingerprint == fingerprint for item in private.tool_diagnostics)
        try:
            arguments = self.tools.authorize(task, action)
            if action.kind in {"call_tool", "request_context"}:
                action.arguments = arguments
                if repeated:
                    raise ToolFailure("repeated_tool_failure", "Repeated failed action blocked.", recoverable=False)
                if private.investigation is not None and investigation.stalled(private, fingerprint):
                    return self._stop(state, "no_progress", explanation="Repeated request adds no new acknowledged evidence.")
                self.budget.consume_tool(task.task_id)
                private.tool_call_count += 1
                await self._save(state)
                operation_id, started = uuid4().hex, time.monotonic()
                await self._event("tool_called", state, tool=action.tool or "read_source", operation_id=operation_id)
                if action.kind == "request_context":
                    # Context Manager retrieves selected references; no extra AI identity.
                    observation = ToolObservation.model_validate(await asyncio.wait_for(
                        _resolve(self.context(state)), timeout=self.budget.timeout_for("command")))
                else:
                    observation = await asyncio.wait_for(self.tools.execute(task, action),
                                                         timeout=self.budget.timeout_for("command"))
                if observation.evidence_ref in private.evidence_refs:
                    private.evidence_refs.remove(observation.evidence_ref)
                private.evidence_refs.append(observation.evidence_ref)
                private.evidence_cursors[observation.evidence_ref] = observation.offset
                private.evidence_page_sizes[observation.evidence_ref] = observation.max_chars
                receipt = private.evidence_progress.setdefault(observation.evidence_ref, EvidenceProgress())
                receipt.processed = True
                if private.investigation is not None:
                    investigation.observed(private, fingerprint, observation.evidence_ref)
                state["last_tool_error"] = None
            elif action.kind == "submit_candidates":
                output = SpecialistResult.model_validate(action.payload)
                private.local_findings = output.candidates
                private.quarantined_candidates = output.quarantined
                if output.candidates:
                    await self._event("candidate_submitted", state, count=len(output.candidates))
                if output.quarantined:
                    await self._event("candidate_rejected", state, count=len(output.quarantined),
                                      error_code="invalid_schema", outcome="failed")
                # Source inspection coverage comes from runtime observations, not
                # an agent claiming it inspected files which it never opened.
                for path in task.files:
                    if path not in private.coverage.inspected_files:
                        private.coverage.skipped[path] = "not_inspected"
                private.coverage.limitations.extend(output.coverage.limitations)
                return self._stop(state, output.stop_reason, explanation=output.stop_explanation)
            elif action.kind == "submit_plan":
                state["output"] = ReviewPlan.model_validate(action.payload)
                return self._stop(state, "evidence_complete")
            elif action.kind == "submit_verification":
                verified = VerificationPhaseResult.model_validate(action.payload)
                previous = state.get("verification")
                if previous is not None:
                    verified.decisions = previous.decisions + verified.decisions
                    verified.duplicate_groups = previous.duplicate_groups + verified.duplicate_groups
                    verified.conflicts = previous.conflicts + verified.conflicts
                    verified.followup_requests = previous.followup_requests + verified.followup_requests
                proposed = state.get("proposed_followups", [])
                # A proposal is never a dispatch or a separate agent.
                verified.followup_requests.extend(proposed)
                state["verification"] = verified
                for decision in VerificationPhaseResult.model_validate(action.payload).decisions:
                    await self._event("verification_completed", state, finding_id=decision.finding_id,
                                      verdict=decision.verdict, count=1)
                if not action.payload.get("decisions"):
                    await self._event("verification_completed", state, count=0)
                if {decision.finding_id for decision in verified.decisions} == set(state["candidates"]):
                    state["phase"] = "synthesis"
            elif action.kind == "request_followup":
                from devwatch.review.contracts import FollowupRequest
                state.setdefault("proposed_followups", []).append(FollowupRequest.model_validate(action.payload))
            elif action.kind == "submit_synthesis":
                state["output"] = VerificationSynthesisResult.model_validate(action.payload)
                return self._stop(state, "evidence_complete")
            elif action.kind == "finish":
                return self._stop(state, "finished_without_result")
            state["action"] = None
            return state
        except EventPersistenceError:
            raise
        except UnknownToolCompletion:
            tool_error = "unknown_tool_completion"
            self._tool_diagnostic(state, ToolFailure(tool_error, "Do not replay unknown completion.", recoverable=False), fingerprint)
            return self._stop(state, "unknown_tool_completion")
        except PermissionError as exc:
            tool_error = "permission_denied"
            self._tool_diagnostic(state, exc, fingerprint)
            return self._stop(state, "permission_denied")
        except BudgetExceeded:
            return self._stop(state, "budget_exhausted")
        except TimeoutError as exc:
            # A drained timeout may still have had effects. Never automatically
            # replay the action or claim that it produced evidence.
            tool_error = "tool_timeout"
            self._tool_diagnostic(state, exc, fingerprint)
            return self._stop(state, "tool_timeout")
        except (LookupError, ValueError, FileNotFoundError) as exc:
            if repeated:
                exc = ToolFailure("repeated_tool_failure", "Repeated failed action blocked.", recoverable=False)
            elif isinstance(exc, ValidationError) and operation_id is not None:
                # Admission already validated the arguments. A later schema
                # failure belongs to execution/results and may follow effects.
                exc = ToolFailure("tool_execution_failed", "Invalid tool execution result; do not replay.", recoverable=False)
            diagnostic = self._tool_diagnostic(state, exc, fingerprint)
            if not diagnostic.recoverable:
                tool_error = diagnostic.code
                return self._stop(state, "tools_unavailable")
            # These are known read failures, so another bounded action is safe.
            name = action.tool or "read_source"
            private.coverage.failed[f"{task.task_id}:{name}"] = "recoverable_tool_error"
            private.coverage.limitations.append(f"Tool {name} failed; no evidence was produced for that call.")
            # One bounded runtime receipt, not an exception string or reasoning
            # transcript. The next model action can correct arguments/tool choice.
            state["last_tool_error"] = {"tool": name, "code": "recoverable_tool_error"}
            tool_error = "recoverable_tool_error"
            await self._event("validation_failed", state, tool=name, error_code=tool_error, outcome="failed")
            state["action"] = None
            return state
        except asyncio.CancelledError:
            await self._save(self._stop(state, "cancelled"))
            raise
        except Exception as exc:
            tool_error = "execution_failed"
            self._tool_diagnostic(state, exc, fingerprint)
            return self._stop(state, "tools_unavailable")
        finally:
            if operation_id is not None:
                await self._event("tool_result", state, tool=action.tool or "read_source", operation_id=operation_id,
                    outcome="succeeded" if observation is not None else "cancelled" if private.stop_reason == "cancelled" else "failed",
                    error_code=tool_error, evidence_ref=observation.evidence_ref if observation is not None else None,
                    stop_reason=safe_stop_reason(private.stop_reason) if private.stop_reason else None,
                    duration_seconds=time.monotonic() - started)
                if observation is not None:
                    await self._event("evidence_retrieved", state, tool=action.tool or "read_source",
                                      evidence_ref=observation.evidence_ref, operation_id=operation_id, offset=observation.offset)
            await self._save(state)

    def _tool_diagnostic(self, state, error, fingerprint=None):
        task, private = state["task"], state["private_state"]
        action = state.get("action") or AgentAction(kind="call_tool",
            tool="read_evidence" if error.code.startswith("evidence") else "read_source", arguments=error.arguments)
        name = action.tool or "read_source"
        fingerprint = fingerprint or failure_identity(name, action.arguments, self.tools._arguments.get(name))
        diagnostic = diagnose(name if name in self.tools._arguments else "unrecognized_tool", action.arguments,
            task.files, error, fingerprint, replay_safe=self.tools._arguments.get(name) is not CommandArguments)
        private.tool_diagnostics = (private.tool_diagnostics + [diagnostic])[-8:]
        return diagnostic

    async def run_specialist(self, task: ReviewTask, *, private_state: AgentPrivateState | None = None,
                             complexity: float = 0, confidence: float = 1, restored_state: dict | None = None):
        private = (private_state or AgentPrivateState()).model_copy(deep=True)
        if private.current_task is not None and private.current_task != task.task_id:
            raise ValueError("private state belongs to another task")
        if private.coverage.failed.get(task.task_id) == "cancelled":
            private.coverage.failed.pop(task.task_id)
        private.current_task, private.stop_reason = task.task_id, None
        private.stop_explanation = ""
        investigation.begin(task, private)
        tier, escalations = ModelRouter.select(task.agent_id, complexity=complexity, confidence=confidence)
        state = {"task": task, "private_state": private, "action": None, "output": None,
                 "model_tier": tier, "escalation_count": escalations}
        if restored_state is not None:
            if restored_state.get("task") != task.model_dump(mode="json"):
                raise ValueError("specialist checkpoint belongs to another task scope")
            state["retry_operation"] = self._restored_retry(restored_state, private)
            state["last_tool_error"] = restored_state.get("last_tool_error")
            state["validation_error"] = restored_state.get("validation_error", "")
            state["provider_observations"] = restored_state.get("provider_observations", [])
            state['tool_selections']=restored_state.get('tool_selections',[])
        # Ambient SDK settings must not export graph state, prompts or source.
        # Optional observability uses a separate metadata-only integration.
        return await self._invoke(self.graphs[task.agent_id], state)

    async def _run_control(self, agent: AgentId, *, snapshot_id: str, files: list[str],
                           candidates=None, private_state: AgentPrivateState | None = None,
                           complexity: float = 0, confidence: float = 1, restored_state: dict | None = None,
                           review_tasks: set[str] | None = None):
        identity = "__planner" if agent == AgentId.PLANNER else "__final"
        private = (private_state or AgentPrivateState()).model_copy(deep=True)
        if private.current_task not in {None, identity}:
            raise ValueError("private state belongs to another task")
        if private.coverage.failed.get(identity) == "cancelled":
            private.coverage.failed.pop(identity)
        private.current_task, private.stop_reason = identity, None
        private.stop_explanation = ""
        tier, escalations = ModelRouter.select(agent, complexity=complexity, confidence=confidence)
        work = AgentWorkItem(task_id=identity, agent_id=agent, files=files,
                             focus="Plan review" if agent == AgentId.PLANNER else "Verify then synthesize")
        state = {"task": work, "private_state": private, "action": None, "output": None,
                 "snapshot_id": snapshot_id, "candidates": candidates or {}, "verification": None,
                 "phase": "planning" if agent == AgentId.PLANNER else "verification",
                 "model_tier": tier, "escalation_count": escalations}
        if review_tasks is not None:
            state["review_tasks"] = sorted(review_tasks)
        if restored_state is not None:
            if (restored_state.get("snapshot_id") != snapshot_id
                    or restored_state.get("candidates", {}) != (candidates or {})
                    or restored_state.get("task", {}).get("agent_id") != agent.value):
                raise ValueError("control checkpoint does not belong to the current input")
            if agent == AgentId.SYNTHESIZER_VERIFIER and restored_state.get("verification") is not None:
                state["verification"] = VerificationPhaseResult.model_validate(restored_state["verification"])
                state["phase"] = restored_state["phase"]
            state["proposed_followups"] = restored_state.get("proposed_followups", [])
            state["model_tier"] = ModelTier(restored_state.get("model_tier", tier))
            state["escalation_count"] = restored_state.get("escalation_count", escalations)
            state["retry_operation"] = self._restored_retry(restored_state, private)
            state["last_tool_error"] = restored_state.get("last_tool_error")
            state["validation_error"] = restored_state.get("validation_error", "")
            state["provider_observations"] = restored_state.get("provider_observations", [])
            state['tool_selections']=restored_state.get('tool_selections',[])
        return await self._invoke(self.control_graph, state)

    def _restored_retry(self, restored, private):
        operation = restored.get("retry_operation")
        if operation is not None:
            expected = {f"{private.current_task}.{private.iteration_count}.{repair}" for repair in (0, 1)}
            if operation not in expected or self.budget.ledger.operation_retries.get(operation, 0) < 1:
                raise ValueError("pending retry does not belong to persisted accounting")
        return operation

    async def run_planner(self, *, snapshot_id: str, files: list[str], **kwargs):
        return await self._run_control(AgentId.PLANNER, snapshot_id=snapshot_id, files=files, **kwargs)

    async def run_final(self, *, snapshot_id: str, files: list[str], candidates: dict[str, Any], **kwargs):
        return await self._run_control(AgentId.SYNTHESIZER_VERIFIER, snapshot_id=snapshot_id,
                                       files=files, candidates=candidates, **kwargs)
