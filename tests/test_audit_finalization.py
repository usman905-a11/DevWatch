import asyncio
import json

import pytest

from devwatch.review.contracts import Coverage, FindingCandidate, ReportDraft, ReportFinding, VerificationDecision
from devwatch.review.finalization import AcceptanceError, FinalAcceptanceGate
from tests.test_audit_evidence import engine, candidate
from tests.test_repository_context import setup_repository
from tests.verification_fixtures import reviewed


def payload(repo, ref):
    claim = candidate(repo,ref)
    decision = dict(finding_id='f1',verdict='confirmed',confidence=.9,rationale='Source inspected',evidence_refs=[ref],
                    causal_review=reviewed(claim, [ref]))
    finding = dict(**claim,finding_id='f1',verification_rationale='Source inspected')
    return dict(decisions=[decision],report_draft=dict(snapshot_id=repo.snapshot_id,summary='Review',coverage={},confirmed_defects=[finding]),coverage_summary={})


@pytest.mark.parametrize('damage',['missing','wrong_id','immutable','rationale','decision'])
def test_legacy_synthesis_still_cannot_alter_recorded_verification(tmp_path,damage):
    _, _, _, repo, task = setup_repository(tmp_path)
    ref = repo._read_source({'file_path':'service.py'},task).evidence_ref
    good = payload(repo,ref)
    bad = json.loads(json.dumps(good))
    if damage=='missing': bad['report_draft']['confirmed_defects']=[]
    if damage=='wrong_id': bad['report_draft']['confirmed_defects'][0]['finding_id']='invented'
    if damage=='immutable': bad['report_draft']['confirmed_defects'][0]['description']='Changed claim'
    if damage=='rationale': bad['report_draft']['confirmed_defects'][0]['verification_rationale']='Changed rationale'
    if damage=='decision': bad['decisions'][0]['verdict']='rejected'
    runtime, provider = engine(repo,[
        dict(kind='submit_verification', inspected_evidence=[ref],payload={'decisions':good['decisions']}),
        dict(kind='submit_synthesis',payload=bad),dict(kind='submit_synthesis',payload=good)])
    state = asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id,files=task.files,candidates={'f1':candidate(repo,ref)}))
    assert state['output'] is not None
    assert len(provider.requests)==1
    with pytest.raises(ValueError):
        runtime._parse_action(json.dumps(dict(kind='submit_synthesis', payload=bad)), state)
    assert runtime._parse_action(json.dumps(dict(kind='submit_synthesis', payload=good)), state).kind == 'submit_synthesis'


def test_compact_synthesis_assembles_verified_fields_deterministically(tmp_path):
    _, _, _, repo, task = setup_repository(tmp_path)
    ref = repo._read_source({'file_path':'service.py'},task).evidence_ref
    good = payload(repo,ref)
    runtime,_ = engine(repo,[dict(kind='submit_verification',inspected_evidence=[ref],payload={'decisions':good['decisions']}),
        dict(kind='submit_synthesis',payload={'summary':'Reviewed source','limitations':[]})])
    state=asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id,files=task.files,candidates={'f1':candidate(repo,ref)}))
    assert state['output'].report_draft.confirmed_defects[0].model_dump()==good['report_draft']['confirmed_defects'][0] | {'kind':'defect','remediation':'','arithmetic_claims':[]}


def test_verifier_may_raise_confidence_after_inspecting_new_evidence(tmp_path):
    _,_,_,repo,task=setup_repository(tmp_path)
    ref=repo._read_source({'file_path':'service.py'},task).evidence_ref
    good=payload(repo,ref)
    claim={**candidate(repo,ref),'confidence':.6}
    good['decisions'][0]['causal_review']=reviewed(claim,[ref])
    runtime,_=engine(repo,[dict(kind='submit_verification',inspected_evidence=[ref],payload={'decisions':good['decisions']}),
        dict(kind='submit_synthesis',payload={'summary':'Verified','limitations':[]})])
    state=asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id,files=task.files,candidates={'f1':claim}))
    assert state['output'].report_draft.confirmed_defects[0].confidence==.9


def test_acceptance_requires_verifier_inspection_and_allows_verifier_evidence(tmp_path):
    _, _, _, repo, task=setup_repository(tmp_path)
    ref=repo._read_source({'file_path':'service.py'},task).evidence_ref
    own=repo._read_source({'file_path':'service.py','start_line':2,'end_line':2},task).evidence_ref
    raw=payload(repo,own)
    draft=ReportDraft.model_validate(raw['report_draft'])
    decisions=[VerificationDecision.model_validate(raw['decisions'][0])]
    claim=FindingCandidate.model_validate(candidate(repo,ref))
    decisions[0].causal_review=reviewed(claim,[own])
    with pytest.raises(AcceptanceError,match='inspect'):
        FinalAcceptanceGate({'f1':claim},evidence_refs={ref,own}).accept(draft,decisions)
    accepted=FinalAcceptanceGate({'f1':claim},evidence_refs={ref,own},inspected_evidence={own}).accept(draft,decisions)
    assert accepted.draft.confirmed_defects[0].evidence_refs==[own]


