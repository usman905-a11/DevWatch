"""Actual SDK serialization/transport and cleanup; network is replaced at HTTP boundary."""
import asyncio
import json
import httpx
import pytest

from devwatch.providers.base import LLMRequest
from devwatch.providers.openai_adapter import OpenAIProviderAdapter


def test_real_sdk_uses_unwrapped_transport_and_closes_it(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    import sys
    from types import ModuleType
    import langsmith
    wrappers = ModuleType("langsmith.wrappers")
    wrappers.wrap_openai = lambda *args, **kwargs: pytest.fail("raw provider tracing is forbidden")
    monkeypatch.setitem(sys.modules, "langsmith.wrappers", wrappers)
    monkeypatch.setattr(langsmith, "wrappers", wrappers, raising=False)
    requests = []
    def reply(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 1, "model": "test-model",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "{}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 2, "total_tokens": 14}})
    async def scenario():
        transport = httpx.AsyncClient(transport=httpx.MockTransport(reply))
        adapter = OpenAIProviderAdapter(provider_name="openai", request_delay=0)
        monkeypatch.setattr(adapter, "_get_httpx_async_client", lambda: transport)
        result = await adapter.generate_completion(LLMRequest(prompt="private source", model="test-model"))
        assert result.usage.total_tokens == 14
        assert transport.is_closed
    asyncio.run(scenario())
    assert len(requests) == 1
    assert requests[0]["model"] == "test-model"


def test_cancelled_provider_delay_releases_transport_without_dispatch(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    async def scenario():
        transport = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: pytest.fail("Provider call was dispatched")))
        adapter = OpenAIProviderAdapter(provider_name="openai", request_delay=60)
        entered = asyncio.Event()
        def configured():
            entered.set()
            return transport
        monkeypatch.setattr(adapter, "_get_httpx_async_client", configured)
        task = asyncio.create_task(adapter.generate_completion(LLMRequest(prompt="fixture", model="test-model")))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert transport.is_closed
    asyncio.run(scenario())


@pytest.mark.parametrize('finish_reason',['stop','length','content_filter',None])
def test_sdk_preserves_finish_reason_and_usage_even_for_empty_truncated_output(monkeypatch,finish_reason):
    monkeypatch.setenv('OPENAI_API_KEY','test-only-key')
    monkeypatch.delenv('OPENROUTER_API_KEY',raising=False)
    def reply(request):
        return httpx.Response(200,json={'id':'finish-test','object':'chat.completion','created':1,'model':'test-model',
            'choices':[{'index':0,'message':{'role':'assistant','content':''},'finish_reason':finish_reason}],
            'usage':{'prompt_tokens':12,'completion_tokens':2,'total_tokens':14}})
    async def run():
        transport=httpx.AsyncClient(transport=httpx.MockTransport(reply))
        adapter=OpenAIProviderAdapter(provider_name='openai',request_delay=0)
        monkeypatch.setattr(adapter,'_get_httpx_async_client',lambda:transport)
        result=await adapter.generate_completion(LLMRequest(prompt='fixture',model='test-model'))
        assert result.finish_reason==(finish_reason or 'unknown')
        assert result.usage.total_tokens==14
        assert transport.is_closed
    asyncio.run(run())


@pytest.mark.parametrize("status,exception", [(401, "ProviderAuthenticationError"), (403, "ProviderAuthorizationError"),
    (429, "ProviderRateLimitError"), (500, "ProviderTemporaryError")])
def test_sdk_failure_has_no_internal_retries_and_releases_transport(monkeypatch, status, exception):
    from devwatch.providers import exceptions
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    calls = []
    def reply(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"message": "test rejection", "type": "test", "code": "test"}})
    async def scenario():
        transport = httpx.AsyncClient(transport=httpx.MockTransport(reply))
        adapter = OpenAIProviderAdapter(provider_name="openai", request_delay=0)
        monkeypatch.setattr(adapter, "_get_httpx_async_client", lambda: transport)
        with pytest.raises(getattr(exceptions, exception)):
            await adapter.generate_completion(LLMRequest(prompt="private source", model="test-model"))
        assert transport.is_closed
    asyncio.run(scenario())
    assert len(calls) == 1
