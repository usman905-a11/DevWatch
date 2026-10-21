"""Verified duplicate groups must survive assembly and durable acceptance."""

import json

import pytest

from devwatch.review.contracts import VerificationDecision, VerificationPhaseResult
from devwatch.review.finalization import AcceptanceError, FinalAcceptanceGate, FinalizationWorkflow, assemble_report
from devwatch.review.jobs import DurableJobManager
from tests.test_finalization_workflow import finding
from tests.test_m14_runtime import MultipleTasksProvider, executor_for, stores
from tests.verification_fixtures import reviewed


def claims():
    candidates = {identity: finding() for identity in ("a", "b", "c")}
    decisions = [VerificationDecision(finding_id=identity, verdict="confirmed", confidence=confidence,
        rationale="Source and contract establish the failure", evidence_refs=["ev1"],
        causal_review=reviewed(candidates[identity], ['ev1']))
        for identity, confidence in (("a", .8), ("b", .95), ("c", .9))]
    return candidates, decisions


def gate(candidates, groups=()):
    verification = VerificationPhaseResult(decisions=[], duplicate_groups=groups,
        duplicate_reviews=[dict(finding_ids=group, rationale='Same empty-index cause and source location.',
            evidence_refs=['ev1']) for group in groups])
    return FinalAcceptanceGate(candidates, evidence_refs={"ev1"}, inspected_evidence={"ev1"},
                               snapshot_id="snapshot-1", duplicate_groups=groups, verification=verification)


def test_transitive_verified_duplicates_choose_strongest_claim_without_rewriting_it():
    candidates, decisions = claims()
    groups = [["a", "b"], ["c", "a"]]
    report = assemble_report("snapshot-1", candidates, decisions, summary="Reviewed", duplicate_groups=groups)
    assert [item.finding_id for item in report.confirmed_defects] == ["b"]
    assert report.confirmed_defects[0].description == candidates["b"].description
    assert gate(candidates, list(reversed(groups))).accept(report, decisions).draft.confirmed_defects == report.confirmed_defects
    assert len(decisions) == 3  # Publication never erases verification records.
    with pytest.raises(AcceptanceError):
        gate(candidates).accept(report, decisions)


def test_duplicate_group_cannot_hide_a_disagreement_in_verification():
    candidates, decisions = claims()
    decisions[1].verdict = "uncertain"
    report = assemble_report("snapshot-1", candidates, decisions, summary="Reviewed", duplicate_groups=[["a", "b"]])
    assert [item.finding_id for item in report.confirmed_defects] == ["a", "c"]
    assert not report.uncertain_high_impact_candidates
    with pytest.raises(AcceptanceError):
        gate(candidates, [["a", "b"]]).accept(report, decisions)


@pytest.mark.parametrize("group", [["a", "unknown"], ["a", "a"], ["a"]])
def test_invalid_duplicate_groups_cannot_suppress_findings(group):
    candidates, decisions = claims()
    with pytest.raises(AcceptanceError):
        assemble_report("snapshot-1", candidates, decisions, summary="Reviewed", duplicate_groups=[group])


def test_suppressed_duplicate_still_requires_verifier_inspection():
    candidates, decisions = claims()
    report = assemble_report("snapshot-1", candidates, decisions, summary="Reviewed", duplicate_groups=[["a", "b"]])
    decisions[0].evidence_refs = ["uninspected"]
    with pytest.raises(AcceptanceError):
        gate(candidates, [["a", "b"]]).accept(report, decisions)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["normal", "synthesis_failure", "inconsistent_draft"])
async def test_full_graph_preserves_duplicates_through_normal_and_partial_acceptance(tmp_path, monkeypatch, mode):
    if mode == "inconsistent_draft":
        original = FinalizationWorkflow._draft
        def inconsistent(self, state):
            output = original(self, state)
            output["report_draft"].uncertain_high_impact_candidates[0].title = "Unverified rewrite"
            output["report_draft"].coverage.failed["earlier_task"] = "specialist_failed"
            return output
        monkeypatch.setattr(FinalizationWorkflow, "_draft", inconsistent)
    class DuplicatesProvider(MultipleTasksProvider):
        async def generate_completion(self, request):
            body = json.loads(request.prompt)
            response = await super().generate_completion(request)
            action = json.loads(response.content)
            if body["phase"] == "verification":
                action["payload"]["duplicate_groups"] = [list(body["candidates"])]
                action['payload']['duplicate_reviews'] = [dict(finding_ids=list(body['candidates']),
                    rationale='Same unguarded empty index and caller-contract evidence gap.',
                    evidence_refs=next(iter(body['candidates'].values()))['evidence_refs'])]
            elif body["phase"] == "synthesis":
                action = {"kind": "submit_synthesis", "payload": {"summary": "One issue", "limitations": []}}
                if mode == "synthesis_failure":
                    action["payload"] = {"invalid": True}
            return response.model_copy(update={"content": json.dumps(action)})
    layout, artifacts, snapshot, jobs, events = stores(tmp_path)
    executor = executor_for(layout, artifacts, jobs, events, DuplicatesProvider(["logic-a", "logic-b"]))
    manager = DurableJobManager(jobs, events, executor)
    try:
        job = await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="duplicates")
        done = await manager.wait(job.job_id, owner="alice")
    finally:
        await manager.close()
    assert done.status == "completed" and not done.ledger.inflight
    report = json.loads(done.result["json"])
    assert len(report["uncertain_high_impact_candidates"]) == 1
    assert bool(report["coverage"]["failed"]) == (mode != "normal")
    if mode == "synthesis_failure":
        assert report["coverage"]["failed"]["__final"] == "invalid_schema"
    elif mode == "inconsistent_draft":
        assert report["coverage"]["failed"] == {"earlier_task": "specialist_failed", "__final": "final_consistency_failure"}
        assert report["uncertain_high_impact_candidates"][0]["title"] == "Empty input raises"
