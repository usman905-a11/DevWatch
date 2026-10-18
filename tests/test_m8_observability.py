"""The durable timeline describes real work without serializing model content."""
import asyncio
import json
import time
from uuid import uuid4

import pytest

from devwatch.providers.exceptions import ProviderAuthenticationError, ProviderTemporaryError
from devwatch.review.budgets import BudgetManager
from devwatch.review.contracts import AgentId, TokenUsage
from devwatch.review.jobs import EventPayload
from devwatch.review.subgraphs import AgentSubgraphs, PermissionedTools, ToolObservation
from tests.test_control_agents import MODELS
from tests.test_iterative_agents import ScriptedProvider, result, task
from tests.test_review_retries import FailingProvider


def recorder(events):
    def emit(kind, **payload):
        # Use the actual public metadata boundary, even in subgraph-only tests.
        events.append((kind, EventPayload.model_validate(payload).model_dump(mode="json")))
    return emit


def test_each_actual_model_attempt_has_correlated_completion_and_usage():
    async def scenario():
        events = []
        provider = ScriptedProvider(["invalid JSON with private content", {"kind": "submit_candidates", "payload": result()}])
        budget = BudgetManager()
        output = await AgentSubgraphs(provider, PermissionedTools(), budget, lambda state: {}, models=MODELS,
                                      emit=recorder(events)).run_specialist(task())
        assert output["output"].stop_reason == "evidence_complete"
        starts = [p for kind, p in events if kind == "model_call_started"]
        ends = [p for kind, p in events if kind == "model_call_completed"]
        assert len(starts) == len(ends) == len(provider.requests) == 2
        assert len({p["operation_id"] for p in starts}) == 2
        assert {p["operation_id"] for p in starts} == {p["operation_id"] for p in ends}
        assert all(p["phase"] == "investigation" and p["iteration"] == 1 and p["attempt"] == 1 for p in starts)
        assert all(p["outcome"] == "succeeded" and p["total_tokens"] == 15 and p["duration_seconds"] >= 0 for p in ends)
        assert sum(p["total_tokens"] for p in ends) == budget.ledger.total_tokens == 30
        assert len([1 for kind, p in events if kind == "iteration_started"]) == 1
        assert "private content" not in json.dumps(events)
    asyncio.run(scenario())


def test_safe_retry_events_link_the_failed_attempt_and_do_not_invent_an_iteration():
    async def scenario():
        events = []
        provider = FailingProvider([ProviderTemporaryError("private upstream details"),
                                   {"kind": "submit_candidates", "payload": result()}])
        await AgentSubgraphs(provider, PermissionedTools(), BudgetManager(), lambda state: {}, models=MODELS,
                             emit=recorder(events)).run_specialist(task())
        calls = [p for kind, p in events if kind == "model_call_started"]
        completed = [p for kind, p in events if kind == "model_call_completed"]
        retries = [p for kind, p in events if kind == "retry_started"]
        assert [p["attempt"] for p in calls] == [1, 2]
        assert [p["outcome"] for p in completed] == ["failed", "succeeded"]
        assert completed[0]["error_code"] == "provider_temporary"
        assert len(retries) == 1 and retries[0]["operation_id"] == calls[0]["operation_id"]
        assert retries[0]["attempt"] == 2
        assert len([1 for kind, p in events if kind == "iteration_started"]) == 1
        assert "private upstream" not in json.dumps(events)
    asyncio.run(scenario())


def test_agent_lifecycle_reports_provider_failure_and_stop_reason():
    async def scenario():
        events = []
        provider = FailingProvider([ProviderAuthenticationError("private key")])
        await AgentSubgraphs(provider, PermissionedTools(), BudgetManager(), lambda state: {}, models=MODELS,
                             emit=recorder(events)).run_specialist(task())
        assert [kind for kind, p in events if kind.startswith("agent_")] == ["agent_started", "agent_completed"]
        end = next(p for kind, p in events if kind == "agent_completed")
        assert end["outcome"] == "failed" and end["stop_reason"] == "model_unavailable"
        failed = next(p for kind, p in events if kind == "model_call_completed")
        assert failed["error_code"] == "provider_authentication"
        assert end["run_id"] == failed["run_id"]
        assert "private key" not in json.dumps(events)
    asyncio.run(scenario())


