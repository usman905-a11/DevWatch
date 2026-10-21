"""Reproduce visible M13 live failures without calling a remote provider."""

import json

import httpx
import pytest

from devwatch.providers.base import LLMRequest
from devwatch.providers.openai_adapter import OpenAIProviderAdapter
from devwatch.review.contracts import BalancedLimits, ModelTier, SPECIALISTS
from devwatch.review.jobs import DurableJobManager
from devwatch.review.stores import RepoCache
from devwatch.review.workflow import CanonicalReviewExecutor
from tests.test_canonical_workflow import ReviewProvider, stores
from tests.test_repository_context import setup_repository


def test_short_source_reads_clamp_requested_end_to_real_eof(tmp_path):
    _, _, _, repository, task = setup_repository(tmp_path)
    observation = repository._read_source({"file_path": "service.py", "start_line": 1, "end_line": 80}, task)
    record = repository.evidence(observation.evidence_ref)
    assert (record["start_line"], record["end_line"]) == (1, 2)
    assert record["data"] == "def first(items):\n    return items[0]"


@pytest.mark.parametrize("arguments", [
    {"start_line": 3}, {"start_line": 2, "end_line": 1},
    {"start_line": 1, "end_line": 201}, {"start_line": True, "end_line": 2},
])
def test_eof_clamping_does_not_admit_invalid_or_unbounded_ranges(tmp_path, arguments):
    _, _, _, repository, task = setup_repository(tmp_path)
    with pytest.raises(ValueError):
        repository._read_source({"file_path": "service.py", **arguments}, task)


@pytest.mark.asyncio
@pytest.mark.parametrize("specialist", sorted(SPECIALISTS, key=lambda role: role.value))
@pytest.mark.parametrize("context_tokens", [32768, 20000])
async def test_every_role_uses_json_actions_and_bounded_reasoning_through_sdk_full_graph(tmp_path, monkeypatch, specialist, context_tokens):
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-only")
    provider, requests, clients = ReviewProvider(), [], []
    async def reply(request):
        body = json.loads(request.content)
        requests.append(body)
        prompt = json.loads(body["messages"][1]["content"])
        role = prompt["task"]["agent_id"]
        # The fixture provider supplies one source-backed claim for every role;
        # permission checks, actual source retrieval, verification and reports stay real.
        if role == specialist.value:
            prompt["task"]["agent_id"] = "logic_correctness"
        response = await provider.generate_completion(LLMRequest(model=body["model"], prompt=json.dumps(prompt)))
        action = json.loads(response.content)
        if role == "planner":
            action["payload"]["selected_agents"] = [specialist.value]
            action["payload"]["review_tasks"][0]["agent_id"] = specialist.value
        elif role == specialist.value and action["kind"] == "submit_candidates":
            action["payload"]["agent_id"] = specialist.value
        if action["kind"] == "call_tool" and action["tool"] == "read_source":
            action["arguments"]["end_line"] = 80
        content = json.dumps(action)
        # Visible fenced JSON was observed live outside JSON mode. Model the
        # provider's documented JSON-mode boundary rather than stripping fences.
        if body.get("response_format") != {"type": "json_object"}:
            content = "```json\n" + content + "\n```"
        return httpx.Response(200, json={"id": "fixture", "object": "chat.completion", "created": 1,
            "model": body["model"], "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": content}}],
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
                                   idempotency_key="m13-live-remediation",
                                   limits=BalancedLimits(model_context_tokens=context_tokens))
        done = await manager.wait(job.job_id, owner="alice")
    finally:
        await manager.close()
    assert done.status == "completed" and not done.ledger.inflight
    report = json.loads(done.result["json"])
    assert len(report["uncertain_high_impact_candidates"]) == 1 and not report["coverage"]["failed"]
    assert len(requests) == 4
    assert all(body["reasoning_effort"] == "low" for body in requests)
    assert all(body["response_format"] == {"type": "json_object"} for body in requests)
    for request in requests:
        bound = sum(len(message["content"].encode("utf-8")) for message in request["messages"]) + 512 + request["max_tokens"]
        assert bound <= context_tokens
        assert 512 <= request["max_tokens"] <= 8192
        prompt = json.loads(request["messages"][1]["content"])
        kinds = prompt["action_schema"]["properties"]["kind"]["enum"]
        if prompt["phase"] == "investigation":
            assert "submit_plan" not in kinds and "submit_verification" not in kinds
        elif prompt["phase"] == "verification":
            assert "submit_synthesis" not in kinds
        elif prompt["phase"] == "synthesis":
            assert "submit_verification" not in kinds
    assert all(client.is_closed for client in clients)
