"""Distinguish omitted thinking counters from an explicitly reported zero."""
import asyncio

import httpx
import pytest

from devwatch.providers.base import LLMRequest
from devwatch.providers.openai_adapter import OpenAIProviderAdapter


@pytest.mark.parametrize('details,expected', [(None, None), ({}, None),
    ({'reasoning_tokens': None}, None), ({'reasoning_tokens': 0}, 0), ({'reasoning_tokens': 7}, 7)])
def test_sdk_reasoning_usage_retains_availability_without_inventing_zero(monkeypatch, details, expected):
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-test-key')
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    usage = dict(prompt_tokens=10, completion_tokens=8, total_tokens=18)
    if details is not None:
        usage['completion_tokens_details'] = details
    def respond(request):
        return httpx.Response(200, json=dict(id='usage-fixture', object='chat.completion', created=1,
            model='fixture', choices=[dict(index=0, message=dict(role='assistant', content='{}'), finish_reason='stop')],
            usage=usage))
    async def run():
        transport = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        adapter = OpenAIProviderAdapter(provider_name='openai', request_delay=0)
        monkeypatch.setattr(adapter, '_get_httpx_async_client', lambda: transport)
        result = await adapter.generate_completion(LLMRequest(prompt='synthetic fixture', model='fixture'))
        assert result.usage.reasoning_tokens == expected
        assert result.usage.total_tokens == 18
        assert transport.is_closed
    asyncio.run(run())
