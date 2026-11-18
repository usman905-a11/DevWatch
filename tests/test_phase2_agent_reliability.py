"""Phase 2 TDD suite: role tool selection, cross-agent deduplication, and termination/coverage hardening."""

import json
import pytest

from backend.providers.base import LLMResponse, LLMUsage
from backend.review.contracts import (
    AGENT_CONTRACTS,
    AgentId,
    AgentPrivateState,
    BalancedLimits,
    Coverage,
    FindingCandidate,
    ModelTier,
    ReviewTask,
    SourceLocation,
    SpecialistResult,
)
from backend.review.jobs import DurableJobManager
from backend.review.repository import RepositoryContext, SharedBlackboard, StructuralEvidenceGate
from backend.review.stores import ArtifactStore, StoreLayout
from backend.review.workflow import CanonicalReviewExecutor
from tests.test_canonical_workflow import ReviewProvider, stores
from tests.test_control_agents import MODELS, plan_payload
from tests.test_iterative_agents import ScriptedProvider
from tests.test_m16_investigation import complete, engine
from tests.test_repository_context import setup_repository
from tests.verification_fixtures import reviewed


@pytest.mark.asyncio
async def test_non_ast_task_omits_parser_tools_and_planner_omits_redundant_repo_map(tmp_path):
    layout = StoreLayout(tmp_path / "runtime")
    artifacts = ArtifactStore(layout.app_db)
    snapshot = artifacts.capture(
        owner="alice",
        files={
            "README.md": "# Service\nEmpty lines ok\n",
            "config.json": '{"retries": 3}\n',
        },
    )
    repo = RepositoryContext(artifacts, snapshot.snapshot_id, owner="alice")
    task = ReviewTask(
        task_id="sec-docs",
        agent_id=AgentId.ARCHITECTURE_SECURITY,
        files=["README.md", "config.json"],
        focus="Check configuration security",
    )

    class InspectDocProvider(ScriptedProvider):
        async def generate_completion(self, request):
            body = json.loads(request.prompt)
            refs = [page["evidence_ref"] for page in body["selected_context"]["evidence"]]
            if not refs:
                action = {
                    "kind": "call_tool",
                    "tool": "read_file",
                    "arguments": {"file_path": "README.md", "additional_files": ["config.json"]},
                }
            else:
                action = complete(task, [], refs)
            self.responses = iter([action])
            return await super().generate_completion(request)

    spec_provider = InspectDocProvider([])
    await engine(repo, spec_provider).run_specialist(task)
    assert len(spec_provider.requests) == 2
    analysis_tools = {t["name"] for t in json.loads(spec_provider.requests[1].prompt)["tool_catalogue"]}
    assert {"read_file", "code_search"}.issubset(analysis_tools)
    assert not {"parse_ast", "symbol_lookup", "call_graph"} & analysis_tools

    # Planner with full pre-computed intelligence (0 omissions) should not be offered redundant repo_map.
    plan = {
        "selected_agents": ["architecture_security"],
        "priority_files": ["README.md"],
        "priority_symbols": [],
        "risk_areas": [],
        "review_tasks": [
            {
                "task_id": "sec-docs",
                "agent_id": "architecture_security",
                "files": ["README.md", "config.json"],
                "focus": "Check config",
            }
        ],
        "review_strategy": "Audit docs and config",
        "coverage_expectations": ["README.md", "config.json"],
    }
    planner_provider = ScriptedProvider([{"kind": "submit_plan", "payload": plan}])

    def full_context(_state):
        return {
            "snapshot_id": repo.snapshot_id,
            "scope": ["README.md", "config.json"],
            "evidence": [],
            "intelligence": {"README.md": {"status": "parser_unavailable"}, "config.json": {"status": "parser_unavailable"}},
            "changes": ["README.md", "config.json"],
        }

    planner_engine = engine(repo, planner_provider)
    planner_engine.context = full_context
    await planner_engine.run_planner(snapshot_id=repo.snapshot_id, files=["README.md", "config.json"])
    planner_tools = {t["name"] for t in json.loads(planner_provider.requests[0].prompt)["tool_catalogue"]}
    assert "repo_map" not in planner_tools
    assert "read_file" in planner_tools


