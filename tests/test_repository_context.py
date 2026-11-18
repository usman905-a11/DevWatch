"""Real snapshot/cache/evidence boundaries used by canonical agents."""

import asyncio
import importlib

import pytest

from backend.review.contracts import AgentAction, AgentId, AgentPrivateState, FindingCandidate, ReviewTask, SpecialistResult, Coverage
from backend.review.stores import ArtifactStore


def repository_api():
    assert importlib.util.find_spec("backend.review.repository"), "Canonical repository context is missing"
    return importlib.import_module("backend.review.repository")


def setup_repository(tmp_path):
    api = repository_api()
    artifacts = ArtifactStore(tmp_path / "devwatch.sqlite")
    manifest = artifacts.capture(owner="alice", files={
        "service.py": "def first(items):\n    return items[0]\n",
        "other.py": "PRIVATE_OTHER_FILE = 'not-in-context'\n",
        "index.ts": "export const first = (items: number[]) => items[0];\n"})
    repo = api.RepositoryContext(artifacts, manifest.snapshot_id, owner="alice")
    task = ReviewTask(task_id="logic-1", agent_id=AgentId.LOGIC_CORRECTNESS, files=["service.py"], focus="empty input")
    return api, artifacts, manifest, repo, task


def test_python_intelligence_is_cached_and_unsupported_parsers_are_explicit(tmp_path):
    _, _, _, repo, _ = setup_repository(tmp_path)
    first = repo.analyze()
    assert first["service.py"]["symbols"][0]["name"] == "first"
    assert first["service.py"]["symbols"][0]["start_line"] == 1
    assert first["index.ts"]["status"] == "parsed"
    assert repo.analyze() == first


def test_agent_reads_are_scoped_and_evidence_is_available_on_next_iteration(tmp_path):
    _, _, _, repo, task = setup_repository(tmp_path)
    async def scenario():
        tools = repo.tools()
        with pytest.raises(PermissionError):
            await tools.execute(task, AgentAction(kind="call_tool", tool="read_file", arguments={"file_path": "other.py"}))
        observed = await tools.execute(task, AgentAction(kind="call_tool", tool="read_file", arguments={"file_path": "service.py"}))
        private = AgentPrivateState(current_task=task.task_id, evidence_refs=[observed.evidence_ref])
        context = repo.context({"task": task, "private_state": private, "action": None})
        assert "return items[0]" in str(context)
        assert "not-in-context" not in str(context)
        assert observed.inspected == ["service.py"]
        with pytest.raises(ValueError):
            await tools.execute(task, AgentAction(kind="call_tool", tool="read_file", arguments={"file_path": "service.py", "start_line": 3}))
    asyncio.run(scenario())


def test_structural_gate_rejects_forged_refs_and_source_ranges(tmp_path):
    api, _, manifest, repo, task = setup_repository(tmp_path)
    async def scenario():
        observed = await repo.tools().execute(task, AgentAction(kind="call_tool", tool="read_file", arguments={"file_path": "service.py"}))
        candidate = FindingCandidate(category="logic", title="Empty list raises", description="Indexing an empty list fails",
            impact="Caller fails", confidence=0.9, evidence_refs=[observed.evidence_ref],
            location={"snapshot_id": manifest.snapshot_id, "file_path": "service.py", "start_line": 2, "end_line": 2})
        gate = api.StructuralEvidenceGate(repo)
        gate.validate(candidate, task)
        for bad in [candidate.model_copy(update={"evidence_refs": ["made-up"]}),
                    candidate.model_copy(update={"location": candidate.location.model_copy(update={"end_line": 20})}),
                    candidate.model_copy(update={"location": candidate.location.model_copy(update={"snapshot_id": "other"})})]:
            with pytest.raises(ValueError):
                gate.validate(bad, task)
        board = api.SharedBlackboard(gate)
        output = SpecialistResult(task_id=task.task_id, agent_id=task.agent_id, candidates=[candidate], coverage=Coverage(), stop_reason="evidence_complete")
        board.publish(task, output)
        board.publish(task, output)
        assert len(board.candidates) == 1
        assert next(iter(board.candidates)).startswith("finding-")
    asyncio.run(scenario())


def test_evidence_survives_reopening_but_tampering_is_detected(tmp_path):
    import sqlite3
    api, artifacts, manifest, repo, task = setup_repository(tmp_path)
    async def scenario():
        observed = await repo.tools().execute(task, AgentAction(kind="call_tool", tool="read_file", arguments={"file_path": "service.py"}))
        reopened = api.RepositoryContext(artifacts, manifest.snapshot_id, owner="alice")
        assert reopened.evidence(observed.evidence_ref)["file_path"] == "service.py"
        with sqlite3.connect(tmp_path / "devwatch.sqlite") as conn:
            row = conn.execute(
                "SELECT payload FROM evidence WHERE snapshot_id=? AND evidence_ref=?",
                (manifest.snapshot_id, observed.evidence_ref),
            ).fetchone()
            conn.execute(
                "UPDATE evidence SET payload=? WHERE snapshot_id=? AND evidence_ref=?",
                (row[0].replace("return items[0]", "return items[1]"), manifest.snapshot_id, observed.evidence_ref),
            )
        with pytest.raises(ValueError):
            reopened.evidence(observed.evidence_ref)
    asyncio.run(scenario())


def test_context_request_is_bounded_and_does_not_widen_scope(tmp_path):
    _, _, _, repo, task = setup_repository(tmp_path)
    with pytest.raises(PermissionError):
        repo.context({"task": task, "private_state": AgentPrivateState(), "action": AgentAction(
            kind="request_context", arguments={"file_path": "other.py"})})
    observation = repo.context({"task": task, "private_state": AgentPrivateState(), "action": AgentAction(
        kind="request_context", arguments={"file_path": "service.py", "start_line": 2, "end_line": 2})})
    assert observation.inspected == ["service.py"]
    assert repo.evidence(observation.evidence_ref)["end_line"] == 2


def test_oversized_source_intelligence_returns_parse_failed():
    from backend.review.intelligence import analyze_source

    oversized = "# " + ("x" * 600_000)
    analysis = analyze_source("big.py", oversized)
    assert analysis["status"] == "parse_failed"
    assert analysis["symbols"] == []
    assert analysis["limitations"] == ["Source exceeds parser input bound"]