def test_broken_optional_summary_cannot_discard_confirmed_findings_or_fail_coverage(tmp_path):
    from devwatch.review.jobs import DurableJobManager
    from devwatch.review.stores import RepoCache
    from devwatch.review.workflow import CanonicalReviewExecutor
    from tests.test_canonical_workflow import ReviewProvider, stores
    from tests.test_control_agents import MODELS
    class BrokenSynthesis(ReviewProvider):
        async def generate_completion(self,request):
            response=await super().generate_completion(request)
            data=json.loads(request.prompt)
            action=json.loads(response.content)
            if data['phase']=='verification':
                for decision in action['payload']['decisions']:
                    decision.update(verdict='confirmed',confidence=.9)
                    for assessment in decision['causal_review']['assessments']: assessment['status']='supported'
            elif data['phase']=='synthesis':
                action['payload']['report_draft']['uncertain_high_impact_candidates']=[]
                action['payload']['report_draft']['confirmed_defects']=[]
            return response.model_copy(update={'content':json.dumps(action)})
    async def run():
        layout,artifacts,snapshot,jobs,events=stores(tmp_path)
        provider=BrokenSynthesis()
        executor=CanonicalReviewExecutor(layout,artifacts,RepoCache(layout.repo_cache),jobs,events,provider,models=MODELS)
        manager=DurableJobManager(jobs,events,executor)
        job=await manager.submit(owner='alice',request={'snapshot_id':snapshot.snapshot_id},idempotency_key='repair-fallback')
        done=await manager.wait(job.job_id,owner='alice')
        await manager.close()
        assert done.status=='completed'
        report=json.loads(done.result['json'])
        assert not report['confirmed_defects']
        assert len(report['uncertain_high_impact_candidates'])==1
        assert report['uncertain_high_impact_candidates'][0]['title']=='Empty input raises'
        assert '__final' not in report['coverage']['failed']
        assert len([r for r in provider.requests if json.loads(r.prompt)['phase']=='synthesis'])==0
    asyncio.run(run())


def test_deadline_recovery_preserves_persisted_inspected_verification(tmp_path, monkeypatch):
    from devwatch.review.stores import RepoCache
    from devwatch.review.workflow import CanonicalReviewExecutor
    from tests.test_canonical_workflow import ReviewProvider, stores
    from tests.test_control_agents import MODELS
    from devwatch.review.subgraphs import AgentSubgraphs
    class PausedSynthesis(ReviewProvider):
        def __init__(self):
            super().__init__()
            self.entered=asyncio.Event()
        async def generate_completion(self,request):
            if json.loads(request.prompt)['phase']=='synthesis':
                self.entered.set()
                await asyncio.Event().wait()
            response=await super().generate_completion(request)
            if json.loads(request.prompt)['phase']=='verification':
                action=json.loads(response.content)
                for decision in action['payload']['decisions']:
                    decision.update(verdict='confirmed',confidence=.9)
                    for assessment in decision['causal_review']['assessments']: assessment['status']='supported'
                response=response.model_copy(update={'content':json.dumps(action)})
            return response
    async def run():
        layout,artifacts,snapshot,jobs,events=stores(tmp_path)
        provider=PausedSynthesis()
        async def pause_assembly(engine, state):
            await engine._save(state)
            provider.entered.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(AgentSubgraphs, '_assemble_verified', pause_assembly)
        executor=CanonicalReviewExecutor(layout,artifacts,RepoCache(layout.repo_cache),jobs,events,provider,models=MODELS)
        job=jobs.submit(owner='alice',request={'snapshot_id':snapshot.snapshot_id},idempotency_key='deadline-verified')
        jobs.transition(job.job_id,owner='alice',expected_status='queued',status='running')
        operation=asyncio.create_task(executor(jobs.get(job.job_id,owner='alice')))
        await asyncio.wait_for(provider.entered.wait(),10)
        operation.cancel()
        await asyncio.gather(operation,return_exceptions=True)
        ledger=jobs.get(job.job_id,owner='alice').ledger
        ledger.elapsed_seconds=600
        jobs.update_ledger(job.job_id,owner='alice',ledger=ledger)
        before=len(provider.requests)
        report=json.loads((await executor.recover_timeout(jobs.get(job.job_id,owner='alice')))['json'])
        assert not report['confirmed_defects']
        assert len(report['uncertain_high_impact_candidates'])==1
        assert len(provider.requests)==before
        assert report['coverage']['failed']['__job']=='review_time_exhausted'
    asyncio.run(run())


