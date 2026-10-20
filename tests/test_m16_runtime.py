"""Actual SDK serialization, durable graph and acceptance with synthetic responses."""
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
@pytest.mark.parametrize('mode', ['repair', 'partial_siblings', 'no_progress'])
async def test_sdk_investigation_repair_and_stops_reach_honest_accepted_reports(tmp_path, monkeypatch, mode):
    monkeypatch.setenv('GEMINI_API_KEY', 'fixture-only')
    provider, prompts, clients = ReviewProvider(), [], []

    async def reply(request):
        body = json.loads(request.content)
        prompt = json.loads(body['messages'][1]['content'])
        prompts.append(prompt)
        response = await provider.generate_completion(LLMRequest(model=body['model'], prompt=json.dumps(prompt)))
        action = json.loads(response.content)
        if prompt['task']['agent_id'] == 'logic_correctness' and action['kind'] == 'submit_candidates':
            if mode == 'repair' and not prompt.get('repair'):
                action['inspected_evidence'] = []
            elif mode == 'partial_siblings':
                candidate = action['payload']['candidates'][0]
                action['payload']['candidates'].append({**candidate, 'title': 'Unsupported sibling', 'evidence_refs': ['missing']})
            elif mode == 'no_progress':
                action = dict(kind='call_tool', tool='read_source', arguments={'file_path': 'service.py'},
                              inspected_evidence=action['inspected_evidence'])
        assert sum(len(message['content'].encode()) for message in body['messages']) + body['max_tokens'] + 512 <= 20000
        return httpx.Response(200, json=dict(id='m16-fixture', object='chat.completion', created=1, model=body['model'],
            choices=[dict(index=0, finish_reason='stop', message=dict(role='assistant', content=json.dumps(action)))],
            usage=dict(prompt_tokens=10, completion_tokens=5, total_tokens=15)))

    def transport():
        client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
        clients.append(client)
        return client

    adapter = OpenAIProviderAdapter(provider_name='gemini', request_delay=0)
    monkeypatch.setattr(adapter, '_get_httpx_async_client', transport)
    layout, artifacts, snapshot, jobs, events = stores(tmp_path)
    executor = CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events,
        adapter, models={tier: 'fixture-model' for tier in ModelTier})
    manager = DurableJobManager(jobs, events, executor)
    try:
        job = await manager.submit(owner='alice', request={'snapshot_id': snapshot.snapshot_id},
            idempotency_key='m16-' + mode, limits=BalancedLimits(model_context_tokens=20000))
        done = await manager.wait(job.job_id, owner='alice')
    finally:
        await manager.close()
    assert done.status == 'completed' and not done.ledger.inflight
    report = json.loads(done.result['json'])
    specialist = [prompt for prompt in prompts if prompt['task']['agent_id'] == 'logic_correctness']
    assert specialist[0]['investigation']['remaining_files'] == ['service.py']
    assert report['coverage']['inspected_files'] == ['service.py']
    # Publication preserves the existing quarantine coverage classification.
    failures = {} if mode == 'repair' else {'logic-1': 'invalid_evidence' if mode == 'partial_siblings' else 'no_progress'}
    assert report['coverage']['failed'] == failures
    findings = report['uncertain_high_impact_candidates']
    assert [finding['title'] for finding in findings] == ([] if mode == 'no_progress' else ['Empty input raises'])
    assert len(specialist) == (2 if mode == 'no_progress' else 3)
    assert done.ledger.task_tools['logic-1'] == 1
    jobs.dispatch_events(events)
    stream = events.replay(job.job_id)
    assert sum(event.kind == 'candidate_rejected' for event in stream) == int(mode == 'partial_siblings')
    stopped = [event.payload.stop_reason for event in stream if event.kind == 'agent_completed'
               and event.payload.task_id == 'logic-1']
    assert stopped == [{'repair': 'evidence_complete', 'partial_siblings': 'evidence_incomplete', 'no_progress': 'no_progress'}[mode]]
    assert any(event.kind == 'evidence_inspected' for event in stream)
    assert all('Unsupported sibling' not in event.model_dump_json() for event in stream)
    assert all(client.is_closed for client in clients)
