"""Completion decides before draft acceptance and deterministic rendering."""

import asyncio
import importlib
import json

import pytest

from devwatch.review.budgets import BudgetManager
from devwatch.review.contracts import (
    AgentId, Coverage, FindingCandidate, ReportDraft, ReportFinding, ReviewTask,
    VerificationDecision, VerificationSynthesisResult,
)


def finalization():
    assert importlib.util.find_spec("devwatch.review.finalization"), "Finalization workflow is missing"
    return importlib.import_module("devwatch.review.finalization")


def draft():
    return ReportDraft(snapshot_id="snapshot-1", summary="Review complete", coverage=Coverage())


def test_one_followup_precedes_final_acceptance_and_rendering():
    api = finalization()
    async def scenario():
        trace = []
        async def synthesize(state):
            trace.append("synthesizer_verifier")
            return VerificationSynthesisResult(decisions=[], report_draft=draft(), coverage_summary=Coverage(),
                followup_requests=[{"task_id": "t1", "question": "Does empty input fail?", "evidence_needed": "boundary test"}])
        async def followup(state):
            trace.append("targeted_followup")
            assert state["round_number"] == 2
        def accept(report, decisions):
            trace.append("final_acceptance")
            return api.FinalAcceptanceGate({}).accept(report, decisions)
        def render(report):
            trace.append("renderer")
            return api.render_accepted_report(report)
        task = ReviewTask(task_id="t1", agent_id=AgentId.LOGIC_CORRECTNESS, files=["service.py"], focus="empty input")
        workflow = api.FinalizationWorkflow(synthesize, followup, accept, budget=BudgetManager(),
                                            tasks={"t1": task}, renderer=render)
        result = await workflow.run()
        assert trace == ["synthesizer_verifier", "targeted_followup", "synthesizer_verifier", "final_acceptance", "renderer"]
        assert result["finalized"] is True
        assert result["round_number"] == 2
        assert result["report_draft"].limitations
        assert json.loads(result["rendered"]["json"])["snapshot_id"] == "snapshot-1"
    asyncio.run(scenario())


def test_exhausted_task_does_not_trigger_followup():
    api = finalization()
    async def scenario():
        budget = BudgetManager()
        for _ in range(8):
            budget.consume_iteration("t1")
        async def synthesize(state):
            return VerificationSynthesisResult(decisions=[], report_draft=draft(), coverage_summary=Coverage(),
                followup_requests=[{"task_id": "t1", "question": "Missing boundary evidence", "evidence_needed": "test"}])
        async def forbidden_followup(state):
            raise AssertionError("exhausted task was retried")
        task = ReviewTask(task_id="t1", agent_id=AgentId.BUG_RELIABILITY, files=["service.py"], focus="boundary")
        gate = api.FinalAcceptanceGate({})
        workflow = api.FinalizationWorkflow(synthesize, forbidden_followup, gate.accept, budget=budget, tasks={"t1": task})
        result = await workflow.run()
        assert result["round_number"] == 1
        assert "follow-up unavailable" in " ".join(result["report_draft"].limitations)
    asyncio.run(scenario())


def finding():
    return FindingCandidate(category="bug", title="<script>alert(1)</script>", description="Empty input indexes item 0",
        impact="Request crashes", confidence=0.9, evidence_refs=["ev1"],
        location={"snapshot_id": "snapshot-1", "file_path": "service.py", "start_line": 2, "end_line": 2})


def report_with(candidate):
    report = draft()
    report.confirmed_defects = [ReportFinding(**candidate.model_dump(), finding_id="f1", verification_rationale="Reproduced failure")]
    return report


def test_acceptance_requires_known_candidates_verified_evidence_and_confidence():
    api = finalization()
    candidate = finding()
    report = report_with(candidate)
    decision = VerificationDecision(finding_id="f1", verdict="confirmed", confidence=0.9,
                                    rationale="Reproduced failure", evidence_refs=["ev1"])
    gate = api.FinalAcceptanceGate({"f1": candidate}, evidence_refs={"ev1"}, inspected_evidence={"ev1"})
    assert gate.accept(report, [decision]).draft.confirmed_defects[0].finding_id == "f1"
    for invalid in (
        decision.model_copy(update={"confidence": 0.79}),
        decision.model_copy(update={"verdict": "uncertain"}),
        decision.model_copy(update={"evidence_refs": []}),
    ):
        with pytest.raises(api.AcceptanceError):
            gate.accept(report, [invalid])
    with pytest.raises(api.AcceptanceError):
        api.FinalAcceptanceGate({}, evidence_refs={"ev1"}, inspected_evidence={"ev1"}).accept(report, [decision])
    with pytest.raises(api.AcceptanceError):
        api.FinalAcceptanceGate({"f1": candidate}).accept(report, [decision])


