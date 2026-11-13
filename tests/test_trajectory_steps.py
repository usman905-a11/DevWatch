"""Tests for Antigravity-style trajectory step streaming (step_idx + StepUpdate)."""

import asyncio
import json
import pytest
from pydantic import ValidationError

from devwatch.review.jobs import (
    EventPayload,
    EventStore,
    JobStore,
    StepRenderInfo,
    StepUpdatePayload,
    TrajectoryStepTracker,
)


def test_step_contracts_validate_and_reject_private_fields():
    info = StepRenderInfo(
        title="Running pytest -q",
        command="pytest -q",
        stdout_append="1 passed\n",
        exit_code=0,
        duration_ms=42,
        files=["service.py"],
    )
    assert info.title == "Running pytest -q"
    assert info["title"] == "Running pytest -q"
    assert info.get("command") == "pytest -q"

    payload = StepUpdatePayload(
        step_idx=0,
        parent_step_idx=None,
        agent_name="bug_reliability",
        step_type="run_command",
        status="RUNNING",
        delta_seq=0,
        render_info=info,
    )
    assert payload.step_idx == 0
    assert payload["step_type"] == "run_command"
    assert payload.render_info.title == "Running pytest -q"

    with pytest.raises(ValidationError):
        StepRenderInfo(title="bad", private_reasoning="secret")  # type: ignore[call-arg]

    event_payload = EventPayload.model_validate(payload.model_dump(exclude_none=True))
    assert event_payload.step_idx == 0
    assert event_payload.step_type == "run_command"
    assert event_payload.status == "RUNNING"
    assert event_payload.render_info is not None
    assert event_payload.render_info.title == "Running pytest -q"


def test_step_scope_lifecycle_normal_deltas_and_nesting():
    async def scenario():
        emitted: list[tuple[str, dict]] = []

        def emit(kind: str, **payload):
            emitted.append((kind, EventPayload.model_validate(payload).model_dump(mode="json")))

        tracker = TrajectoryStepTracker(emit)
        async with tracker.step_scope(
            "agent_run",
            "Specialist: bug_reliability",
            agent_name="bug_reliability",
        ) as parent:
            assert parent.step_idx == 0
            async with tracker.step_scope(
                "run_command",
                "Running pytest -q",
                parent_step_idx=parent.step_idx,
                agent_name="bug_reliability",
                initial_render_info={"command": "pytest -q"},
            ) as cmd:
                assert cmd.step_idx == 1
                assert cmd.parent_step_idx == 0
                await cmd.emit_delta({"stdout_append": "collecting...\n"})
                await cmd.update({"stdout_append": "1 passed\n"})
                cmd.set_completion_info({"exit_code": 0, "evidence_ref": "evidence-123"})

        assert len(emitted) == 6
        kinds = [k for k, _ in emitted]
        assert kinds == ["step_update"] * 6

        parent_start = emitted[0][1]
        assert parent_start["step_idx"] == 0
        assert parent_start["parent_step_idx"] is None
        assert parent_start["step_type"] == "agent_run"
        assert parent_start["status"] == "RUNNING"
        assert parent_start["delta_seq"] == 0
        assert parent_start["render_info"]["title"] == "Specialist: bug_reliability"

        cmd_start = emitted[1][1]
        assert cmd_start["step_idx"] == 1
        assert cmd_start["parent_step_idx"] == 0
        assert cmd_start["step_type"] == "run_command"
        assert cmd_start["status"] == "RUNNING"
        assert cmd_start["delta_seq"] == 0
        assert cmd_start["render_info"]["command"] == "pytest -q"

        cmd_d1 = emitted[2][1]
        assert cmd_d1["step_idx"] == 1
        assert cmd_d1["delta_seq"] == 1
        assert cmd_d1["status"] == "RUNNING"
        assert cmd_d1["render_info"]["stdout_append"] == "collecting...\n"

        cmd_d2 = emitted[3][1]
        assert cmd_d2["step_idx"] == 1
        assert cmd_d2["delta_seq"] == 2
        assert cmd_d2["status"] == "RUNNING"
        assert cmd_d2["render_info"]["stdout_append"] == "1 passed\n"

        cmd_done = emitted[4][1]
        assert cmd_done["step_idx"] == 1
        assert cmd_done["delta_seq"] == 3
        assert cmd_done["status"] == "DONE"
        assert cmd_done["render_info"]["exit_code"] == 0
        assert cmd_done["render_info"]["evidence_ref"] == "evidence-123"
        assert cmd_done["render_info"]["duration_ms"] >= 0

        parent_done = emitted[5][1]
        assert parent_done["step_idx"] == 0
        assert parent_done["delta_seq"] == 1
        assert parent_done["status"] == "DONE"
        assert parent_done["render_info"]["duration_ms"] >= 0

    asyncio.run(scenario())


