"""Provider compatibility is exercised through the installed SDK and HTTP boundary."""

import json

import httpx
import pytest

from devwatch.providers.base import LLMRequest
from devwatch.providers.openai_adapter import OpenAIProviderAdapter


@pytest.mark.asyncio
async def test_gemini_planning_json_mode_and_reasoning_usage_survive_sdk(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-only")
    requests = []
    def reply(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "fixture", "object": "chat.completion",
            "created": 1, "model": "fixture-model", "choices": [{"index": 0,
                "message": {"role": "assistant", "content": '{"kind":"finish"}'},
                "finish_reason": "stop"}], "usage": {"prompt_tokens": 10,
                    "completion_tokens": 20, "total_tokens": 30,
                    "completion_tokens_details": {"reasoning_tokens": 12}}})
    transport = httpx.AsyncClient(transport=httpx.MockTransport(reply))
    adapter = OpenAIProviderAdapter(provider_name="gemini", request_delay=0)
    monkeypatch.setattr(adapter, "_get_httpx_async_client", lambda: transport)
    request = LLMRequest(prompt="Return one JSON action", model="fixture-model", max_tokens=8192,
                         json_mode=True, reasoning_effort="low")
    response = await adapter.generate_completion(request)
    assert requests[0]["response_format"] == {"type": "json_object"}
    assert requests[0]["reasoning_effort"] == "low"
    assert requests[0]["max_tokens"] == 8192
    assert "temperature" not in requests[0]
    assert response.usage.reasoning_tokens == 12
    assert response.usage.total_tokens == 30
    assert transport.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", ["stop", "length", "content_filter", None])
async def test_sdk_preserves_incomplete_and_refusal_metadata_without_inventing_stop(monkeypatch, finish):
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-only")
    def reply(request):
        return httpx.Response(200, json={"id": "fixture", "object": "chat.completion",
            "created": 1, "model": "fixture-model", "choices": [{"index": 0,
                "message": {"role": "assistant", "content": "", "refusal": "private refusal text"},
                "finish_reason": finish}], "usage": {"prompt_tokens": 10,
                    "completion_tokens": 1, "total_tokens": 11}})
    transport = httpx.AsyncClient(transport=httpx.MockTransport(reply))
    adapter = OpenAIProviderAdapter(provider_name="gemini", request_delay=0)
    monkeypatch.setattr(adapter, "_get_httpx_async_client", lambda: transport)
    response = await adapter.generate_completion(LLMRequest(prompt="fixture", model="fixture-model"))
    assert response.finish_reason == (finish or "unknown")
    assert response.refusal is True
    assert "private refusal" not in response.model_dump_json()
    assert transport.is_closed


def test_unrelated_provider_requests_keep_existing_options():
    adapter = OpenAIProviderAdapter(provider_name="openai", request_delay=0)
    options = adapter._completion_options(LLMRequest(prompt="fixture", model="fixture-model"))
    assert "response_format" not in options
    assert "reasoning_effort" not in options
    assert options["temperature"] == .2
