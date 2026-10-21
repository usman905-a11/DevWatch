"""SDK-to-report verification of a source retrieval correction, without paid calls."""

import json

import httpx
import pytest

from devwatch.providers.base import LLMRequest
from devwatch.providers.openai_adapter import OpenAIProviderAdapter
from devwatch.review.contracts import BalancedLimits, ModelTier
from devwatch.review.jobs import DurableJobManager
from devwatch.review.stores import RepoCache
from devwatch.review.workflow import CanonicalReviewExecutor
from tests.test_canonical_workflow import ReviewProvider, stores


@pytest.mark.asyncio
@pytest.mark.parametrize("context_tokens", [32768, 20000])
async def test_sdk_range_correction_preserves_delivery_accounting_through_report(tmp_path, monkeypatch, context_tokens):
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-only")
    provider, requests, prompts, clients = ReviewProvider(), [], [], []
    async def reply(request):
        body = json.loads(request.content)
        prompt = json.loads(body["messages"][1]["content"])
        requests.append(body)
        prompts.append(prompt)
        response = await provider.generate_completion(LLMRequest(model=body["model"], prompt=json.dumps(prompt)))
        action = json.loads(response.content)
        if prompt["task"]["agent_id"] == "logic_correctness" and action["kind"] == "call_tool":
            feedback = prompt.get("tool_diagnostic")
            if feedback is None:
                action["arguments"]["start_line"] = 99
            else:
                assert feedback["code"] == "invalid_source_range"
                assert feedback["details"]["line_count"] == 2
                assert feedback["arguments"]["start_line"] == 99
                assert not prompt["private_state"]["evidence_refs"]
                action["arguments"].update(start_line=1, end_line=feedback["details"]["line_count"])
        return httpx.Response(200, json={"id": "m15-fixture", "object": "chat.completion", "created": 1,
            "model": body["model"], "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(action)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})
    def transport():
        client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
        clients.append(client)
        return client
    adapter = OpenAIProviderAdapter(provider_name="gemini", request_delay=0)
    monkeypatch.setattr(adapter, "_get_httpx_async_client", transport)
    layout, artifacts, snapshot, jobs, events = stores(tmp_path)
    executor = CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events,
        adapter, models={tier: "fixture-model" for tier in ModelTier})
    manager = DurableJobManager(jobs, events, executor)
    try:
        job = await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id},
            idempotency_key="m15-recovery", limits=BalancedLimits(model_context_tokens=context_tokens))
        done = await manager.wait(job.job_id, owner="alice")
    finally:
        await manager.close()
    assert done.status == "completed" and not done.ledger.inflight
    report = json.loads(done.result["json"])
    assert len(report["uncertain_high_impact_candidates"]) == 1
    assert report["coverage"]["inspected_files"] == ["service.py"], [
        {"role": prompt["task"]["agent_id"], "omissions": prompt["context_omissions"],
         "pages": len(prompt["selected_context"].get("evidence", [])),
         "input_bytes": sum(len(message["content"].encode("utf-8")) for message in request["messages"]),
         "output_tokens": request["max_tokens"]} for prompt, request in zip(prompts, requests)]
    # Retain the historical failed-call receipt even after successful correction.
    assert report["coverage"]["failed"] == {"logic-1:read_source": "recoverable_tool_error"}
    assert len(requests) == 5
    specialist = [prompt for prompt in prompts if prompt["task"]["agent_id"] == "logic_correctness"]
    assert specialist[-1]["tool_diagnostic"] is None
    assert specialist[-1]["selected_context"]["evidence"]
    for request in requests:
        assert request["reasoning_effort"] == "low"
        assert request["response_format"] == {"type": "json_object"}
        bound = sum(len(message["content"].encode("utf-8")) for message in request["messages"]) + 512 + request["max_tokens"]
        assert bound <= context_tokens
        assert request["max_tokens"] >= 512
    jobs.dispatch_events(events)
    stream = events.replay(job.job_id)
    results = [event.payload for event in stream if event.kind == "tool_result"]
    assert len(results) == 2
    assert results[0].outcome == "failed" and results[0].evidence_ref is None
    assert results[1].outcome == "succeeded" and results[1].evidence_ref
    acknowledged = [event for event in stream if event.kind == "evidence_inspected"
                    and event.payload.agent_id.value == "logic_correctness"]
    assert acknowledged
    assert all(client.is_closed for client in clients)
