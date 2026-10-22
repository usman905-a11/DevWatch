"""Completion-first graph tail and deterministic, non-publishing report rendering.

The upstream structural evidence gate supplies snapshot-validated candidate and
evidence indexes. This gate checks final draft consistency, not evidence integrity
alone as proof of correctness. Model review and computed arithmetic are distinct.
"""

import html
import inspect
import json
import re
import asyncio
import time
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from devwatch.review.budgets import BudgetManager
from devwatch.review.contracts import (
    AgentId, Coverage, FindingCandidate, FollowupRequest, ReportDraft, ReportFinding, ReviewTask,
    VerificationDecision, VerificationSynthesisResult, VerificationAudit, VerificationPhaseResult,
)
from devwatch.review.verification import validate_decision, validate_relations, arithmetic_receipts


class AcceptanceError(ValueError):
    pass


_ACCEPTANCE_TOKEN = object()


class AcceptedReport:
    """An immutable serialized draft returned only after acceptance."""
    __slots__ = ("_data",)

    def __init__(self, draft: ReportDraft, *, _token: object):
        if _token is not _ACCEPTANCE_TOKEN:
            raise TypeError("reports must pass the acceptance gate")
        self._data = json.dumps(draft.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, allow_nan=False)

    @property
    def draft(self) -> ReportDraft:
        return ReportDraft.model_validate_json(self._data)