def test_step_scope_guarantees_terminal_error_and_cancellation_with_redaction():
    async def scenario():
        emitted: list[tuple[str, dict]] = []

        def emit(kind: str, **payload):
            emitted.append((kind, EventPayload.model_validate(payload).model_dump(mode="json")))

        tracker = TrajectoryStepTracker(emit)

        with pytest.raises(TimeoutError):
            async with tracker.step_scope("tool", "Running parse_ast"):
                raise TimeoutError("private tool token and sk-secret12345678901234567890")

        assert len(emitted) == 2
        err_event = emitted[1][1]
        assert err_event["step_idx"] == 0
        assert err_event["status"] == "ERROR"
        assert err_event["delta_seq"] == 1
        assert "TimeoutError" in err_event["error_details"]
        assert "private tool token" not in json.dumps(emitted)
        assert "sk-secret12345678901234567890" not in json.dumps(emitted)

        with pytest.raises(asyncio.CancelledError):
            async with tracker.step("planner", "Planning next action..."):
                raise asyncio.CancelledError()

        assert len(emitted) == 4
        cancel_event = emitted[3][1]
        assert cancel_event["step_idx"] == 1
        assert cancel_event["status"] == "CANCELING"
        assert cancel_event["delta_seq"] == 1
        assert cancel_event["error_details"] == "Step cancelled"

    asyncio.run(scenario())


def test_job_store_settles_unfinished_running_steps_on_terminal_transition(tmp_path):
    jobs = JobStore(tmp_path / "jobs.sqlite")
    events = EventStore(tmp_path / "events.sqlite")
    job = jobs.submit(owner="alice", request={"snapshot_id": "a" * 32}, idempotency_key="step-settle")
    jobs.claim(job.job_id, owner="alice", execution_id="exec-1")

    # Emit step 0 (completed) and step 1 (still RUNNING with 1 delta)
    jobs.emit(
        job.job_id,
        owner="alice",
        kind="step_update",
        payload={
            "step_idx": 0,
            "step_type": "planner",
            "status": "RUNNING",
            "delta_seq": 0,
            "render_info": {"title": "Planning"},
        },
    )
    jobs.emit(
        job.job_id,
        owner="alice",
        kind="step_update",
        payload={
            "step_idx": 0,
            "step_type": "planner",
            "status": "DONE",
            "delta_seq": 1,
            "render_info": {"title": "Planned", "duration_ms": 12},
        },
    )
    jobs.emit(
        job.job_id,
        owner="alice",
        kind="step_update",
        payload={
            "step_idx": 1,
            "step_type": "run_command",
            "status": "RUNNING",
            "delta_seq": 0,
            "render_info": {"title": "Running pytest", "command": "pytest"},
        },
    )
    jobs.emit(
        job.job_id,
        owner="alice",
        kind="step_update",
        payload={
            "step_idx": 1,
            "step_type": "run_command",
            "status": "RUNNING",
            "delta_seq": 1,
            "render_info": {"stdout_append": "running...\n"},
        },
    )

    jobs.transition(job.job_id, owner="alice", expected_status="running", status="failed")
    jobs.dispatch_events(events)

    replayed = events.replay(job.job_id)
    step1_events = [
        e for e in replayed if getattr(e, "kind", None) == "step_update" and e.payload.step_idx == 1
    ]
    assert len(step1_events) == 3
    settled = step1_events[-1]
    assert settled.payload.status == "ERROR"
    assert settled.payload.delta_seq == 2
    assert settled.payload.error_details == "Interrupted by job termination"