def test_exhausted_admission_reports_stop_without_a_model_call():
    async def scenario():
        events, budget = [], BudgetManager()
        budget.ledger.agent_usage[AgentId.BUG_RELIABILITY] = TokenUsage(prompt_tokens=50_000)
        await AgentSubgraphs(ScriptedProvider([]), PermissionedTools(), budget, lambda state: {}, models=MODELS,
                             emit=recorder(events)).run_specialist(task())
        assert not [p for kind, p in events if kind.startswith("model_call_")]
        completed = [p for kind, p in events if kind == "agent_completed"]
        assert len(completed) == 1 and completed[0]["stop_reason"] == "budget_exhausted"
    asyncio.run(scenario())


def test_real_cancellation_closes_model_and_agent_events():
    async def scenario():
        entered, events = asyncio.Event(), []
        class Provider:
            async def generate_completion(self, request):
                entered.set()
                await asyncio.Event().wait()
        runtime = AgentSubgraphs(Provider(), PermissionedTools(), BudgetManager(), lambda state: {}, models=MODELS,
                                 emit=recorder(events))
        operation = asyncio.create_task(runtime.run_specialist(task()))
        await asyncio.wait_for(entered.wait(), 1)
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation
        ended = [p for kind, p in events if kind in {"model_call_completed", "agent_completed"}]
        assert len(ended) == 2 and all(p["outcome"] == "cancelled" for p in ended)
        assert ended[-1]["stop_reason"] == "cancelled"
        assert ended[0]["total_tokens"] > 1000
    asyncio.run(scenario())


def test_evidence_events_distinguish_retrieval_delivery_and_inspection():
    async def scenario():
        events, tools = [], PermissionedTools()
        async def ast(arguments, work):
            return ToolObservation(evidence_ref="ast-1")
        tools.register("parse_ast", ast)
        provider = ScriptedProvider([
            {"kind": "call_tool", "tool": "parse_ast", "arguments": {"file_path": "service.py"}},
            {"kind": "submit_candidates", "payload": result(), "inspected_evidence": ["ast-1"]}])
        def context(state):
            return {"evidence": [{"evidence_ref": ref, "offset": 0, "end_offset": 2,
                "total_chars": 2, "excerpt": "{}", "source_scope": ["service.py"]}
                for ref in state["private_state"].evidence_refs]}
        await AgentSubgraphs(provider, tools, BudgetManager(), context, models=MODELS,
                             emit=recorder(events)).run_specialist(task())
        selected = [(kind, p) for kind, p in events if kind.startswith("evidence_")]
        assert [kind for kind, p in selected] == ["evidence_retrieved", "evidence_delivered", "evidence_inspected"]
        assert all(p["evidence_ref"] == "ast-1" for kind, p in selected)
        assert not [kind for kind, p in events if kind == "file_opened"]
        calls = [p for kind, p in events if kind in {"tool_called", "tool_result"}]
        assert len(calls) == 2 and calls[0]["operation_id"] == calls[1]["operation_id"]
        assert calls[1]["outcome"] == "succeeded" and calls[1]["duration_seconds"] >= 0
    asyncio.run(scenario())


def test_recoverable_tool_error_has_failed_result_without_fake_evidence():
    async def scenario():
        events, tools = [], PermissionedTools()
        async def broken(*args):
            raise LookupError("private source and token")
        tools.register("parse_ast", broken)
        provider = ScriptedProvider([
            {"kind": "call_tool", "tool": "parse_ast", "arguments": {"file_path": "service.py"}},
            {"kind": "submit_candidates", "payload": result()}])
        await AgentSubgraphs(provider, tools, BudgetManager(), lambda state: {}, models=MODELS,
                             emit=recorder(events)).run_specialist(task())
        ends = [p for kind, p in events if kind == "tool_result"]
        assert len(ends) == 1 and ends[0]["outcome"] == "failed"
        assert ends[0]["error_code"] == "recoverable_tool_error"
        assert not [p for kind, p in events if kind == "evidence_retrieved"]
        assert "private source" not in json.dumps(events)
    asyncio.run(scenario())


