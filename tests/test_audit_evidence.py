import asyncio
import json

import pytest

from devwatch.review.budgets import BudgetManager
from devwatch.review.contracts import AgentAction, AgentId, AgentPrivateState, ModelTier
from devwatch.review.subgraphs import AgentSubgraphs
from tests.test_iterative_agents import ScriptedProvider
from tests.test_repository_context import setup_repository


def engine(repo, responses):
    provider = ScriptedProvider(responses)
    return AgentSubgraphs(provider, repo.tools(), BudgetManager(), repo.context,
                          models={t:t.value for t in ModelTier}), provider


def test_large_evidence_can_be_reassembled_with_bounded_scoped_pages(tmp_path):
    _, _, _, repo, task = setup_repository(tmp_path)
    observed = repo._record({'tool': 'parse_ast', 'file_path': 'service.py', 'data': '界x' * 15000})
    assert len(json.dumps(repo.evidence(observed.evidence_ref)).encode()) > repo.CONTEXT_BYTES
    private = AgentPrivateState(evidence_refs=[observed.evidence_ref])
    selected = repo.context({'task':task, 'private_state':private})
    assert selected['evidence'], 'successful large results must not disappear'
    assert len(json.dumps(selected, ensure_ascii=False).encode()) <= repo.CONTEXT_BYTES
    async def run():
        cursor, parts = 0, []
        while True:
            observation = await repo.tools().execute(task, AgentAction(kind='call_tool', tool='read_evidence',
                arguments={'evidence_ref':observed.evidence_ref, 'offset':cursor, 'max_chars':800}))
            private.evidence_cursors[observed.evidence_ref] = observation.offset
            page = repo.context({'task':task, 'private_state':private})['evidence'][0]
            assert len(json.dumps(page, ensure_ascii=False).encode()) <= 3000
            assert page['offset'] == cursor
            parts.append(page['excerpt'])
            if page['next_offset'] is None:
                break
            assert page['next_offset'] > cursor
            cursor = page['next_offset']
        restored = json.loads(''.join(parts))
        assert restored['data'] == '界x' * 15000
    asyncio.run(run())


def test_processing_is_separate_from_delivery_and_acknowledged_inspection(tmp_path):
    _, _, _, repo, task = setup_repository(tmp_path)
    runtime, _ = engine(repo, [
        {'kind':'call_tool','tool':'read_source','arguments':{'file_path':'service.py'}},
        {'kind':'finish'},
    ])
    state = asyncio.run(runtime.run_specialist(task))
    ref = state['private_state'].evidence_refs[0]
    receipt = state['private_state'].evidence_progress[ref]
    assert receipt.processed
    assert receipt.delivered and not receipt.inspected
    private = state['private_state'].model_copy(deep=True)
    runtime, _ = engine(repo, [{'kind':'finish', 'inspected_evidence':[ref]}])
    state = asyncio.run(runtime.run_specialist(task, private_state=private))
    assert state['private_state'].evidence_progress[ref].inspected
    assert state['output'].coverage.inspected_files == ['service.py']


def candidate(repo, ref):
    return dict(category='logic', title='Empty list crashes', description='Index access raises', impact='Failure', confidence=.9,
        evidence_refs=[ref], location=dict(snapshot_id=repo.snapshot_id, file_path='service.py', start_line=2, end_line=2))


@pytest.mark.parametrize('inspect_evidence', [False, True])
def test_confirmation_requires_delivered_acknowledged_evidence(tmp_path, inspect_evidence):
    _, _, _, repo, task = setup_repository(tmp_path)
    ref = repo._read_source({'file_path':'service.py'}, task).evidence_ref
    action = dict(kind='submit_verification', payload=dict(decisions=[dict(finding_id='f1', verdict='confirmed',
        confidence=.9, rationale='Index access raises on empty input', evidence_refs=[ref])]))
    if inspect_evidence:
        action['inspected_evidence'] = [ref]
    runtime, _ = engine(repo, [action, {'kind':'finish'}] if inspect_evidence else [action, action])
    state = asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id, files=task.files, candidates={'f1':candidate(repo,ref)}))
    assert (state['verification'] is not None) == inspect_evidence
    if inspect_evidence:
        assert state['verification'].decisions[0].verdict == 'confirmed'
    else:
        assert state['private_state'].stop_reason == 'invalid_schema'