def test_subgraph_emits_nested_agent_planner_and_enriched_tool_steps(tmp_path):
    from devwatch.review.budgets import BudgetManager
    from devwatch.review.contracts import AgentId, ReviewTask
    from devwatch.review.repository import RepositoryContext
    from devwatch.review.stores import ArtifactStore, RepoCache
    from devwatch.review.subgraphs import AgentSubgraphs
    from tests.test_control_agents import MODELS
    from tests.test_iterative_agents import ScriptedProvider, result

    files = {
        "service.py": "def compute(x):\n    return x + 1\n",
        "utils.py": "def helper():\n    return compute(2)\n",
    }
    artifacts = ArtifactStore(tmp_path / "artifacts")
    manifest = artifacts.capture(owner="alice", files=files)
    repo = RepositoryContext(artifacts, RepoCache(tmp_path / "cache.sqlite"), manifest.snapshot_id, owner="alice")

    provider = ScriptedProvider([
        {"kind": "call_tool", "tool": "repo_map", "arguments": {}},
        {"kind": "submit_candidates", "payload": {**result(), "task_id": "arch-1", "agent_id": "architecture_security"}},
        {"kind": "call_tool", "tool": "code_search", "arguments": {"query": "compute"}},
        {"kind": "call_tool", "tool": "read_source", "arguments": {"file_path": "service.py", "start_line": 1, "end_line": 2}},
        {"kind": "submit_candidates", "payload": {**result(), "task_id": "logic-1", "agent_id": "logic_correctness"}},
    ])

    events: list[tuple[str, dict]] = []

    def emit(kind: str, **payload):
        events.append((kind, EventPayload.model_validate(payload).model_dump(mode="json")))

    arch_task = ReviewTask(
        task_id="arch-1",
        agent_id=AgentId.ARCHITECTURE_SECURITY,
        files=["service.py", "utils.py"],
        focus="Check repo structure",
    )
    logic_task = ReviewTask(
        task_id="logic-1",
        agent_id=AgentId.LOGIC_CORRECTNESS,
        files=["service.py", "utils.py"],
        focus="Check compute",
    )

    async def scenario():
        subgraphs = AgentSubgraphs(
            provider,
            repo.tools(),
            BudgetManager(),
            repo.context,
            models=MODELS,
            emit=emit,
        )
        await subgraphs.run_specialist(arch_task)
        await subgraphs.run_specialist(logic_task)

    asyncio.run(scenario())

    step_events = [p for k, p in events if k == "step_update"]
    assert len(step_events) > 0

    # Root step 0 is the first agent_run step
    agent_runs = [e for e in step_events if e["step_type"] == "agent_run" and e["delta_seq"] == 0]
    assert len(agent_runs) == 2
    assert agent_runs[0]["step_idx"] == 0
    assert agent_runs[0]["parent_step_idx"] is None
    assert agent_runs[0]["agent_name"] == "architecture_security"
    assert agent_runs[1]["parent_step_idx"] is None
    assert agent_runs[1]["agent_name"] == "logic_correctness"

    arch_parent_idx = agent_runs[0]["step_idx"]
    logic_parent_idx = agent_runs[1]["step_idx"]

    # All child steps point to their respective agent_run parent_step_idx
    child_steps = [e for e in step_events if e["step_type"] != "agent_run"]
    assert child_steps
    assert all(
        e["parent_step_idx"] == (arch_parent_idx if e["agent_name"] == "architecture_security" else logic_parent_idx)
        for e in child_steps
    )

    # Planner steps transition from "Planning next action..." to public summary
    planner_done = [e for e in child_steps if e["step_type"] == "planner" and e["status"] == "DONE"]
    assert len(planner_done) == 5
    assert planner_done[0]["render_info"]["title"] == "Selected tool: repo_map"
    assert planner_done[1]["render_info"]["title"] == "Planned action: submit_candidates"
    assert planner_done[2]["render_info"]["title"] == "Selected tool: code_search"
    assert planner_done[3]["render_info"]["title"] == "Selected tool: read_source"
    assert planner_done[4]["render_info"]["title"] == "Planned action: submit_candidates"

    # repo_map step has files, match_count, evidence_ref
    repo_map_done = next(e for e in child_steps if e["step_type"] == "repo_map" and e["status"] == "DONE")
    assert repo_map_done["render_info"]["files"] == ["service.py", "utils.py"]
    assert repo_map_done["render_info"]["match_count"] == 2
    assert repo_map_done["render_info"]["evidence_ref"].startswith("evidence-")

    # code_search step has query on start and match_count/files/evidence_ref on completion
    search_start = next(e for e in child_steps if e["step_type"] == "code_search" and e["delta_seq"] == 0)
    search_done = next(e for e in child_steps if e["step_type"] == "code_search" and e["status"] == "DONE")
    assert search_start["render_info"]["query"] == "compute"
    assert search_done["render_info"]["match_count"] == 2
    assert search_done["render_info"]["files"] == ["service.py", "utils.py"]
    assert search_done["render_info"]["evidence_ref"].startswith("evidence-")

    # read_file step has files on start and evidence_ref on completion
    read_start = next(e for e in child_steps if e["step_type"] == "read_file" and e["delta_seq"] == 0)
    read_done = next(e for e in child_steps if e["step_type"] == "read_file" and e["status"] == "DONE")
    assert read_start["render_info"]["files"] == ["service.py"]
    assert read_done["render_info"]["evidence_ref"].startswith("evidence-")

    # Never leak raw source content
    assert "return x + 1" not in json.dumps(events)


