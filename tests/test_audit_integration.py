"""Script only the model; exercise the canonical graph, artifacts and job stores."""
import asyncio
from hashlib import sha256
import json

from devwatch.review.contracts import AGENT_CONTRACTS, AgentPrivateState, ModelTier
from devwatch.review.jobs import DurableJobManager
from devwatch.review.stores import RepoCache
from devwatch.review.workflow import CanonicalReviewExecutor
from tests.test_canonical_workflow import ReviewProvider, stores


def test_large_evidence_pipeline_through_inspected_verifier_evidence_and_accepted_report(tmp_path):
    class Provider(ReviewProvider):
        def __init__(self):
            super().__init__()
            self.steps={}
        async def generate_completion(self,request):
            state=json.loads(request.prompt)
            role,phase=state['task']['agent_id'],state['phase']
            if role=='planner':
                return await super().generate_completion(request)
            self.requests.append(request)
            step=self.steps.get(role,0)
            self.steps[role]=step+1
            private,context=state['private_state'],state['selected_context']
            pages=context['evidence']
            if role=='logic_correctness':
                if step==0:
                    action=dict(kind='call_tool',tool='parse_ast',arguments={'file_path':'service.py'})
                elif step==1:
                    ast=private['evidence_refs'][0]
                    assert pages[0]['next_offset'] is not None
                    action=dict(kind='call_tool',tool='read_evidence',arguments={'evidence_ref':ast,'offset':12000,'max_chars':1000})
                elif step==2:
                    assert any(page['offset']==12000 for page in pages)
                    action=dict(kind='call_tool',tool='read_source',arguments={'file_path':'service.py','start_line':1,'end_line':2})
                else:
                    action=dict(kind='submit_candidates',payload=dict(task_id='logic-1',agent_id=role,coverage={},stop_reason='evidence_complete',candidates=[
                        dict(category='logic',title='Empty input raises',description='Indexing empty input raises IndexError',impact='Request fails',confidence=.9,
                             evidence_refs=private['evidence_refs'],location=dict(snapshot_id=context['snapshot_id'],file_path='service.py',start_line=2,end_line=2))]))
            elif phase=='verification':
                if step==0:
                    ast=next(page['evidence_ref'] for page in pages if page['next_offset'] is not None)
                    action=dict(kind='call_tool',tool='read_evidence',arguments={'evidence_ref':ast,'offset':12000})
                elif step==1:
                    action=dict(kind='call_tool',tool='read_source',arguments={'file_path':'service.py','start_line':2,'end_line':2})
                else:
                    own=private['evidence_refs'][-1]
                    action=dict(kind='submit_verification',payload={'decisions':[
                        dict(finding_id=identity,verdict='confirmed',confidence=.9,rationale='Scoped source inspection establishes the boundary failure',
                             evidence_refs=[own]) for identity in state['candidates']]})
            else:
                action=dict(kind='submit_synthesis',payload={'summary':'One evidence-backed defect','limitations':[]})
            action['inspected_evidence']=[page['evidence_ref'] for page in pages]
            from devwatch.providers.base import LLMResponse,LLMUsage
            return LLMResponse(finish_reason="stop", content=json.dumps(action),provider='scripted',model=request.model,latency_ms=0,
                               usage=LLMUsage(prompt_tokens=10,completion_tokens=5,total_tokens=15))
    async def run():
        layout,artifacts,_,jobs,events=stores(tmp_path)
        snapshot=artifacts.capture(owner='alice',files={'service.py':'\n'.join(f'def first_{i}(items):\n    return items[0]\n' for i in range(400))})
        provider=Provider()
        executor=CanonicalReviewExecutor(layout,artifacts,RepoCache(layout.repo_cache),jobs,events,provider,models={t:t.value for t in ModelTier})
        manager=DurableJobManager(jobs,events,executor)
        job=await manager.submit(owner='alice',request={'snapshot_id':snapshot.snapshot_id},idempotency_key='large-pipeline')
        done=await manager.wait(job.job_id,owner='alice')
        await manager.close()
        assert done.status=='completed'
        report=json.loads(done.result['json'])
        assert len(report['confirmed_defects'])==1
        thread=sha256(('alice\0'+job.job_id).encode()).hexdigest()
        specialist=AgentPrivateState.model_validate(executor.checkpoints.load(thread,'logic-1')['state']['private_state'])
        ast=specialist.evidence_refs[0]
        assert specialist.evidence_progress[ast].processed
        assert (12000,13000) in specialist.evidence_progress[ast].delivered
        assert (12000,13000) in specialist.evidence_progress[ast].inspected
        verifier=AgentPrivateState.model_validate(executor.checkpoints.load(thread,'__final')['state']['private_state'])
        own=report['confirmed_defects'][0]['evidence_refs'][0]
        assert verifier.evidence_progress[own].fully_inspected()
        assert verifier.evidence_progress[own].provenance['agent_id']=='synthesizer_verifier'
        assert specialist.evidence_progress[ast].provenance['agent_id']=='logic_correctness'
        assert done.ledger.total_tokens==15*len(provider.requests)
        assert len(AGENT_CONTRACTS)==7
        assert all('items[0]' not in event.model_dump_json() for event in events.replay(job.job_id))
        assert {event.kind for event in events.replay(job.job_id)} >= {
            'tool_result', 'evidence_delivered', 'evidence_inspected', 'validation_passed'}
    asyncio.run(run())