class FinalAcceptanceGate:
    def __init__(self, candidates: dict[str, FindingCandidate], *, evidence_refs: set[str] | None = None,
                 inspected_evidence: set[str] | None = None, snapshot_id: str | None = None,
                 duplicate_groups=(), verification=None, provenance=None, allow_unreviewed=False,
                 require_independent_support=False):
        self.candidates = {key: value.model_copy(deep=True) for key, value in candidates.items()}
        self.evidence_refs = frozenset(evidence_refs or ())
        self.inspected_evidence = frozenset(inspected_evidence or ())
        self.snapshot_id = snapshot_id
        self.duplicate_groups = tuple(tuple(group) for group in duplicate_groups)
        self.verification = (VerificationPhaseResult(**{field: getattr(verification, field)
            for field in VerificationPhaseResult.model_fields}) if verification is not None else None)
        self.provenance = dict(provenance or {})
        self.allow_unreviewed = allow_unreviewed
        self.require_independent_support = require_independent_support

    def accept(self, draft: ReportDraft, decisions: list[VerificationDecision]) -> AcceptedReport:
        draft = ReportDraft.model_validate(draft.model_dump())
        decisions = [VerificationDecision.model_validate(decision.model_dump()) for decision in decisions]
        if ((self.snapshot_id is not None and draft.snapshot_id != self.snapshot_id)
                or any(candidate.location.snapshot_id != draft.snapshot_id for candidate in self.candidates.values())):
            raise AcceptanceError("report snapshot differs from immutable input")
        by_id = {decision.finding_id: decision for decision in decisions}
        if len(by_id) != len(decisions):
            raise AcceptanceError("duplicate verification decisions")
        if set(by_id) != set(self.candidates):
            raise AcceptanceError("every candidate must receive a verification decision")
        for decision in decisions:
            if self.require_independent_support and decision.verdict in {'confirmed', 'advisory'}:
                raise AcceptanceError('Positive publication requires independent whole-claim support, not model agreement.')
            if (self.require_independent_support and decision.verdict == 'rejected' and not any(
                    receipt.result.status == 'contradicted' for receipt in arithmetic_receipts(
                        self.candidates[decision.finding_id], decision.arithmetic_counterexamples))):
                raise AcceptanceError('Rejection requires an independent contradiction; model-only disputes remain uncertain.')
            try:
                validate_decision(self.candidates[decision.finding_id], decision,
                                  allow_unreviewed=self.allow_unreviewed)
            except ValueError as exc:
                raise AcceptanceError(str(exc)) from exc
            if decision.verdict != "rejected" and (not decision.evidence_refs or not set(decision.evidence_refs).issubset(self.evidence_refs)):
                raise AcceptanceError("decision cites unknown evidence")
            if (decision.verdict != 'rejected' and decision.causal_review is not None
                    and not set(decision.evidence_refs).issubset(self.inspected_evidence)):
                raise AcceptanceError("reviewed decision lacks verifier inspection")
        seen = set()
        buckets = (
            (draft.confirmed_defects, "confirmed", "defect"),
            (draft.uncertain_high_impact_candidates, "uncertain", "high_impact_candidate"),
            (draft.advisories, "advisory", "advisory"),
        )
        for findings, verdict, kind in buckets:
            for finding in findings:
                candidate, decision = self.candidates.get(finding.finding_id), by_id.get(finding.finding_id)
                if candidate is None or decision is None or finding.finding_id in seen:
                    raise AcceptanceError("unknown or duplicate final finding")
                seen.add(finding.finding_id)
                if finding.location.snapshot_id != draft.snapshot_id:
                    raise AcceptanceError("finding belongs to a different snapshot")
                for field in ("location", "title", "description", "impact", "category", "remediation", "arithmetic_claims"):
                    if getattr(finding, field) != getattr(candidate, field):
                        raise AcceptanceError("final claim differs from the verified candidate")
                if decision.verdict != verdict or finding.kind != kind:
                    raise AcceptanceError("finding classification does not match verification")
                if finding.verification_rationale != decision.rationale:
                    raise AcceptanceError("rationale differs from verification")
                refs = set(finding.evidence_refs)
                if (not refs or not refs.issubset(self.evidence_refs)
                        or refs != set(decision.evidence_refs)):
                    raise AcceptanceError("final finding lacks verified evidence references")
                if finding.confidence > decision.confidence:
                    raise AcceptanceError("draft overstates verified confidence")
                if verdict == "confirmed" and min(finding.confidence, decision.confidence) < 0.8:
                    raise AcceptanceError("confirmed confidence is below 0.8")
        expected = _report_ids(self.candidates, decisions, self.duplicate_groups)
        if seen != expected:
            raise AcceptanceError("draft dropped a non-rejected verification decision or retained a verified duplicate")
        metadata = self.verification.model_dump() if self.verification is not None else {}
        metadata.update(decisions=decisions, duplicate_groups=[list(group) for group in self.duplicate_groups],
                        provenance=self.provenance)
        audit = VerificationAudit.model_validate(metadata)
        audit.arithmetic_checks = {identity: arithmetic_receipts(candidate, by_id[identity].arithmetic_counterexamples)
            for identity, candidate in self.candidates.items() if candidate.arithmetic_claims}
        try:
            validate_relations(self.candidates, audit, self.inspected_evidence)
        except ValueError as exc:
            raise AcceptanceError(str(exc)) from exc
        if draft.verification_audit is not None and draft.verification_audit != audit:
            raise AcceptanceError('Synthesis cannot alter verification audit or specialist provenance.')
        draft.verification_audit = audit
        if self.candidates:
            note = ('Independent arithmetic checks cover only explicit predicates on their declared integer domains. '
                    'Source relevance and other prose remain model judgments, not independently proven facts.')
            if note not in draft.limitations:
                draft.limitations.append(note)
        draft.limitations.extend(note for note in audit.conflicts if note not in draft.limitations)
        notes = ['Unresolved disagreement: ' + item.rationale for item in audit.disagreements
                 if item.resolution == 'unresolved']
        draft.limitations.extend(note for note in notes if note not in draft.limitations)
        draft.summary = report_summary(draft)
        return AcceptedReport(draft, _token=_ACCEPTANCE_TOKEN)


def report_summary(draft):
    partial = bool(draft.coverage.skipped or draft.coverage.failed or draft.coverage.limitations
                   or draft.limitations or draft.uncertain_high_impact_candidates)
    return (('Partial review: ' if partial else 'Scoped review: ')
            + f'{len(draft.confirmed_defects)} confirmed defect(s), '
              f'{len(draft.uncertain_high_impact_candidates)} uncertain candidate(s), '
              f'{len(draft.advisories)} advisory finding(s). '
              f'{len(draft.coverage.inspected_files)} captured source file(s) inspected; '
              f'{len(draft.coverage.skipped)} skipped and {len(draft.coverage.failed)} failed coverage entry/entries. '
              'Coverage applies only to the captured source and recorded evidence.')


