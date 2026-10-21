"""Metadata records actual completed and unknown work without double charging subsets."""
import asyncio
import json

import httpx
import pytest

from devwatch.providers.base import LLMRequest, LLMUsage
from devwatch.providers.openai_adapter import OpenAIProviderAdapter
from tests.test_audit_evidence import engine
from tests.test_m20_verification import setup
from tests.verification_fixtures import decision


@pytest.mark.parametrize('cached', [6, None])
def test_real_sdk_reports_cached_input_and_reasoning_subsets(monkeypatch, cached):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-only-key')
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    def reply(request):
        return httpx.Response(200, json=dict(id='fixture', object='chat.completion', created=1, model='fixture',
            choices=[dict(index=0, message=dict(role='assistant', content='{}'), finish_reason='stop')],
            usage=dict(prompt_tokens=20, completion_tokens=10, total_tokens=30,
                completion_tokens_details=dict(reasoning_tokens=4),
                **({'prompt_tokens_details':dict(cached_tokens=cached)} if cached is not None else {}))))
    async def scenario():
        transport = httpx.AsyncClient(transport=httpx.MockTransport(reply))
        adapter = OpenAIProviderAdapter(provider_name='openai', request_delay=0)
        monkeypatch.setattr(adapter, '_get_httpx_async_client', lambda: transport)
        response = await adapter.generate_completion(LLMRequest(model='fixture', prompt='synthetic'))
        assert response.usage.cached_prompt_tokens == cached
        assert response.usage.reasoning_tokens == 4
        assert response.usage.total_tokens == 30
        assert transport.is_closed
    asyncio.run(scenario())


def test_every_successful_call_records_sizes_and_subsets_without_extra_charge(tmp_path):
    repo, task, ref, claim = setup(tmp_path)
    runtime, provider = engine(repo, [dict(kind='submit_verification', inspected_evidence=[ref],
        payload=dict(decisions=[decision(claim,[ref])]))])
    generate = provider.generate_completion
    async def complete(request):
        response = await generate(request)
        return response.model_copy(update={'usage': LLMUsage(prompt_tokens=20, completion_tokens=10,
            total_tokens=30, reasoning_tokens=4, cached_prompt_tokens=6)})
    provider.generate_completion = complete
    state = asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id, files=task.files, candidates={'f1':claim}))
    assert state['private_state'].stop_reason == 'evidence_complete'
    assert runtime.budget.ledger.total_tokens == 30
    record, = state['provider_observations']
    assert record['reported_cached_prompt_tokens'] == 6
    assert record['reported_reasoning_tokens'] == 4
    assert record['charged_tokens'] == 30
    assert record['status'] == 'returned'
    assert record['prompt_utf8_bytes'] > record['source_page_utf8_bytes'] > 0
    assert record['duration_seconds'] >= 0


def test_unknown_call_retains_its_reservation_and_persisted_metadata(tmp_path):
    repo, task, ref, claim = setup(tmp_path)
    runtime, provider = engine(repo, [])
    async def unknown(request):
        raise TimeoutError('synthetic timeout')
    provider.generate_completion = unknown
    saved = []
    async def persist(state, ledger):
        from devwatch.review.workflow import _serializable
        saved.append((_serializable(state), ledger))
    runtime.persist = persist
    state = asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id, files=task.files, candidates={'f1':claim}))
    assert state['output'] is None
    record, = state['provider_observations']
    assert record['status'] == 'unknown'
    assert record['charged_tokens'] == record['reserved_tokens'] > 0
    assert record['charged_tokens'] == runtime.budget.ledger.total_tokens
    assert saved[-1][0]['provider_observations'][0]['status'] == 'unknown'
    before_dispatch = next(snapshot for snapshot, ledger in saved if ledger['inflight'])
    assert before_dispatch['provider_observations'][0]['status'] == 'reserved'
    assert 'synthetic timeout' not in json.dumps(record)