def test_partial_recovery_downgrades_a_confirmation_without_inspection_receipts(tmp_path):
    from types import SimpleNamespace
    from devwatch.review.contracts import AgentPrivateState,ReviewTask,SpecialistResult,VerificationPhaseResult
    from devwatch.review.repository import SharedBlackboard,StructuralEvidenceGate
    from devwatch.review.workflow import _ReviewSession
    _,_,_,repo,task=setup_repository(tmp_path)
    ref=repo._read_source({'file_path':'service.py'},task).evidence_ref
    board=SharedBlackboard(StructuralEvidenceGate(repo))
    board.publish(task,SpecialistResult(task_id=task.task_id,agent_id=task.agent_id,candidates=[candidate(repo,ref)],coverage={},stop_reason='evidence_complete'))
    identity=next(iter(board.candidates))
    verification=VerificationPhaseResult(decisions=[dict(finding_id=identity,verdict='confirmed',confidence=.9,rationale='Old claim',evidence_refs=[ref])])
    session=SimpleNamespace(repository=repo,board=board)
    result=_ReviewSession.partial_result(session,AgentPrivateState(stop_reason='invalid_schema'),verification=verification)
    assert not result.report_draft.confirmed_defects
    assert len(result.report_draft.uncertain_high_impact_candidates)==1
    assert FinalAcceptanceGate(board.candidates,evidence_refs={ref},allow_unreviewed=True).accept(result.report_draft,result.decisions)


def test_inconsistent_persisted_synthesis_recovers_from_recorded_verification(tmp_path):
    from devwatch.review.budgets import BudgetManager
    from devwatch.review.contracts import SpecialistResult,VerificationSynthesisResult
    from devwatch.review.repository import RepositoryContext
    from devwatch.review.stores import RepoCache
    from devwatch.review.workflow import CanonicalReviewExecutor,_ReviewSession
    from tests.test_canonical_workflow import stores
    from tests.test_control_agents import MODELS
    from tests.test_iterative_agents import ScriptedProvider
    async def run():
        layout,artifacts,snapshot,jobs,events=stores(tmp_path)
        repo=RepositoryContext(artifacts,RepoCache(layout.repo_cache),snapshot.snapshot_id,owner='alice')
        from devwatch.review.contracts import ReviewTask
        task=ReviewTask(task_id='logic-1',agent_id='logic_correctness',files=['service.py'],focus='boundary')
        ref=repo._read_source({'file_path':'service.py'},task).evidence_ref
        provider=ScriptedProvider([])
        executor=CanonicalReviewExecutor(layout,artifacts,repo.cache,jobs,events,provider,models=MODELS)
        job=jobs.submit(owner='alice',request={'snapshot_id':snapshot.snapshot_id},idempotency_key='corrupted-synthesis')
        job=jobs.transition(job.job_id,owner='alice',expected_status='queued',status='running')
        session=_ReviewSession(executor,job,repo,BudgetManager(),['service.py'])
        result=SpecialistResult(task_id=task.task_id,agent_id=task.agent_id,candidates=[candidate(repo,ref)],coverage={},stop_reason='evidence_complete')
        session.publish(task,result)
        identity=next(iter(session.board.candidates))
        good=payload(repo,ref)
        good['decisions'][0]['finding_id']=identity
        approval = dict(kind='submit_verification', inspected_evidence=[ref], payload={'decisions':good['decisions']})
        runtime,_=engine(repo,[approval, approval])
        runtime.require_verification_challenge = True
        state=await runtime.run_final(snapshot_id=repo.snapshot_id,files=task.files,
            candidates={identity:session.board.candidates[identity].model_dump(mode='json')})
        good['report_draft']['confirmed_defects'][0]['finding_id']=identity
        good['decisions'][0]['finding_id']='corrupted-id'
        state['output']=VerificationSynthesisResult.model_validate(good)
        state['private_state'].stop_reason='evidence_complete'
        executor.checkpoints.save(session.thread_id,state,1)
        final=await session.finalize({'tasks':[task.model_dump(mode='json')],'results':[result.model_dump(mode='json')]})
        report=json.loads(final['rendered']['json'])
        assert not report['confirmed_defects']
        assert len(report['uncertain_high_impact_candidates'])==1
        assert report['uncertain_high_impact_candidates'][0]['finding_id']==identity
        assert 'Partial' in report['summary']
        assert provider.requests==[]
    asyncio.run(run())
