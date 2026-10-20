"""Actual SDK serialization and accepted reports retain stage-relevant tools."""
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
async def test_filtered_catalogues_cross_sdk_and_keep_source_backed_report(tmp_path, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','fixture-only')
    provider,prompts,clients=ReviewProvider(),[],[]
    async def reply(request):
        body=json.loads(request.content)
        prompt=json.loads(body['messages'][1]['content'])
        prompts.append(prompt)
        names={tool['name'] for tool in prompt['tool_catalogue']}
        assert set(prompt['action_schema']['properties']['tool']['enum'])=={None,*names}
        assert not {'run_tests','lint','type_check','benchmark','write_artifact','db_analyze','query_analyze'} & names
        assert 'tool_selections' not in prompt
        if prompt['phase']=='synthesis':
            assert not names
            assert 'call_tool' not in prompt['action_schema']['properties']['kind']['enum']
        elif prompt['phase']=='verification' and prompt['selected_context'].get('evidence'):
            assert 'read_evidence' in names
        elif prompt['task']['agent_id']=='logic_correctness':
            if prompt['selected_context'].get('evidence'):
                assert 'parse_ast' in names
            else:
                assert names=={'read_source'}
        assert sum(len(message['content'].encode()) for message in body['messages'])+body['max_tokens']+512<=20000
        response=await provider.generate_completion(LLMRequest(model=body['model'],prompt=json.dumps(prompt)))
        return httpx.Response(200,json=dict(id='m17-fixture',object='chat.completion',created=1,model=body['model'],
            choices=[dict(index=0,finish_reason='stop',message=dict(role='assistant',content=response.content))],
            usage=dict(prompt_tokens=10,completion_tokens=5,total_tokens=15)))
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
            idempotency_key='m17-filtered',limits=BalancedLimits(model_context_tokens=20000))
        done=await manager.wait(job.job_id,owner='alice')
    finally:
        await manager.close()
    report=json.loads(done.result['json'])
    assert done.status=='completed' and not done.ledger.inflight
    assert report['coverage']['inspected_files']==['service.py']
    assert not report['coverage']['failed']
    assert len(report['uncertain_high_impact_candidates'])==1
    assert len(prompts)==5 and all(client.is_closed for client in clients)