def _report_ids(candidates, decisions, duplicate_groups):
    """Select representatives only from authoritative verifier duplicate groups.

    Keep all decisions for audit and validation. Overlapping groups form one
    component; prefer confirmation, then confidence, then a stable identity.
    """
    by_id = {decision.finding_id: decision for decision in decisions}
    expected = {identity for identity, decision in by_id.items() if decision.verdict != "rejected"}
    components = []
    for group in duplicate_groups:
        members = set(group)
        if (len(group) < 2 or len(members) != len(group)
                or not members.issubset(candidates) or not members.issubset(by_id)):
            raise AcceptanceError("duplicate groups require distinct known verified candidates")
        disjoint = []
        for component in components:
            if members & component:
                members |= component
            else:
                disjoint.append(component)
        components = [*disjoint, members]
    priority = {"confirmed": 0, "uncertain": 1, "advisory": 2}
    for component in components:
        eligible = component & expected
        if eligible:
            representative = min(eligible, key=lambda identity: (
                priority[by_id[identity].verdict], -by_id[identity].confidence, identity))
            expected -= eligible - {representative}
    return expected


def assemble_report(snapshot_id, candidates, decisions, *, summary, coverage=None, limitations=(), duplicate_groups=()):
    """Keep claims, IDs and decisions runtime-owned; the model writes only prose."""
    draft = ReportDraft(snapshot_id=snapshot_id, summary=summary,
                        coverage=(coverage or Coverage()).model_copy(deep=True), limitations=list(limitations))
    buckets = {"confirmed": ("confirmed_defects", "defect"),
               "uncertain": ("uncertain_high_impact_candidates", "high_impact_candidate"),
               "advisory": ("advisories", "advisory")}
    expected = _report_ids(candidates, decisions, duplicate_groups)
    for decision in decisions:
        if decision.finding_id not in expected:
            continue
        candidate = candidates[decision.finding_id]
        claim = candidate.model_dump() if isinstance(candidate, FindingCandidate) else dict(candidate)
        bucket, kind = buckets[decision.verdict]
        claim.update(kind=kind, confidence=decision.confidence, evidence_refs=decision.evidence_refs)
        getattr(draft, bucket).append(ReportFinding(**claim, finding_id=decision.finding_id,
                                                   verification_rationale=decision.rationale))
    return draft


def _markdown_text(value: str) -> str:
    escaped = html.escape(value, quote=False)
    return re.sub(r"([\\`*{}\[\]()#+.!|_])", r"\\\1", escaped).replace("\r", "").replace("\n", " ")