@pytest.mark.parametrize("invalid", [False, True])
def test_full_timeline_tracks_publication_verification_and_final_acceptance(tmp_path, invalid):
    from fastapi.testclient import TestClient
    from tests.test_canonical_workflow import ReviewProvider
    from tests.test_review_service import ALICE, app, completed, submit
    with TestClient(app(tmp_path, ReviewProvider(invalid=invalid))) as client:
        identity, _ = submit(client)
        assert completed(client, identity)["status"] == "completed"
        events = client.get(f"/api/jobs/{identity}/events?limit=1000", headers=ALICE).json()["events"]
        kinds = [e["kind"] for e in events]
        assert kinds.count("agent_started") == kinds.count("agent_completed") == 3
        assert kinds.count("model_call_started") == kinds.count("model_call_completed") == 5
        assert "candidate_submitted" in kinds and "verification_completed" in kinds
        assert kinds.count("finding_created") == (0 if invalid else 1)
        assert kinds.count("candidate_rejected") == (1 if invalid else 0)
        gate = [e for e in events if e["payload"].get("phase") == "structural_gate" and e["kind"].startswith("validation_")]
        assert gate[-1]["kind"] == ("validation_failed" if invalid else "validation_passed")
        assert kinds.index("finalization_started") < kinds.index("finalization_completed") < kinds.index("job_completed")
        assert kinds.index("report_render_started") < kinds.index("report_render_completed")
        accepted = [e for e in events if e["kind"] == "validation_passed" and e["payload"].get("phase") == "acceptance"]
        assert len(accepted) == 1
        assert "return items[0]" not in json.dumps(events)


def test_metadata_export_correlates_random_runs_and_calls_without_private_identifiers(tmp_path):
    from devwatch.review.jobs import EventStore, PersistedEvent
    from devwatch.review.observability import MetadataExporter
    store, calls = EventStore(tmp_path / "events.sqlite"), []
    job, operation, run = uuid4().hex, uuid4().hex, uuid4().hex
    for sequence, kind in enumerate(["model_call_started", "model_call_completed"], 1):
        store.append(PersistedEvent(event_id=uuid4().hex, job_id=job, sequence=sequence, kind=kind,
            timestamp=time.time(), payload=EventPayload(agent_id="bug_reliability", task_id="private-task-name",
                evidence_ref="private-evidence", phase="investigation", iteration=2, attempt=1,
                operation_id=operation, run_id=run, outcome="succeeded" if sequence == 2 else None)))
    class Client:
        def create_run(self, **kwargs):
            calls.append(kwargs)
    assert asyncio.run(MetadataExporter(store, client=Client()).export_once()) == 2
    metadata = [call["extra"]["metadata"] for call in calls]
    assert all(item.get("run_id") == run for item in metadata)
    assert not any(key in item for item in metadata for key in ("review_trace", "task_trace", "evidence_trace"))
    assert [item["sequence"] for item in metadata] == [1, 2]
    assert all(item["operation_id"] == operation and item["iteration"] == 2 for item in metadata)
    assert all(call["inputs"] == call["outputs"] == {} for call in calls)
    encoded = json.dumps(calls, default=str)
    assert job not in encoded and "private-task-name" not in encoded and "private-evidence" not in encoded