def test_verifier_can_cite_its_own_scoped_evidence_with_provenance(tmp_path):
    _, _, _, repo, task = setup_repository(tmp_path)
    ref = repo._read_source({'file_path':'service.py'}, task).evidence_ref
    from tests.test_iterative_agents import ScriptedProvider
    class Provider(ScriptedProvider):
        async def generate_completion(self, request):
            data = json.loads(request.prompt)
            if not data['private_state']['evidence_refs']:
                self.responses = iter([dict(kind='call_tool',tool='read_source',arguments={'file_path':'service.py','start_line':2,'end_line':2})])
            else:
                own = data['private_state']['evidence_refs'][0]
                self.responses = iter([dict(kind='submit_verification', inspected_evidence=[own], payload=dict(decisions=[
                    dict(finding_id='f1',verdict='confirmed',confidence=.9,rationale='Checked source',evidence_refs=[own])]))
                    if data['phase']=='verification' else dict(kind='finish')])
            return await super().generate_completion(request)
    provider = Provider([])
    runtime = AgentSubgraphs(provider,repo.tools(),BudgetManager(),repo.context,models={t:t.value for t in ModelTier})
    state = asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id,files=task.files,candidates={'f1':candidate(repo,ref)}))
    own = state['verification'].decisions[0].evidence_refs[0]
    assert own != ref
    assert repo.evidence(own)['provenance'] == {'agent_id':'synthesizer_verifier','task_id':'__final'}


def test_long_single_line_source_is_stored_and_paged_instead_of_becoming_inaccessible(tmp_path):
    from devwatch.review.repository import RepositoryContext
    from devwatch.review.stores import ArtifactStore,RepoCache
    artifacts=ArtifactStore(tmp_path/'artifacts')
    snapshot=artifacts.capture(owner='alice',files={'service.py':'message = '+repr('x'*30000)+'\n'})
    repo=RepositoryContext(artifacts,RepoCache(tmp_path/'cache'),snapshot.snapshot_id,owner='alice')
    from tests.test_iterative_agents import task
    observed=repo._read_source({'file_path':'service.py'},task())
    page=repo.evidence_page(observed.evidence_ref,task())
    assert page['next_offset'] is not None
    assert len(page['excerpt'].encode())<3000


def test_unseen_or_unrelated_evidence_cannot_confirm_a_candidate(tmp_path):
    _,_,_,repo,task=setup_repository(tmp_path)
    ref=repo._read_source({'file_path':'service.py'},task).evidence_ref
    forged='evidence-'+'0'*64
    action=dict(kind='submit_verification',inspected_evidence=[forged],payload={'decisions':[
        dict(finding_id='f1',verdict='confirmed',confidence=.9,rationale='Claim',evidence_refs=[forged])]})
    runtime,_=engine(repo,[action,action])
    state=asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id,files=task.files,candidates={'f1':candidate(repo,ref)}))
    assert state['verification'] is None
    assert state['private_state'].stop_reason=='invalid_schema'


def test_explicit_retrieval_prioritizes_an_older_artifact_when_context_is_full(tmp_path):
    _,_,_,repo,task=setup_repository(tmp_path)
    refs=[repo._record({'tool':'parse_ast','file_path':'service.py','data':str(i)+'x'*15000}).evidence_ref for i in range(4)]
    private=AgentPrivateState(evidence_refs=refs)
    runtime,provider=engine(repo,[dict(kind='call_tool',tool='read_evidence',arguments={'evidence_ref':refs[0],'offset':5000}),dict(kind='finish')])
    state=asyncio.run(runtime.run_specialist(task,private_state=private))
    delivered=json.loads(provider.requests[1].prompt)['selected_context']['evidence']
    assert delivered[0]['evidence_ref']==refs[0]
    assert delivered[0]['offset']==5000
    assert state['private_state'].evidence_progress[refs[0]].delivered
