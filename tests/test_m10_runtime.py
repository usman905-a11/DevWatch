"""Real runtime over loopback HTTP, scripted models and scoped fault injection."""
import json

import pytest

from devwatch.review.budgets import BudgetManager
from devwatch.review.client import ClientError
from devwatch.review.contracts import BalancedLimits
from devwatch.review.jobs import JobStore

from tests.runtime_scenarios import FILES, ScenarioProvider, live_runtime, repository, timeline


def test_normal_seven_agent_review_captures_source_and_publishes_verified_formats(tmp_path):
    # Catches omitted specialist routing, broken evidence handoff, early acceptance,
    # missing persistence and clients reading mutable working-tree source.
    source = tmp_path / "repository"
    capture = repository(source)
    provider = ScenarioProvider()
    with live_runtime(tmp_path / "runtime", provider) as (client, app):
        snapshot = client.capture(capture)
        current = client.submit(snapshot.snapshot_id, idempotency_key="normal")
        (source / "logic.py").write_text("changed after capture\n")
        done = client.wait(current.job_id, wait_seconds=20, poll_seconds=.02)
        assert done.status == "completed"
        report = json.loads(client.report(done, format="json"))
        assert len(report["confirmed_defects"]) == 1
        finding = report["confirmed_defects"][0]
        assert finding["title"] == "Empty input raises"
        assert finding["location"]["file_path"] == "logic.py" and finding["location"]["start_line"] == 2
        assert finding["location"]["snapshot_id"] == snapshot.snapshot_id
        assert sorted(report["coverage"]["inspected_files"]) == sorted(FILES.values())
        assert not report["coverage"]["failed"]
        assert "Empty input raises" in client.report(done, format="markdown")
        assert client.report(done, format="pdf").startswith(b"%PDF-")
        assert "items[0]" in client.source(done, "logic.py")["data"]
        assert (source / "logic.py").read_text() == "changed after capture\n"
        events = timeline(client, done.job_id)
        roles = {event["payload"]["agent_id"] for event in events if event["kind"] == "agent_started"}
        assert roles == set(FILES) | {"planner", "synthesizer_verifier"}
        kinds = [event["kind"] for event in events]
        assert kinds.index("finding_created") < kinds.index("verification_completed") < kinds.index("report_render_started") < kinds.index("job_completed")
        assert done.ledger.total_tokens == 210 and not done.ledger.inflight
        assert len([event for event in events if event["kind"] == "tool_called"]) == 7
        assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
        assert "items[0]" not in json.dumps(events)
        own = client.evidence(done, finding["evidence_refs"][0])
        assert own["provenance"]["agent_id"] == "synthesizer_verifier"
        assert client.submit(snapshot.snapshot_id, idempotency_key="normal").job_id == done.job_id
        assert client.status(done.job_id).ledger.total_tokens == 210
        print(json.dumps({"scenario": "normal", "events": len(events), "model_calls": 14, "tool_calls": 7, "tokens": done.ledger.total_tokens}))


def configured_limits(monkeypatch, **fields):
    """Supply test admission inputs; retain real store/outbox and budget behavior."""
    original = JobStore.submit

    def submit(store, **kwargs):
        kwargs["limits"] = BalancedLimits(**fields)
        return original(store, **kwargs)
    monkeypatch.setattr(JobStore, "submit", submit)