def test_renderer_accepts_only_gate_output_and_escapes_model_text():
    api = finalization()
    candidate = finding()
    report = report_with(candidate)
    decision = VerificationDecision(finding_id="f1", verdict="confirmed", confidence=0.9,
                                    rationale="Reproduced failure", evidence_refs=["ev1"])
    with pytest.raises(TypeError):
        api.render_accepted_report(report)
    accepted = api.FinalAcceptanceGate({"f1": candidate}, evidence_refs={"ev1"}, inspected_evidence={"ev1"}).accept(report, [decision])
    first, second = api.render_accepted_report(accepted), api.render_accepted_report(accepted)
    assert first == second
    assert "<script>" not in first["markdown"]
    assert "&lt;script&gt;" in first["markdown"]
    assert json.loads(first["json"])["confirmed_defects"][0]["title"] == candidate.title


def test_acceptance_cannot_drop_verified_or_undecided_candidates():
    api = finalization()
    gate = api.FinalAcceptanceGate({"f1": finding()}, evidence_refs={"ev1"}, inspected_evidence={"ev1"})
    decision = VerificationDecision(finding_id="f1", verdict="confirmed", confidence=0.9,
                                    rationale="Reproduced failure", evidence_refs=["ev1"])
    with pytest.raises(api.AcceptanceError):
        gate.accept(draft(), [decision])
    with pytest.raises(api.AcceptanceError):
        gate.accept(draft(), [])


def test_followup_round_admission_survives_restored_budget():
    api = finalization()
    from devwatch.review.budgets import BudgetLedger
    async def scenario():
        calls, saved = [], []
        budget = BudgetManager()
        async def synthesize(state):
            return VerificationSynthesisResult(decisions=[], report_draft=draft(), coverage_summary=Coverage(),
                followup_requests=[{"task_id": "t1", "question": "Boundary failure?", "evidence_needed": "test"}])
        async def followup(state):
            assert saved[-1]["review_round"] == 2
            calls.append("followup")
        task = ReviewTask(task_id="t1", agent_id=AgentId.BUG_RELIABILITY, files=["service.py"], focus="boundary")
        gate = api.FinalAcceptanceGate({})
        first = api.FinalizationWorkflow(synthesize, followup, gate.accept, budget=budget, tasks={"t1": task},
                                        persist=lambda ledger: saved.append(ledger))
        await first.run()
        restored = BudgetManager(ledger=BudgetLedger.model_validate(saved[-1]))
        second = api.FinalizationWorkflow(synthesize, followup, gate.accept, budget=restored, tasks={"t1": task})
        assert (await second.run())["round_number"] == 2
        assert calls == ["followup"]
    asyncio.run(scenario())


def test_final_draft_preserves_authoritative_failed_and_skipped_coverage():
    api = finalization()
    async def scenario():
        async def synthesize(state):
            return VerificationSynthesisResult(decisions=[], report_draft=draft(),
                coverage_summary=Coverage(failed={"service.py": "tool unavailable"},
                                          skipped={"index.ts": "budget"}, limitations=["No tests ran"]))
        async def followup(state):
            raise AssertionError("no followup requested")
        workflow = api.FinalizationWorkflow(synthesize, followup, api.FinalAcceptanceGate({}).accept,
                                            budget=BudgetManager(), tasks={})
        state = await workflow.run()
        assert state["report_draft"].coverage.failed == {"service.py": "tool unavailable"}
        assert state["report_draft"].coverage.skipped == {"index.ts": "budget"}
        assert "No tests ran" in state["rendered"]["markdown"]
    asyncio.run(scenario())


def test_markdown_preserves_escaped_causal_description():
    api = finalization()
    candidate = finding()
    candidate.description = "Empty input <script>crashes</script> when indexing [0]."
    accepted = api.FinalAcceptanceGate({"f1": candidate}, evidence_refs={"ev1"}, inspected_evidence={"ev1"}).accept(report_with(candidate), [
        VerificationDecision(finding_id="f1", verdict="confirmed", confidence=0.9,
                             rationale="Reproduced failure", evidence_refs=["ev1"])])
    rendered = api.render_accepted_report(accepted)["markdown"]
    assert "Empty input &lt;script&gt;crashes&lt;/script&gt; when indexing \\[0\\]" in rendered
    assert "<script>" not in rendered
