"""The public activity lifecycle, independent of any transport."""

import pytest

from devwatch.review.activity_stream import ActivityStream, AgentActivityPublisher, InvalidActivity
from devwatch.review.jobs import EventStore, JobStore


@pytest.fixture
def recording():
    events = []

    def publish(event):
        saved = event.model_copy(update={"sequence": len(events) + 1})
        events.append(saved)
        return saved

    return ActivityStream("run-1", publish), events


def test_delta_and_authoritative_completion(recording):
    stream, events = recording
    stream.begin_agent("agent-1", required=True)
    activity = stream.start("agent-1", "command", {"commandId": "tests"})
    stream.delta(activity, {"stdout": "partial"})
    stream.complete(activity, {"stdout": "final", "exitCode": 0})
    assert [event.type for event in events] == ["activity.started", "activity.delta", "activity.completed"]
    assert {event.activityId for event in events} == {activity}
    assert {event.agentRunId for event in events} == {"agent-1"}
    assert events[-1].data.model_dump(exclude_none=True) == {"stdout": "final", "exitCode": 0}
    assert [event.sequence for event in events] == [1, 2, 3]
    stream.end_agent("agent-1")
    stream.end_run()


def test_failure_cancellation_and_terminal_rejection(recording):
    stream, events = recording
    stream.begin_agent("a")
    failed = stream.start("a", "tool_call", {})
    stream.fail(failed, "tool_execution_failed")
    cancelled = stream.start("a", "file_read", {})
    stream.cancel(cancelled)
    assert [event.type for event in events][-2:] == ["activity.started", "activity.cancelled"]
    assert events[1].data.model_dump(exclude_none=True) == {"errorCode": "tool_execution_failed"}
    for operation in (lambda: stream.delta(failed, {"text": "late"}),
                      lambda: stream.complete(failed, {}),
                      lambda: stream.cancel(cancelled)):
        with pytest.raises(InvalidActivity):
            operation()
    assert len(events) == 4


def test_agent_and_run_wait_for_active_work(recording):
    stream, _ = recording
    stream.begin_agent("required", required=True)
    stream.begin_agent("other")
    first = stream.start("required", "response", {})
    second = stream.start("other", "finding", {})
    with pytest.raises(InvalidActivity):
        stream.end_agent("required")
    stream.complete(first, {"text": "complete response"})
    stream.end_agent("required")
    with pytest.raises(InvalidActivity):
        stream.end_run()
    stream.complete(second, {})
    stream.end_agent("other")
    stream.end_run()


def test_agents_interleave_and_event_ids_are_unique(recording):
    stream, events = recording
    stream.begin_agent("a")
    stream.begin_agent("b")
    a = stream.start("a", "code_search", {})
    b = stream.start("b", "file_search", {})
    stream.delta(b, {"count": 1})
    stream.complete(a, {"count": 2})
    stream.complete(b, {"count": 1})
    assert [event.agentRunId for event in events] == ["a", "b", "b", "a", "b"]
    assert len({event.eventId for event in events}) == len(events)
    with pytest.raises(InvalidActivity):
        stream.start("missing", "result", {})


def test_activity_uses_existing_outbox_and_replays_after_restart(tmp_path):
    jobs = JobStore(tmp_path / "jobs.sqlite")
    events = EventStore(tmp_path / "events.sqlite")
    job = jobs.submit(owner="alice", request={"snapshot_id": "s"}, idempotency_key="intent")
    jobs.transition(job.job_id, owner="alice", expected_status="queued", status="running")
    stream = ActivityStream(job.job_id, lambda event: jobs.publish_activity(job.job_id, owner="alice", event=event))
    stream.begin_agent("agent-1")
    activity_id = stream.start("agent-1", "file_read", {"path": "a.py"})
    stream.complete(activity_id, {"evidenceRef": "evidence-1"})
    jobs.dispatch_events(events)
    replayed = EventStore(tmp_path / "events.sqlite").replay(job.job_id)
    assert [item.sequence for item in replayed] == [1, 2, 3, 4]
    assert [item.type for item in replayed[2:]] == ["activity.started", "activity.completed"]
    assert replayed[2].activityId == replayed[3].activityId == activity_id
    assert jobs.dispatch_events(events) == 0


def test_public_data_rejects_private_fields_and_oversized_text(recording):
    stream, events = recording
    stream.begin_agent("a")
    for data in ({"systemPrompt": "private"}, {"text": "x" * 65537}):
        with pytest.raises((InvalidActivity, ValueError)):
            stream.start("a", "response", data)
    assert events == []