def test_all_role_system_prompts_stay_bounded_and_include_line_grounding_and_severity_rules():
    from backend.review import prompts

    for agent_id, contract in AGENT_CONTRACTS.items():
        assert len(contract.system_prompt.encode("utf-8")) <= 2000, f"{agent_id.value} exceeds 2000B limit"

    assert "start_line" in prompts.SKILLS["specialist_completion"] or "line range" in prompts.SKILLS["specialist_completion"]
    assert "severity" in prompts.SKILLS["specialist_completion"]
    assert "severity" in prompts.SHARED_POLICY or "line" in prompts.SHARED_POLICY


@pytest.mark.asyncio
async def test_cross_agent_equivalent_defects_with_different_categories_consolidate_and_render_attribution(tmp_path):
    layout, artifacts, snapshot, jobs = stores(tmp_path)

    class CrossAgentProvider:
        async def generate_completion(self, request):
            data = json.loads(request.prompt)
            role = data["task"]["agent_id"]
            phase = data["phase"]
            pages = data["selected_context"].get("evidence", [])
            refs = [p["evidence_ref"] for p in pages]
            if role == "planner":
                action = {
                    "kind": "submit_plan",
                    "payload": {
                        "selected_agents": ["bug_reliability", "logic_correctness"],
                        "priority_files": ["service.py"],
                        "priority_symbols": [],
                        "risk_areas": ["empty_input"],
                        "review_tasks": [
                            {
                                "task_id": "bug-1",
                                "agent_id": "bug_reliability",
                                "files": ["service.py"],
                                "focus": "Error handling on empty inputs",
                            },
                            {
                                "task_id": "logic-1",
                                "agent_id": "logic_correctness",
                                "files": ["service.py"],
                                "focus": "Sequence precondition invariants",
                            },
                        ],
                        "review_strategy": "Audit empty input invariants",
                        "coverage_expectations": ["service.py"],
                    },
                }
            elif role in {"bug_reliability", "logic_correctness"}:
                if not data["private_state"]["evidence_refs"]:
                    action = {"kind": "call_tool", "tool": "read_file", "arguments": {"file_path": "service.py"}}
                else:
                    category = "bug" if role == "bug_reliability" else "logic"
                    conf = 0.96 if role == "bug_reliability" else 0.90
                    trailing = "." if role == "logic_correctness" else ""
                    cand = {
                        "category": category,
                        "kind": "defect",
                        "severity": "high",
                        "title": "Empty input raises IndexError",
                        "description": f"Indexing items[0] fails when items is empty{trailing}",
                        "impact": "Caller crashes with unhandled IndexError on empty sequence",
                        "confidence": conf,
                        "remediation": "Guard empty sequences before indexing.",
                        "evidence_refs": refs,
                        "location": {
                            "snapshot_id": data["selected_context"]["snapshot_id"],
                            "file_path": "service.py",
                            "start_line": 2,
                            "end_line": 2,
                        },
                    }
                    action = {
                        "kind": "submit_candidates",
                        "payload": {
                            "task_id": data["task"]["task_id"],
                            "agent_id": role,
                            "candidates": [cand],
                            "coverage": {},
                            "stop_reason": "evidence_complete",
                        },
                    }
            elif phase == "verification":
                decisions = [
                    {
                        "finding_id": fid,
                        "verdict": "confirmed",
                        "confidence": cand["confidence"],
                        "rationale": "Inspected source proves empty items raises IndexError",
                        "evidence_refs": cand["evidence_refs"],
                        "causal_review": reviewed(cand, cand["evidence_refs"]),
                    }
                    for fid, cand in data["candidates"].items()
                ]
                action = {"kind": "submit_verification", "payload": {"decisions": decisions}}
            else:
                action = {"kind": "submit_synthesis", "payload": {"summary": "One verified defect", "limitations": []}}

            action["inspected_evidence"] = refs
            return LLMResponse(
                finish_reason="stop",
                content=json.dumps(action),
                provider="scripted",
                model=request.model,
                latency_ms=0,
                usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )

    executor = CanonicalReviewExecutor(layout, artifacts, jobs, CrossAgentProvider(), models=MODELS)
    manager = DurableJobManager(jobs, executor)
    try:
        job = await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="p2-dedup")
        done = await manager.wait(job.job_id, owner="alice")
    finally:
        await manager.close()

    assert done.status == "completed"
    report = json.loads(done.result["json"])
    assert len(report["confirmed_defects"]) == 1
    assert len(report["verification_audit"]["duplicate_groups"]) == 1
    assert len(report["verification_audit"]["decisions"]) == 2
    markdown = done.result["markdown"]
    assert "Contributors: bug\\_reliability/bug-1, logic\\_correctness/logic-1" in markdown
    for dec in report["verification_audit"]["decisions"]:
        for ref in dec["evidence_refs"]:
            assert ref in markdown


