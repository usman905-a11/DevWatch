"""Real SDK + full graph; only the remote HTTP provider is replaced."""

import json

import httpx
import pytest

from devwatch.providers.base import LLMRequest
from devwatch.providers.openai_adapter import OpenAIProviderAdapter
from devwatch.review.contracts import AgentId, ModelTier
from devwatch.review.jobs import DurableJobManager
from devwatch.review.stores import RepoCache
from devwatch.review.workflow import CanonicalReviewExecutor
from tests.test_canonical_workflow import ReviewProvider, stores


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,expected", [
    ("normal", None), ("bare_plan", None), ("incomplete", None), ("temporary", None),
    ("empty", "invalid_schema"), ("invalid_scope", "invalid_schema"),
    ("invalid_role", "invalid_schema"), ("duplicate", "invalid_schema"),
    ("incomplete_exhausted", "provider_incomplete"), ("refusal", "provider_incomplete"),
    ("quota", "model_unavailable"), ("authentication", "model_unavailable"),
])
async def test_sdk_planner_success_and_failure_reach_honest_full_graph_results(tmp_path, monkeypatch, mode, expected):
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-only")
    behavior, planner_calls, transports, bodies = ReviewProvider(), [], [], []
    async def reply(request):
        body = json.loads(request.content)
        bodies.append(body)
        prompt = json.loads(body["messages"][1]["content"])
        planner = prompt["task"]["agent_id"] == "planner"
        if planner:
            planner_calls.append(body)
            status = {"quota": 429, "authentication": 401}.get(mode)
            if mode == "temporary" and len(planner_calls) == 1:
                status = 503
            if status:
                return httpx.Response(status, json={"error": {"message": "private provider quota" if status == 429 else "private rejection",
                    "code": "insufficient_quota" if status == 429 else "fixture", "type": "fixture"}})
        response = await behavior.generate_completion(LLMRequest(model=body["model"],
            prompt=body["messages"][1]["content"], system_prompt=body["messages"][0]["content"]))
        action, finish, refusal = json.loads(response.content), "stop", None
        if planner:
            if mode == "bare_plan" and len(planner_calls) == 1:
                action = action["payload"]
            elif mode == "empty":
                action["payload"].update(selected_agents=[], review_tasks=[])
            elif mode == "invalid_scope":
                action["payload"]["review_tasks"][0]["files"] = ["missing.py"]
            elif mode == "invalid_role":
                action["payload"]["review_tasks"][0]["agent_id"] = "planner"
            elif mode == "duplicate":
                action["payload"]["review_tasks"] *= 2
            if mode == "incomplete_exhausted" or mode == "incomplete" and len(planner_calls) == 1:
                finish = None
            if mode == "refusal":
                refusal = "private refusal text"
        return httpx.Response(200, json={"id": "fixture", "object": "chat.completion", "created": 1,
            "model": body["model"], "choices": [{"index": 0, "message": {"role": "assistant",
                "content": json.dumps(action), "refusal": refusal}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})
    def transport():
        client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
        transports.append(client)
        return client
    adapter = OpenAIProviderAdapter(provider_name="gemini", request_delay=0)
    monkeypatch.setattr(adapter, "_get_httpx_async_client", transport)
    layout, artifacts, snapshot, jobs, events = stores(tmp_path)
    executor = CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events,
        adapter, models={tier: "fixture-model" for tier in ModelTier})
    manager = DurableJobManager(jobs, events, executor)
    try:
        job = await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key=mode)
        finished = await manager.wait(job.job_id, owner="alice")
    finally:
        await manager.close()
    assert finished.status == "completed"
    report = json.loads(finished.result["json"])
    if expected is None:
        assert len(report["uncertain_high_impact_candidates"]) == 1
        assert not report["coverage"]["failed"]
        assert behavior.phase_counts["synthesizer_verifier:verification"] == 1
        context = json.loads(planner_calls[0]["messages"][1]["content"])["selected_context"]
        assert context["repository_metadata"]["file_count"] == 2
    else:
        assert not report["uncertain_high_impact_candidates"]
        assert report["coverage"]["failed"]["__planner"] == expected
        assert "logic_correctness:investigation" not in behavior.phase_counts
    assert not finished.ledger.inflight
    assert finished.ledger.agent_usage[AgentId.PLANNER].total_tokens <= 25000
    assert all(client.is_closed for client in transports)
    assert all(body["response_format"] == {"type": "json_object"} for body in planner_calls)
    assert len(planner_calls) == (1 if mode in {"normal", "quota", "authentication", "refusal"} else 2)
    timeline = events.replay(job.job_id, limit=1000)
    assert "private rejection" not in json.dumps([event.model_dump(mode="json") for event in timeline])
