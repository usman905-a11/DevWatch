"""Completion classification cannot corrupt findings or claim unseen coverage."""

import json

import pytest
from pydantic import ValidationError

from devwatch.review.budgets import BudgetManager
from devwatch.review.contracts import AgentPrivateState, ModelTier, SpecialistResult
from devwatch.review.repository import SharedBlackboard, StructuralEvidenceGate
from devwatch.review.jobs import DurableJobManager
from devwatch.review.stores import RepoCache
from devwatch.review.subgraphs import AgentSubgraphs
from devwatch.review.workflow import CanonicalReviewExecutor
from tests.test_audit_evidence import candidate
from tests.test_iterative_agents import ScriptedProvider
from tests.test_repository_context import setup_repository
from tests.test_canonical_workflow import ReviewProvider, stores


MODELS = {tier: tier.value for tier in ModelTier}


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["evidence_complete", "budget_exhausted"])
async def test_explanation_is_preserved_without_changing_completion(tmp_path, reason):
    _, _, _, repo, task = setup_repository(tmp_path)
    ref = repo._read_source({"file_path": "service.py"}, task).evidence_ref
    explanation = "The requested source was inspected."
    payload = dict(task_id=task.task_id, agent_id=task.agent_id.value,
        candidates=[candidate(repo, ref)], coverage={}, stop_reason=reason,
        stop_explanation=explanation)
    provider = ScriptedProvider([{"kind": "submit_candidates", "payload": payload,
                                  "inspected_evidence": [ref]}])
    private = AgentPrivateState(current_task=task.task_id, evidence_refs=[ref])
    events, persisted = [], []
    engine = AgentSubgraphs(provider, repo.tools(), BudgetManager(), repo.context,
        models=MODELS, emit=lambda kind, **data: events.append((kind, data)),
        persist=lambda state, ledger: persisted.append(state["private_state"].model_dump_json()))
    state = await engine.run_specialist(task, private_state=private)
    output = state["output"]
    assert output.stop_reason == reason
    assert output.stop_explanation == explanation
    assert state["private_state"].stop_explanation == explanation
    assert AgentPrivateState.model_validate_json(persisted[-1]).stop_explanation == explanation
    assert len(output.candidates) == 1
    assert output.coverage.inspected_files == ["service.py"]
    assert output.coverage.failed == ({} if reason == "evidence_complete" else {task.task_id: reason})
    ended = next(data for kind, data in events if kind == "agent_completed")
    assert ended["outcome"] == ("succeeded" if reason == "evidence_complete" else "failed")
    assert ended["stop_reason"] == reason
    assert explanation not in json.dumps(events)


@pytest.mark.asyncio
async def test_legacy_narrative_stop_preserves_candidates_as_invalid_completion(tmp_path):
    _, _, _, repo, task = setup_repository(tmp_path)
    ref = repo._read_source({"file_path": "service.py"}, task).evidence_ref
    narrative = "I have enough evidence"
    payload = dict(task_id=task.task_id, agent_id=task.agent_id.value,
        candidates=[candidate(repo, ref), {"title": "Malformed sibling"}],
        coverage={}, stop_reason=narrative)
    # A pre-M12 persisted result and a new model response use the same migration.
    legacy = SpecialistResult.model_validate(payload)
    assert legacy.stop_reason == "invalid_schema"
    assert legacy.stop_explanation == narrative
    provider = ScriptedProvider([{"kind": "submit_candidates", "payload": payload}])
    events = []
    state = await AgentSubgraphs(provider, repo.tools(), BudgetManager(), repo.context,
        models=MODELS, emit=lambda kind, **data: events.append((kind, data))).run_specialist(task)
    output = state["output"]
    assert output.stop_reason == "invalid_schema"
    assert output.stop_explanation == narrative
    assert len(output.candidates) == 1
    assert len(output.quarantined) == 1
    assert output.coverage.failed[task.task_id] == "invalid_schema"
    assert output.coverage.inspected_files == []
    assert output.coverage.skipped["service.py"] == "not_inspected"
    board = SharedBlackboard(StructuralEvidenceGate(repo))
    board.publish(task, output)
    assert len(board.candidates) == 1
    assert narrative not in json.dumps(events)
    ended = next(data for kind, data in events if kind == "agent_completed")
    assert ended["stop_reason"] == "invalid_schema" and ended["outcome"] == "failed"


def test_completion_schema_publishes_codes_and_bounds_explanations():
    schema = SpecialistResult.model_json_schema()["properties"]
    assert "evidence_complete" in schema["stop_reason"]["enum"]
    payload = dict(task_id="t1", agent_id="bug_reliability", coverage={}, stop_reason="evidence_complete")
    assert SpecialistResult.model_validate(payload).stop_explanation == ""
    with pytest.raises(ValidationError):
        SpecialistResult.model_validate({**payload, "stop_explanation": "x" * 1001})
    migrated = SpecialistResult.model_validate({**payload, "stop_reason": "x" * 2000})
    assert migrated.stop_reason == "invalid_schema"
    assert len(migrated.stop_explanation) == 1000


@pytest.mark.parametrize("reason", [None, 12, ""])
def test_invalid_completion_types_are_not_migrated_to_success(reason):
    with pytest.raises(ValidationError):
        SpecialistResult.model_validate(dict(task_id="t1", agent_id="bug_reliability",
                                            coverage={}, stop_reason=reason))


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_full_graph_preserves_findings_through_completion_and_verification(tmp_path, legacy):
    class CompletionProvider(ReviewProvider):
        async def generate_completion(self, request):
            response = await super().generate_completion(request)
            action = json.loads(response.content)
            if action["kind"] == "submit_candidates":
                if legacy:
                    action["payload"]["stop_reason"] = "Investigation is complete"
                else:
                    action["payload"]["stop_explanation"] = "Inspected the empty input boundary."
            return response.model_copy(update={"content": json.dumps(action)})

    layout, artifacts, snapshot, jobs, events = stores(tmp_path)
    provider = CompletionProvider()
    executor = CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events,
                                      provider, models=MODELS)
    manager = DurableJobManager(jobs, events, executor)
    try:
        job = await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id},
                                   idempotency_key="completion-contract")
        finished = await manager.wait(job.job_id, owner="alice")
    finally:
        await manager.close()
    assert finished.status == "completed"
    report = json.loads(finished.result["json"])
    assert len(report["uncertain_high_impact_candidates"]) == 1
    assert report["confirmed_defects"] == []
    assert report["coverage"]["failed"] == ({"logic-1": "invalid_schema"} if legacy else {})
    assert report["coverage"]["inspected_files"] == ["service.py"]
    assert provider.phase_counts["synthesizer_verifier:verification"] == 1
    assert provider.phase_counts["synthesizer_verifier:synthesis"] == 1
    assert finished.ledger.total_tokens == 75