def test_slow_client_subscriber_buffer_resyncs_from_event_store_on_overflow(tmp_path):
    from devwatch.review.jobs import JobStore, EventStore
    from devwatch.review.service import SubscriberEventBuffer

    jobs = JobStore(tmp_path / "jobs.sqlite")
    events = EventStore(tmp_path / "events.sqlite")
    job = jobs.submit(owner="alice", request={"snapshot_id": "a" * 32}, idempotency_key="slow-client")
    jobs.transition(job.job_id, owner="alice", expected_status="queued", status="running")

    buffer = SubscriberEventBuffer(after=0, maxsize=256)

    # Emit 320 step_update events while slow client hasn't consumed any yet
    for idx in range(320):
        ev = jobs.emit(
            job.job_id,
            owner="alice",
            kind="step_update",
            payload={
                "step_idx": idx,
                "step_type": "planner",
                "status": "DONE",
                "step_status": "DONE",
                "delta_seq": 0,
                "render_info": {"title": f"Step {idx}"},
            },
        )
        buffer.put_nowait(ev)

    jobs.dispatch_events(events)
    jobs.transition(job.job_id, owner="alice", expected_status="running", status="completed", result={"json": "{}"})
    jobs.dispatch_events(events)

    assert buffer.overflowed is True
    assert buffer.queue.qsize() == 256

    async def consume():
        received = []
        async for ev in buffer.stream(
            replay_fn=lambda after, limit: events.replay(job.job_id, after=after, limit=limit),
            is_active_fn=lambda: jobs.get(job.job_id, owner="alice").status in {"queued", "running"},
        ):
            received.append(ev)
        return received

    delivered = asyncio.run(consume())
    sequences = [e.sequence for e in delivered]
    assert sequences == list(range(1, len(delivered) + 1))
    assert len(delivered) >= 322  # job_queued + job_started + 320 step_updates + job_completed