@pytest.mark.asyncio
async def test_distinct_defects_on_same_file_stay_separate(tmp_path):
    layout = StoreLayout(tmp_path / "runtime")
    artifacts = ArtifactStore(layout.app_db)
    snapshot = artifacts.capture(
        owner="alice",
        files={
            "service.py": "def first(items):\n    return items[0]\n\ndef divide(a, b):\n    return a / b\n",
        },
    )
    jobs = JobStore_for(layout)

    class TwoBugsProvider:
        async def generate_completion(self, request):
            data = json.loads(request.prompt)
            role = data["task"]["agent_id"]
            phase = data["phase"]
            pages = data["selected_context"].get("evidence", [])
            refs = [p["evidence_ref"] for p in pages]
            if role == "planner":
                action = {"kind": "submit_plan", "payload": plan_payload(["service.py"])}
            elif role == "logic_correctness":
                if not data["private_state"]["evidence_refs"]:
                    action = {"kind": "call_tool", "tool": "read_file", "arguments": {"file_path": "service.py"}}
                else:
                    snap = data["selected_context"]["snapshot_id"]
                    cands = [
                        {
                            "category": "logic",
                            "kind": "defect",
                            "severity": "high",
                            "title": "Empty sequence crash",
                            "description": "items[0] fails when items is empty",
                            "impact": "Raises IndexError on empty list",
                            "confidence": 0.9,
                            "remediation": "Check if items is empty first.",
                            "evidence_refs": refs,
                            "location": {"snapshot_id": snap, "file_path": "service.py", "start_line": 2, "end_line": 2},
                        },
                        {
                            "category": "logic",
                            "kind": "defect",
                            "severity": "high",
                            "title": "Zero divisor crash",
                            "description": "a / b raises ZeroDivisionError when b is zero",
                            "impact": "Raises ZeroDivisionError for b=0",
                            "confidence": 0.9,
                            "remediation": "Guard b == 0 before division.",
                            "evidence_refs": refs,
                            "location": {"snapshot_id": snap, "file_path": "service.py", "start_line": 5, "end_line": 5},
                        },
                    ]
                    action = {
                        "kind": "submit_candidates",
                        "payload": {"task_id": "logic-1", "agent_id": role, "candidates": cands, "coverage": {}, "stop_reason": "evidence_complete"},
                    }
            elif phase == "verification":
                decisions = [
                    {
                        "finding_id": fid,
                        "verdict": "confirmed",
                        "confidence": 0.9,
                        "rationale": "Inspected source proves the crash condition",
                        "evidence_refs": cand["evidence_refs"],
                        "causal_review": reviewed(cand, cand["evidence_refs"]),
                    }
                    for fid, cand in data["candidates"].items()
                ]
                action = {"kind": "submit_verification", "payload": {"decisions": decisions}}
            else:
                action = {"kind": "submit_synthesis", "payload": {"summary": "Two separate defects", "limitations": []}}

            action["inspected_evidence"] = refs
            return LLMResponse(
                finish_reason="stop",
                content=json.dumps(action),
                provider="scripted",
                model=request.model,
                latency_ms=0,
                usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )

    executor = CanonicalReviewExecutor(layout, artifacts, jobs, TwoBugsProvider(), models=MODELS)
    manager = DurableJobManager(jobs, executor)
    try:
        job = await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="p2-distinct")
        done = await manager.wait(job.job_id, owner="alice")
    finally:
        await manager.close()

    assert done.status == "completed"
    report = json.loads(done.result["json"])
    assert len(report["confirmed_defects"]) == 2
    assert report["verification_audit"]["duplicate_groups"] == []