def test_cli_event_replay_drains_multiple_pages_without_restarting_review(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from typer.testing import CliRunner
    from devwatch.cli import app as cli
    from tests.test_durable_cli import connect
    from tests.test_review_service import ALICE, app, completed, submit
    application = app(tmp_path)
    with TestClient(application) as http:
        identity, _ = submit(http)
        assert completed(http, identity)["status"] == "completed"
        owner = http.get(f"/api/jobs/{identity}/snapshot", headers=ALICE).json()["owner"]
        for _ in range(120):
            application.state.jobs.emit(identity, owner=owner, kind="budget_updated", payload={"total_tokens": 75})
        expected = http.get(f"/api/jobs/{identity}/events?limit=1000", headers=ALICE).json()["events"]
        _, transport = connect(monkeypatch, http)
        output = CliRunner().invoke(cli, ["events", identity])
        assert output.exit_code == 0, output.output
        assert [json.loads(line) for line in output.output.splitlines()] == expected
        later = CliRunner().invoke(cli, ["events", identity, "--after", "100"])
        assert later.exit_code == 0, later.output
        assert [json.loads(line) for line in later.output.splitlines()] == [event for event in expected if event["sequence"] > 100]
        assert len(transport.requests) >= 2 and all(request.get_method() == "GET" for request in transport.requests)


def test_event_persistence_failure_does_not_become_a_successful_partial_agent():
    async def scenario():
        def fail(kind, **payload):
            if kind == "model_call_started":
                raise OSError("private event store details")
        runtime = AgentSubgraphs(ScriptedProvider([]), PermissionedTools(), BudgetManager(), lambda state: {},
                                 models=MODELS, emit=fail)
        with pytest.raises(OSError):
            await runtime.run_specialist(task())
    asyncio.run(scenario())


def test_websocket_delivers_model_start_before_completion_and_disconnect_keeps_work_running(tmp_path):
    import threading
    from fastapi.testclient import TestClient
    from tests.test_canonical_workflow import ReviewProvider
    from tests.test_review_service import ALICE, app, completed, submit
    entered, release = threading.Event(), threading.Event()
    class Held(ReviewProvider):
        async def generate_completion(self, request):
            if json.loads(request.prompt)["task"]["agent_id"] == "planner":
                entered.set()
                while not release.is_set():
                    await asyncio.sleep(.01)
            return await super().generate_completion(request)
    with TestClient(app(tmp_path, Held())) as client:
        identity, _ = submit(client)
        assert entered.wait(3)
        try:
            with client.websocket_connect(f"/api/jobs/{identity}/ws", headers=ALICE) as socket:
                observed = []
                while not observed or observed[-1]["kind"] != "model_call_started":
                    observed.append(socket.receive_json())
            assert not [e for e in observed if e["kind"] == "model_call_completed"]
            assert client.get(f"/api/jobs/{identity}", headers=ALICE).json()["status"] == "running"
            last = observed[-1]["sequence"]
        finally:
            release.set()
        assert completed(client, identity)["status"] == "completed"
        replay = client.get(f"/api/jobs/{identity}/events?after={last}&limit=1000", headers=ALICE).json()["events"]
        stream = client.get(f"/api/jobs/{identity}/stream", headers={**ALICE, "Last-Event-ID": str(last)})
        streamed = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")]
        assert streamed == replay
        assert replay[0]["sequence"] == last + 1
        assert any(e["kind"] == "model_call_completed" for e in replay)


@pytest.mark.parametrize("interrupt", [False, True])
def test_cli_follow_observes_completion_or_disconnect_without_job_control(tmp_path, monkeypatch, interrupt):
    import threading
    from fastapi.testclient import TestClient
    from typer.testing import CliRunner
    from devwatch.cli import app as cli
    from tests.test_canonical_workflow import ReviewProvider
    from tests.test_durable_cli import connect
    from tests.test_review_service import ALICE, app, completed, submit
    entered, release = threading.Event(), threading.Event()
    class Held(ReviewProvider):
        async def generate_completion(self, request):
            if json.loads(request.prompt)["task"]["agent_id"] == "planner":
                entered.set()
                while not release.is_set():
                    await asyncio.sleep(.01)
            return await super().generate_completion(request)
    with TestClient(app(tmp_path, Held())) as http:
        identity, _ = submit(http)
        assert entered.wait(3)
        _, transport = connect(monkeypatch, http)
        try:
            original_sleep = time.sleep
            def observation_pause(seconds):
                if interrupt:
                    raise KeyboardInterrupt
                release.set()
                original_sleep(.01)
            with monkeypatch.context() as patch:
                patch.setattr("devwatch.cli.time.sleep", observation_pause)
                output = CliRunner().invoke(cli, ["events", identity, "--follow"])
            if interrupt:
                assert output.exit_code == 130 and "no job cancellation" in output.output
                assert http.get(f"/api/jobs/{identity}", headers=ALICE).json()["status"] == "running"
            else:
                assert output.exit_code == 0, output.output
                assert json.loads(output.output.splitlines()[-1])["kind"] == "job_completed"
            assert all(request.get_method() == "GET" for request in transport.requests)
        finally:
            release.set()
        assert completed(http, identity)["status"] == "completed"


def test_report_render_failure_closes_finalization_as_failed(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from devwatch.review.workflow import CanonicalReviewExecutor
    from tests.test_review_service import ALICE, app, completed, submit
    async def fail(*args):
        raise OSError("private report path")
    monkeypatch.setattr(CanonicalReviewExecutor, "render_report", fail)
    with TestClient(app(tmp_path)) as client:
        identity, _ = submit(client)
        assert completed(client, identity)["status"] == "failed"
        events = client.get(f"/api/jobs/{identity}/events?limit=1000", headers=ALICE).json()["events"]
        for kind in ("report_render_completed", "finalization_completed"):
            ended = [event for event in events if event["kind"] == kind]
            assert len(ended) == 1 and ended[0]["payload"]["outcome"] == "failed"
        assert "private report path" not in json.dumps(events)


def test_arbitrary_model_stop_text_is_not_exportable_telemetry():
    async def scenario():
        events, payload = [], result()
        payload["stop_reason"] = "private source or reasoning text"
        await AgentSubgraphs(ScriptedProvider([{"kind": "submit_candidates", "payload": payload}]),
            PermissionedTools(), BudgetManager(), lambda state: {}, models=MODELS,
            emit=recorder(events)).run_specialist(task())
        end = next(p for kind, p in events if kind == "agent_completed")
        assert end["stop_reason"] == "invalid_schema" and end["outcome"] == "failed"
        assert "private source" not in json.dumps(events)
    asyncio.run(scenario())


def test_invalid_remote_event_metadata_has_a_sanitized_client_error():
    import io
    from devwatch.review.client import ClientError, ReviewClient
    identity = "a" * 32
    def malformed(request, timeout):
        data = {"events": [{"event_id": "e1", "job_id": identity, "sequence": 1,
            "timestamp": 1, "kind": "model_call_started", "payload": {"prompt": "private source and key"}}], "next_cursor": 1}
        response = io.BytesIO(json.dumps(data).encode())
        response.status, response.headers = 200, {"content-type": "application/json"}
        return response
    with pytest.raises(ClientError) as error:
        ReviewClient("http://localhost:8000", opener=malformed).events(identity)
    assert "private source" not in str(error.value)


def test_truncated_completion_records_actual_usage_and_failed_finish():
    async def scenario():
        events, budget = [], BudgetManager()
        class Truncated(ScriptedProvider):
            async def generate_completion(self, request):
                response = await super().generate_completion(request)
                return response.model_copy(update={"finish_reason": "length"})
        output = await AgentSubgraphs(Truncated([{"kind": "submit_candidates", "payload": result()}]),
            PermissionedTools(), budget, lambda state: {}, models=MODELS, emit=recorder(events)).run_specialist(task())
        model = next(p for kind, p in events if kind == "model_call_completed")
        assert model["outcome"] == "failed" and model["finish_reason"] == "length"
        assert model["total_tokens"] == budget.ledger.total_tokens == 15
        assert output["output"].stop_reason == "provider_truncated"
        assert not [p for kind, p in events if kind == "candidate_submitted"]
    asyncio.run(scenario())


def test_unknown_call_event_and_cost_settlement_rollback_together(tmp_path, monkeypatch):
    from devwatch.review.jobs import JobStore
    store = JobStore(tmp_path / "jobs.sqlite")
    job = store.submit(owner="alice", request={}, idempotency_key="reconciliation")
    budget = BudgetManager()
    operation = budget.reserve_model(AgentId.BUG_RELIABILITY, 100)
    store.update_ledger(job.job_id, owner="alice", ledger=budget.ledger)
    budget.record_model(operation, prompt_tokens=100, completion_tokens=0)
    payload = EventPayload(agent_id="bug_reliability", operation_id=operation, total_tokens=100, outcome="unknown")
    original = store._enqueue_event
    def fail(db, identity, kind, event_payload):
        if kind == "model_call_completed":
            raise OSError("private outbox path")
        return original(db, identity, kind, event_payload)
    with monkeypatch.context() as patch:
        patch.setattr(store, "_enqueue_event", fail)
        with pytest.raises(OSError):
            store.update_ledger(job.job_id, owner="alice", ledger=budget.ledger, model_completions=[payload])
    saved = store.get(job.job_id, owner="alice").ledger
    assert operation in saved.inflight and saved.total_tokens == 0
    assert not [event for event in store.pending_events() if event.kind == "model_call_completed"]
    store.update_ledger(job.job_id, owner="alice", ledger=budget.ledger, model_completions=[payload])
    assert store.get(job.job_id, owner="alice").ledger.total_tokens == 100
    assert len([event for event in store.pending_events() if event.kind == "model_call_completed"]) == 1


def test_visible_model_completion_already_has_durable_cost_settlement(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from devwatch.review.workflow import _ReviewSession
    from tests.test_review_service import app, completed, submit
    observed = []
    original = _ReviewSession.emit
    def inspect(self, kind, **payload):
        original(self, kind, **payload)
        if kind == "model_call_completed":
            ledger = self.executor.jobs.get(self.job.job_id, owner=self.job.owner).ledger
            observed.append((payload["operation_id"] in ledger.inflight, ledger.total_tokens, payload["total_tokens"]))
    monkeypatch.setattr(_ReviewSession, "emit", inspect)
    with TestClient(app(tmp_path)) as client:
        identity, _ = submit(client)
        assert completed(client, identity)["status"] == "completed"
    assert len(observed) == 5
    assert all(not pending and charged >= consumed for pending, charged, consumed in observed)