def test_agent_tool_and_node_events_have_one_lifecycle(recording):
    stream, events = recording
    publisher = AgentActivityPublisher(stream)
    publisher.record("agent_started", run_id="agent-1", agent_id="planner", task_id="__planner")
    publisher.record("graph_node_started", run_id="agent-1", operation_id="node-1", node="execute_action", graph_scope="agent")
    publisher.record("tool_called", run_id="agent-1", operation_id="tool-1", tool="code_search")
    publisher.record("evidence_retrieved", run_id="agent-1", operation_id="tool-1", evidence_ref="evidence-1", offset=5)
    publisher.record("tool_result", run_id="agent-1", operation_id="tool-1", tool="code_search", outcome="succeeded", evidence_ref="evidence-1")
    publisher.record("graph_node_completed", run_id="agent-1", operation_id="node-1", node="execute_action", graph_scope="agent", outcome="succeeded")
    publisher.record("agent_completed", run_id="agent-1", agent_id="planner", outcome="succeeded")
    publisher.finish()
    assert [(event.activityId, event.type) for event in events if event.activityId == "tool-1"] == [
        ("tool-1", "activity.started"), ("tool-1", "activity.delta"), ("tool-1", "activity.completed")]
    assert next(event for event in events if event.activityId == "tool-1").activityType == "code_search"
    assert next(event for event in events if event.activityId == "tool-1").parentActivityId == "node-1"
    assert all(event.runId == "run-1" for event in events)


def test_job_completion_waits_for_activity_and_failure_closes_it(tmp_path):
    jobs = JobStore(tmp_path / "jobs.sqlite")
    job = jobs.submit(owner="alice", request={"snapshot_id": "s"}, idempotency_key="one")
    jobs.transition(job.job_id, owner="alice", expected_status="queued", status="running")
    stream = ActivityStream(job.job_id, lambda event: jobs.publish_activity(job.job_id, owner="alice", event=event))
    stream.begin_agent("agent-1")
    activity = stream.start("agent-1", "command", {})
    with pytest.raises(InvalidActivity):
        jobs.transition(job.job_id, owner="alice", expected_status="running", status="completed")
    jobs.transition(job.job_id, owner="alice", expected_status="running", status="failed")
    history = [event for event in jobs.pending_events() if hasattr(event, "activityId")]
    assert [(event.activityId, event.type) for event in history] == [
        (activity, "activity.started"), (activity, "activity.failed")]


def test_command_output_is_delta_on_its_command_activity(recording):
    stream, events = recording
    publisher = AgentActivityPublisher(stream)
    publisher.record("agent_started", run_id="agent-1", agent_id="bug_reliability")
    publisher.record("tool_called", run_id="agent-1", operation_id="command-1", tool="run_tests")
    publisher.record("tool_progress", run_id="agent-1", operation_id="command-1", stream="stdout", text="one\n")
    publisher.record("tool_progress", run_id="agent-1", operation_id="command-1", stream="stderr", text="warning\n")
    publisher.record("tool_result", run_id="agent-1", operation_id="command-1", tool="run_tests", outcome="succeeded")
    command = [event for event in events if event.activityId == "command-1"]
    assert [event.type for event in command] == ["activity.started", "activity.delta", "activity.delta", "activity.completed"]
    assert command[1].data.stdout == "one\n" and command[2].data.stderr == "warning\n"
    assert command[-1].data.stdout == "one\n" and command[-1].data.stderr == "warning\n"


def test_search_read_tests_and_findings_use_stable_types(recording):
    stream, events = recording
    publisher = AgentActivityPublisher(stream)
    publisher.record("agent_started", run_id="agent-1", agent_id="bug_reliability")
    for operation, tool, expected in (("files", "repo_map", "file_search"),
                                      ("code", "code_search", "code_search"),
                                      ("read", "read_source", "file_read"),
                                      ("tests", "run_tests", "test_execution")):
        publisher.record("tool_called", run_id="agent-1", operation_id=operation, tool=tool)
        publisher.record("tool_result", run_id="agent-1", operation_id=operation,
                         tool=tool, outcome="succeeded", evidence_ref=f"evidence-{operation}")
        assert next(event for event in events if event.activityId == operation).activityType == expected
    publisher.record("finding_created", run_id="agent-1", finding_id="finding-1")
    assert any(event.activityType == "finding" and event.data.findingId == "finding-1" for event in events)
    web = stream.start("agent-1", "web_search", {"query": "example"})
    stream.complete(web, {"count": 1})
    assert [event.type for event in events if event.activityId == web] == ["activity.started", "activity.completed"]