def render_accepted_report(report: AcceptedReport) -> dict[str, str]:
    if not isinstance(report, AcceptedReport):
        raise TypeError("renderer requires an accepted structured draft")
    draft = report.draft
    lines = ["# DevWatch review", "", _markdown_text(draft.summary), ""]
    for title, findings in (
        ("Confirmed defects", draft.confirmed_defects),
        ("Uncertain high-impact candidates", draft.uncertain_high_impact_candidates),
        ("Advisories", draft.advisories),
    ):
        lines.extend([f"## {title}", ""])
        if not findings:
            lines.extend(["None reported.", ""])
        for finding in sorted(findings, key=lambda f: (f.location.file_path, f.location.start_line, f.finding_id)):
            location = finding.location
            lines.extend([
                f"### {_markdown_text(finding.title)}", "",
                f"Location: {_markdown_text(location.file_path)}:{location.start_line}-{location.end_line}",
                f"Description: {_markdown_text(finding.description)}",
                f"Impact: {_markdown_text(finding.impact)}",
                f"Evidence: {_markdown_text(', '.join(finding.evidence_refs))}",
                f"Verification: {_markdown_text(finding.verification_rationale)}",
                f"Confidence: {finding.confidence:.2f}",
                f"Remediation: {_markdown_text(finding.remediation)}", "",
            ])
    lines.extend(["## Coverage", "", f"Files inspected: {len(draft.coverage.inspected_files)}",
                  f"Symbols inspected: {len(draft.coverage.inspected_symbols)}"])
    for label, entries in (("Skipped", draft.coverage.skipped), ("Failed", draft.coverage.failed)):
        for path, reason in sorted(entries.items()):
            lines.append(f"- {label}: {_markdown_text(path)} — {_markdown_text(reason)}")
    if draft.verification_audit is not None:
        lines.extend(['', '## Verification audit', ''])
        for decision in draft.verification_audit.decisions:
            origin = draft.verification_audit.provenance.get(decision.finding_id)
            contributor = f'{origin.agent_id.value}/{origin.task_id}' if origin else 'origin not recorded'
            lines.append(_markdown_text(f'{decision.finding_id}: {decision.verdict}; {contributor}; {decision.rationale}'))
            if decision.causal_review is not None:
                lines.append(_markdown_text(decision.causal_review.causal_basis))
                lines.extend(_markdown_text(f'{item.field}: {item.status}; {item.explanation}')
                             for item in decision.causal_review.assessments)
        for group in draft.verification_audit.duplicate_reviews:
            lines.append(_markdown_text(f'Equivalent findings: {", ".join(group.finding_ids)}; {group.rationale}'))
        for conflict in draft.verification_audit.disagreements:
            lines.append(_markdown_text(f'Disagreement {conflict.resolution}: {", ".join(conflict.finding_ids)}; {conflict.rationale}'))
        for observation in draft.verification_audit.review_observations:
            record = observation.decision
            lines.append(_markdown_text(f'Model review {observation.pass_number}: {record.finding_id}; {record.verdict}; {record.rationale}'))
        for identity, receipts in draft.verification_audit.arithmetic_checks.items():
            for receipt in receipts:
                result = receipt.result
                lines.append(_markdown_text(f'Independent arithmetic {identity}/{receipt.field}: {result.status}; '
                    f'{result.checked_assignments} assignments; {receipt.statement}; '
                    f'counterexample={result.counterexample}; {result.reason}'))
    limitations = sorted(set(draft.limitations + draft.coverage.limitations))
    if limitations:
        lines.extend(["", "## Limitations", ""])
        lines.extend(f"- {_markdown_text(item)}" for item in limitations)
    return {"json": report._data, "markdown": "\n".join(lines).rstrip() + "\n"}


class FinalizationState(TypedDict, total=False):
    round_number: int
    synthesis_result: VerificationSynthesisResult
    followup: FollowupRequest | None
    finalized: bool
    report_draft: ReportDraft
    accepted: AcceptedReport
    rendered: dict[str, str]


class CompletionAssessment:
    def __init__(self, budget: BudgetManager, tasks: dict[str, ReviewTask]):
        self.budget, self.tasks = budget, dict(tasks)

    def select_followup(self, result: VerificationSynthesisResult, round_number: int) -> FollowupRequest | None:
        self.budget.refresh_time()
        limits, ledger = self.budget.limits, self.budget.ledger
        if (max(round_number, ledger.review_round) >= limits.review_rounds
                or ledger.elapsed_seconds >= limits.review_seconds):
            return None
        reserved = sum(ticket.tokens for ticket in ledger.inflight.values())
        final_used = ledger.agent_usage.get(AgentId.SYNTHESIZER_VERIFIER)
        final_reserve = max(0, limits.final_agent_tokens - (final_used.total_tokens if final_used else 0))
        if ledger.total_tokens + reserved + final_reserve >= limits.job_tokens:
            return None
        for request in sorted(result.followup_requests, key=lambda request: (request.task_id, request.question)):
            task = self.tasks.get(request.task_id)
            if task is None:
                continue
            usage = ledger.agent_usage.get(task.agent_id)
            if usage is not None and usage.total_tokens >= limits.specialist_tokens:
                continue
            if (ledger.task_iterations.get(task.task_id, 0) < limits.iterations_per_task
                    and ledger.task_tools.get(task.task_id, 0) < limits.tool_calls_per_task):
                return request
        return None


async def _resolve(value):
    return await value if inspect.isawaitable(value) else value