@pytest.mark.asyncio
async def test_control_agent_stops_no_progress_on_repeated_identical_tool_call(tmp_path):
    _, _, _, repo, _ = setup_repository(tmp_path)
    repeated_read = {"kind": "call_tool", "tool": "read_file", "arguments": {"file_path": "service.py"}}

    class RepeatingVerifierProvider(ScriptedProvider):
        async def generate_completion(self, request):
            body = json.loads(request.prompt)
            refs = [page["evidence_ref"] for page in body["selected_context"]["evidence"]]
            action = {**repeated_read, "inspected_evidence": refs}
            self.responses = iter([action])
            return await super().generate_completion(request)

    provider = RepeatingVerifierProvider([])
    result = await engine(repo, provider).run_final(
        snapshot_id=repo.snapshot_id,
        files=["service.py"],
        candidates={},
    )
    assert result["private_state"].stop_reason == "no_progress"
    assert len(provider.requests) == 2
    assert result["private_state"].tool_call_count == 1
    assert result["private_state"].coverage.failed["__final"] == "no_progress"


def test_followup_inspection_clears_stale_not_inspected_and_retains_prior_candidates(tmp_path):
    _, artifacts, _, original, task = setup_repository(tmp_path)
    repo = RepositoryContext(artifacts, original.snapshot_id, owner="alice")
    all_files_task = ReviewTask(task_id="logic-1", agent_id=AgentId.LOGIC_CORRECTNESS, files=["service.py", "other.py"], focus="Check both")
    ref1 = repo._read_file({"file_path": "service.py"}, all_files_task).evidence_ref
    ref2 = repo._read_file({"file_path": "other.py"}, all_files_task).evidence_ref
    cand = FindingCandidate(
        category="logic",
        kind="defect",
        severity="high",
        title="Empty input raises",
        description="items[0] fails when empty",
        impact="Crash on empty input",
        confidence=0.9,
        location=SourceLocation(snapshot_id=repo.snapshot_id, file_path="service.py", start_line=2, end_line=2),
        evidence_refs=[ref1],
        remediation="Guard items before indexing.",
    )
    board = SharedBlackboard(StructuralEvidenceGate(repo))
    r1 = SpecialistResult(
        task_id="logic-1",
        agent_id=AgentId.LOGIC_CORRECTNESS,
        candidates=[cand],
        coverage=Coverage(inspected_files=["service.py"], skipped={"other.py": "not_inspected"}),
        stop_reason="evidence_incomplete",
    )
    board.publish(all_files_task, r1)
    assert board.coverage().skipped["other.py"] == "not_inspected"

    # Follow-up inspects other.py cleanly
    r2 = SpecialistResult(
        task_id="logic-1",
        agent_id=AgentId.LOGIC_CORRECTNESS,
        candidates=[cand],
        coverage=Coverage(inspected_files=["service.py", "other.py"], skipped={}),
        stop_reason="evidence_complete",
    )
    board.publish(all_files_task, r2)
    cov = board.coverage()
    assert cov.inspected_files == ["other.py", "service.py"]
    assert "other.py" not in cov.skipped
    assert len(board.candidates) == 1


@pytest.mark.asyncio
async def test_partial_stop_explanation_is_recorded_in_coverage_limitations(tmp_path):
    _, _, _, repo, task = setup_repository(tmp_path)
    provider = ScriptedProvider(
        [
            {"kind": "call_tool", "tool": "read_file", "arguments": {"file_path": "service.py"}},
            {"kind": "call_tool", "tool": "read_file", "arguments": {"file_path": "service.py"}},
        ]
    )
    output = await engine(repo, provider).run_specialist(task)
    assert output["output"].stop_reason == "no_progress"
    assert any("new acknowledged evidence" in note.lower() for note in output["output"].coverage.limitations)


def JobStore_for(layout: StoreLayout):
    from backend.review.jobs import JobStore

    return JobStore(layout.app_db)