@pytest.mark.parametrize("mode, failed_task, failure", [
    ("tool_failure", "bug_reliability:read_source", "recoverable_tool_error"),
    ("invalid_arguments", "bug_reliability:read_source", "recoverable_tool_error"),
    ("unavailable", "performance_scalability:benchmark", "recoverable_tool_error"),
    ("unapproved", "performance_scalability", "permission_denied"),
    ("malformed", None, None),
    ("malformed_exhausted", "bug_reliability", "invalid_schema"),
    ("truncated", "bug_reliability", "provider_truncated"),
    ("budget", "bug_reliability", "budget_exhausted"),
    ("provider_timeout", "bug_reliability", "model_unavailable"),
    ("specialist_failure", "bug_reliability", "specialist_failed"),
    ("final_repair", None, None),
    ("final_repair_exhausted", "__final", "invalid_schema"),
])
def test_runtime_faults_preserve_verified_siblings_and_honest_coverage(tmp_path, monkeypatch, mode, failed_task, failure):
    # Catches unbounded repair/replay, false success after failed tools, loss of
    # sibling findings, acceptance of truncated output and unaccounted calls.
    capture = repository(tmp_path / "repository")
    provider = ScenarioProvider(mode)
    if mode == "provider_timeout":
        original = BudgetManager.timeout_for
        monkeypatch.setattr(BudgetManager, "timeout_for", lambda self, operation:
            min(.05, original(self, operation)) if operation == "provider" else original(self, operation))
    if mode == "specialist_failure":
        from devwatch.review.workflow import _ReviewSession
        original_run = _ReviewSession.run_task

        async def crash(session, task, **kwargs):
            if task.agent_id.value == "bug_reliability":
                raise RuntimeError("private-m10-error")
            return await original_run(session, task, **kwargs)
        monkeypatch.setattr(_ReviewSession, "run_task", crash)
    if mode == "unavailable":
        from devwatch.review.repository import RepositoryContext
        original_tools = RepositoryContext.tools

        def missing_benchmark(repository, *args, **kwargs):
            tools = original_tools(repository, *args, **kwargs)
            tools._handlers.pop("benchmark")  # Inject a missing optional backend.
            return tools
        monkeypatch.setattr(RepositoryContext, "tools", missing_benchmark)
    with live_runtime(tmp_path / "runtime", provider) as (client, app):
        snapshot = client.capture(capture)
        submitted = client.submit(snapshot.snapshot_id, idempotency_key=mode)
        done = client.wait(submitted.job_id, wait_seconds=25, poll_seconds=.02)
        assert done.status == "completed"
        report = json.loads(client.report(done, format="json"))
        if mode == 'final_repair_exhausted':
            # This fault now omits a verifier decision, rather than a summary.
            assert report['confirmed_defects'] == []
            assert len(report['uncertain_high_impact_candidates']) == 1
            assert report['uncertain_high_impact_candidates'][0]['confidence'] <= .5
        else:
            assert len(report["confirmed_defects"]) == 1
            assert report["confirmed_defects"][0]["title"] == "Empty input raises"
        assert "logic.py" in report["coverage"]["inspected_files"]
        assert not done.ledger.inflight
        if failed_task is not None:
            assert report["coverage"]["failed"][failed_task] == failure
        else:
            assert not report["coverage"]["failed"]
        assert "Empty input raises" in client.report(done, format="markdown")
        assert client.report(done, format="pdf").startswith(b"%PDF-")
        events = timeline(client, done.job_id)
        assert events[-1]["kind"] == "job_completed"
        assert "private-m10-error" not in json.dumps(events) + json.dumps(report)
        starts = [event for event in events if event["kind"] == "model_call_started"]
        completions = [event for event in events if event["kind"] == "model_call_completed"]
        assert {event["payload"]["operation_id"] for event in starts} == {event["payload"]["operation_id"] for event in completions}
        assert done.ledger.total_tokens == sum(event["payload"]["total_tokens"] for event in completions)
        if mode in {"malformed", "malformed_exhausted", "final_repair", "final_repair_exhausted"}:
            task = "__final" if mode.startswith("final_") else "bug_reliability"
            assert done.ledger.task_schema_repairs[task] == 1
            assert len([event for event in events if event["kind"] == "validation_failed" and event["payload"]["error_code"] == "invalid_schema"]) == (2 if mode.endswith("exhausted") else 1)
        if mode == "budget":
            assert done.ledger.task_iterations["bug_reliability"] == 8
            assert done.ledger.task_tools["bug_reliability"] == 8
        if mode in {"truncated", "provider_timeout"}:
            assert len([event for event in starts if event["payload"]["task_id"] == "bug_reliability"]) == 1
        if mode == "invalid_arguments":
            assert done.ledger.task_tools["bug_reliability"] == 1
        if mode in {"tool_failure", "unavailable"}:
            assert any(event["kind"] == "tool_result" and event["payload"]["outcome"] == "failed" and
                       event["payload"]["evidence_ref"] is None for event in events)
        if mode == "provider_timeout":
            assert provider.drained.is_set()
        for path, content in capture.files.items():
            assert (tmp_path / "repository" / path).read_bytes() == content.encode("utf-8")
        print(json.dumps({"scenario": mode, "events": len(events), "model_calls": len(starts), "tokens": done.ledger.total_tokens}))


@pytest.mark.parametrize("mode, limits, stop", [
    ("context", {"model_context_tokens": 4096}, "prompt_context_limit"),
    ("global_budget", {"job_tokens": 1, "final_agent_tokens": 1}, "budget_exhausted"),
])
def test_runtime_admission_refuses_model_dispatch_and_returns_partial_report(tmp_path, monkeypatch, mode, limits, stop):
    configured_limits(monkeypatch, **limits)
    capture = repository(tmp_path / "repository")
    with live_runtime(tmp_path / "runtime", ScenarioProvider()) as (client, app):
        snapshot = client.capture(capture)
        done = client.wait(client.submit(snapshot.snapshot_id, idempotency_key=mode).job_id,
                           wait_seconds=20, poll_seconds=.02)
        assert done.status == "completed"
        report = json.loads(client.report(done, format="json"))
        assert not report["confirmed_defects"] and not report["coverage"]["inspected_files"]
        assert report["coverage"]["failed"]["__planner"] == stop
        assert done.ledger.total_tokens == 0 and not done.ledger.inflight
        events = timeline(client, done.job_id)
        assert not any(event["kind"] == "model_call_started" for event in events)
        assert events[-1]["kind"] == "job_completed"
        assert client.report(done, format="pdf").startswith(b"%PDF-")