class FinalizationWorkflow:
    def __init__(self, synthesize: Callable, followup: Callable, accept: Callable, *,
                 budget: BudgetManager, tasks: dict[str, ReviewTask], renderer: Callable = render_accepted_report,
                 persist: Callable[[dict[str, Any]], Any] | None = None,
                 admit: Callable | None = None, emit: Callable | None = None):
        self.synthesize, self.followup, self.accept, self.renderer = synthesize, followup, accept, renderer
        self.assessment = CompletionAssessment(budget, tasks)
        self.persist = persist
        self.admit = admit
        self.emit = emit
        builder = StateGraph(FinalizationState)
        builder.add_node("synthesizer_verifier", self._synthesize)
        builder.add_node("completion_assessment", self._assess)
        builder.add_node("targeted_followup", self._followup)
        builder.add_node("finalize", self._finalize)
        builder.add_node("structured_report_draft", self._draft)
        builder.add_node("final_acceptance_gate", self._accept)
        builder.add_node("deterministic_report_renderer", self._render)
        builder.add_edge(START, "synthesizer_verifier")
        builder.add_edge("synthesizer_verifier", "completion_assessment")
        builder.add_conditional_edges("completion_assessment", lambda state: "targeted_followup" if state["followup"] else "finalize")
        builder.add_edge("targeted_followup", "synthesizer_verifier")
        builder.add_edge("finalize", "structured_report_draft")
        builder.add_edge("structured_report_draft", "final_acceptance_gate")
        builder.add_edge("final_acceptance_gate", "deterministic_report_renderer")
        builder.add_edge("deterministic_report_renderer", END)
        # Acceptance capabilities are process-local objects. The root persists
        # structured progress/results, never a serialized gate bypass token.
        self.graph = builder.compile(checkpointer=False)

    async def _synthesize(self, state):
        return {"synthesis_result": VerificationSynthesisResult.model_validate(await _resolve(self.synthesize(state)))}

    async def _assess(self, state):
        followup = self.assessment.select_followup(state["synthesis_result"], state["round_number"])
        if followup is not None:
            self.assessment.budget.admit_followup()
            if self.admit is not None:
                await _resolve(self.admit(followup, self.assessment.budget.ledger.model_dump(mode="json")))
            if self.persist is not None:
                await _resolve(self.persist(self.assessment.budget.ledger.model_dump(mode="json")))
        return {"followup": followup, "round_number": self.assessment.budget.ledger.review_round}

    async def _followup(self, state):
        # Completion Assessment has already persisted cumulative admission.
        await _resolve(self.followup(state))
        return {}

    def _finalize(self, state):
        return {"finalized": True}

    def _draft(self, state):
        if not state["finalized"]:
            raise RuntimeError("completion assessment has not finalized the review")
        draft = state["synthesis_result"].report_draft.model_copy(deep=True)
        authoritative = state["synthesis_result"].coverage_summary
        explanations = list(draft.coverage.limitations)
        draft.coverage = authoritative.model_copy(deep=True)
        draft.coverage.limitations = sorted(set(explanations + authoritative.limitations))
        if state["synthesis_result"].followup_requests:
            draft.limitations.append("Unresolved questions remain; targeted follow-up unavailable or round limit reached.")
        return {"report_draft": draft}

    async def _accept(self, state):
        if not state["finalized"]:
            raise RuntimeError("cannot accept an unfinished review")
        try:
            accepted = await _resolve(self.accept(state["report_draft"], state["synthesis_result"].decisions))
        except Exception:
            await self._event("validation_failed", phase="acceptance", outcome="failed")
            raise
        await self._event("validation_passed", phase="acceptance", outcome="succeeded")
        return {"accepted": accepted}

    async def _render(self, state):
        started, outcome = time.monotonic(), "failed"
        await self._event("report_render_started", phase="rendering")
        try:
            rendered = await _resolve(self.renderer(state["accepted"]))
            outcome = "succeeded"
            return {"rendered": rendered}
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        finally:
            await self._event("report_render_completed", phase="rendering", outcome=outcome,
                              duration_seconds=time.monotonic() - started)

    async def _event(self, kind, **metadata):
        if self.emit is not None:
            await _resolve(self.emit(kind, **metadata))

    async def run(self):
        started, outcome = time.monotonic(), "failed"
        await self._event("finalization_started", phase="finalization")
        try:
            with tracing_context(enabled=False, parent=False):
                result = await self.graph.ainvoke({"round_number": self.assessment.budget.ledger.review_round,
                                                  "finalized": False, "followup": None})
            outcome = "succeeded"
            return result
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        finally:
            await self._event("finalization_completed", phase="finalization", outcome=outcome,
                              duration_seconds=time.monotonic() - started)
