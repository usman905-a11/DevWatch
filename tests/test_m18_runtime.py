"""SDK-to-report behavior with progressive policies and provider metadata intact."""
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
async def test_sdk_phase_guidance_preserves_accepted_report_and_private_metadata(tmp_path,monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','fixture-only')
    provider,prompts,clients=ReviewProvider(),[],[]
    async def reply(request):
        body=json.loads(request.content)
        prompt=json.loads(body['messages'][1]['content'])
        prompts.append(prompt)
        assert body['reasoning_effort']=='low' and body['response_format']=={'type':'json_object'}
        assert sum(len(message['content'].encode()) for message in body['messages'])+body['max_tokens']+512<=20000
        assert prompt['prompt_revision']['skills']==list(prompt['policy_skills'])
        response=await provider.generate_completion(LLMRequest(model=body['model'],prompt=json.dumps(prompt)))
        return httpx.Response(200,json=dict(id='m18-fixture',object='chat.completion',created=1,model=body['model'],
            choices=[dict(index=0,finish_reason='stop',message=dict(role='assistant',content=response.content))],
            usage=dict(prompt_tokens=10,completion_tokens=8,total_tokens=18,completion_tokens_details={'reasoning_tokens':3})))
    def transport():
        client=httpx.AsyncClient(transport=httpx.MockTransport(reply))
        clients.append(client)
        return client
    adapter=OpenAIProviderAdapter(provider_name='gemini',request_delay=0)
    monkeypatch.setattr(adapter,'_get_httpx_async_client',transport)
    layout,artifacts,snapshot,jobs,events=stores(tmp_path)
    executor=CanonicalReviewExecutor(layout,artifacts,RepoCache(layout.repo_cache),jobs,events,
        adapter,models={tier:'fixture-model' for tier in ModelTier})
    manager=DurableJobManager(jobs,events,executor)
    try:
        job=await manager.submit(owner='alice',request={'snapshot_id':snapshot.snapshot_id},
            idempotency_key='m18-versioned',limits=BalancedLimits(model_context_tokens=20000))
        done=await manager.wait(job.job_id,owner='alice')
    finally:
        await manager.close()
    report=json.loads(done.result['json'])
    assert done.status=='completed' and not done.ledger.inflight
    assert not report['coverage']['failed'] and report['coverage']['inspected_files']==['service.py']
    assert len(report['uncertain_high_impact_candidates'])==1
    assert list(prompts[-1]['policy_skills'])==['verification']
    assert len(prompts)==4 and done.ledger.total_tokens==72
    assert 'policy_sha256' not in done.result['json']
    from contextlib import closing
    import sqlite3
    with closing(sqlite3.connect(layout.checkpoints)) as db:
        states=[json.loads(row[0]) for row in db.execute('SELECT state FROM agent_progress')]
    observations=[item for state in states for item in state['provider_observations']]
    assert len(observations)==4
    assert all(item['reported_reasoning_tokens']==3 and item['reported_total_tokens']==18
        and item['finish_reason']=='stop' and item['prompt_revision']['version'] for item in observations)
    jobs.dispatch_events(events)
    assert all('policy_sha256' not in event.model_dump_json() for event in events.replay(job.job_id))
    assert all(client.is_closed for client in clients)