@pytest.mark.parametrize("context_tokens", [32768, 20000])
def test_oversized_evidence_is_paged_inspected_and_bounded_through_final_report(tmp_path, monkeypatch, context_tokens):
    configured_limits(monkeypatch, model_context_tokens=context_tokens)
    capture = repository(tmp_path / "repository", large=True)
    provider = ScenarioProvider("oversized")
    with live_runtime(tmp_path / "runtime", provider) as (client, app):
        snapshot = client.capture(capture)
        done = client.wait(client.submit(snapshot.snapshot_id, idempotency_key="large").job_id,
                           wait_seconds=25, poll_seconds=.02)
        assert done.status == "completed"
        report = json.loads(client.report(done, format="json"))
        assert len(report["confirmed_defects"]) == 1 and not report["coverage"]["failed"]
        events = timeline(client, done.job_id)
        inspected = [event["payload"] for event in events if event["kind"] == "evidence_inspected" and
                     event["payload"]["task_id"] == "quality_testability" and event["payload"]["offset"] == 12000]
        ast = next(event["payload"]["evidence_ref"] for event in events if event["kind"] == "tool_result" and event["payload"]["tool"] == "parse_ast")
        evidence = client.evidence(done, ast)
        assert evidence["tool"] == "parse_ast" and len(json.dumps(evidence)) > 12000
        assert all(call["request_bound"] <= context_tokens for call in provider.observed)
        # M15 fits the response reservation before dropping retrievable evidence.
        # Both windows can now deliver and acknowledge the requested AST page.
        assert any(page["end_offset"] == 13000 and page["evidence_ref"] == ast for page in inspected)
        assert not done.ledger.inflight


def test_explicit_cancellation_drains_provider_without_publishing_report(tmp_path):
    capture = repository(tmp_path / "repository")
    provider = ScenarioProvider("pause")
    with live_runtime(tmp_path / "runtime", provider) as (client, app):
        snapshot = client.capture(capture)
        current = client.submit(snapshot.snapshot_id, idempotency_key="cancel")
        assert provider.entered.wait(15)
        assert client.cancel(current.job_id).status == "cancelled"
        assert provider.drained.is_set()
        done = client.status(current.job_id)
        assert not done.ledger.inflight
        with pytest.raises(ClientError, match="finalized"):
            client.report(done, format="pdf")
        with pytest.raises(ClientError, match="HTTP 409"):
            client._request("GET", f"/api/jobs/{done.job_id}/report?format=pdf")
        assert not list((tmp_path / "runtime" / "artifacts" / "reports").rglob("*.pdf"))
        assert not any(event["kind"] == "report_render_completed" for event in timeline(client, done.job_id))


def test_service_restart_resumes_saved_verification_without_repeating_specialists(tmp_path):
    capture = repository(tmp_path / "repository")
    first = ScenarioProvider("pause")
    root = tmp_path / "runtime"
    with live_runtime(root, first) as (client, app):
        snapshot = client.capture(capture)
        current = client.submit(snapshot.snapshot_id, idempotency_key="resume")
        assert first.entered.wait(15)
    assert first.drained.is_set()
    second = ScenarioProvider()
    with live_runtime(root, second) as (client, app):
        interrupted = client.status(current.job_id)
        assert interrupted.status == "interrupted" and not interrupted.ledger.inflight
        before = timeline(client, current.job_id)
        cursor = before[-1]["sequence"]
        done = client.wait(client.resume(current.job_id).job_id, wait_seconds=20, poll_seconds=.02)
        assert done.status == "completed" and done.job_id == current.job_id and done.snapshot_id == snapshot.snapshot_id
        assert done.ledger.total_tokens == interrupted.ledger.total_tokens
        report = json.loads(client.report(done, format="json"))
        assert len(report["confirmed_defects"]) == 1
        tail = [event for event in timeline(client, done.job_id) if event["sequence"] > cursor]
        assert [event["payload"]["phase"] for event in tail if event["kind"] == "model_call_started"] == []
        assert not any(event["kind"] == "tool_called" for event in tail)
        assert not done.ledger.inflight
        assert client.submit(snapshot.snapshot_id, idempotency_key="resume").job_id == done.job_id


def test_real_job_deadline_drains_synthesis_and_publishes_verified_partial(tmp_path, monkeypatch):
    configured_limits(monkeypatch, review_seconds=15)
    capture = repository(tmp_path / "repository")
    provider = ScenarioProvider("deadline")
    with live_runtime(tmp_path / "runtime", provider) as (client, app):
        snapshot = client.capture(capture)
        done = client.wait(client.submit(snapshot.snapshot_id, idempotency_key="deadline").job_id,
                           wait_seconds=30, poll_seconds=.04)
        assert done.status == "completed" and provider.entered.is_set() and provider.drained.is_set()
        report = json.loads(client.report(done, format="json"))
        assert report["coverage"]["failed"]["__job"] == "review_time_exhausted"
        assert len(report["confirmed_defects"]) == 1
        assert done.ledger.elapsed_seconds >= 15 and not done.ledger.inflight
        assert client.report(done, format="pdf").startswith(b"%PDF-")
