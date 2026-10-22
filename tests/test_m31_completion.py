"""Regressions for the exact M30 repair and required-contract failures."""
import json
import pytest

from devwatch.providers.base import LLMResponse, LLMUsage
from devwatch.review.contracts import AgentPrivateState
from tests.test_m19_candidate_repair import setup
from tests.test_m16_investigation import complete, engine
from tests.test_iterative_agents import ScriptedProvider


@pytest.mark.asyncio
async def test_arithmetic_shape_repair_names_constraint_without_echoing_values(tmp_path):
    repo, task, ref, good, _ = setup(tmp_path)
    good = {**good, 'description': 'For integers x in [2, 2] step 1: x + 1 == 3.',
        'arithmetic_claims': [dict(field='description', expression='x + 1 == 3',
            variables={'x':dict(start=2,stop=2,step=1)})]}
    import copy
    bad = copy.deepcopy(good)
    bad['arithmetic_claims'][0]['variables']['x']['start'] = 'PRIVATE_EXPLANATION_NEVER_ECHO'
    class Provider(ScriptedProvider):
        async def generate_completion(self, request):
            body = json.loads(request.prompt)
            repair = body.get('repair') or ''
            repaired = 'arithmetic_claims' in repair and 'int_type' in repair
            self.responses = iter([complete(task, [good if repaired else bad], [ref])])
            return await super().generate_completion(request)
    provider = Provider([])
    graph = engine(repo, provider)
    result = await graph.run_specialist(task, private_state=AgentPrivateState(evidence_refs=[ref]))
    assert result['output'].stop_reason == 'evidence_complete'
    assert len(result['output'].candidates) == 1
    assert result['output'].candidates[0].description == 'For integers x in [2, 2] step 1: x + 1 == 3.'
    assert graph.budget.ledger.task_schema_repairs[task.task_id] == 1
    assert 'PRIVATE_EXPLANATION_NEVER_ECHO' not in json.loads(provider.requests[1].prompt)['repair']


@pytest.mark.asyncio
async def test_agreeing_model_reviews_cannot_independently_confirm_whole_claim(tmp_path):
    from tests.test_m20_verification import setup as final_setup
    from tests.test_audit_evidence import engine as final_engine
    from tests.verification_fixtures import decision
    repo, task, ref, claim = final_setup(tmp_path)
    record = decision(claim, [ref])
    action = dict(kind='submit_verification', inspected_evidence=[ref], payload=dict(decisions=[record]))
    graph, provider = final_engine(repo, [action, action])
    graph.require_verification_challenge = True
    graph.require_independent_support = True
    state = await graph.run_final(snapshot_id=repo.snapshot_id, files=task.files, candidates={'f1':claim})
    assert state['output'] is not None
    assert not state['output'].report_draft.confirmed_defects
    finding = state['output'].report_draft.uncertain_high_impact_candidates[0]
    assert finding.description == claim['description']
    assert finding.confidence <= .5
    assert [item.decision.verdict for item in state['verification'].review_observations] == ['confirmed','confirmed']


def test_strict_acceptance_refuses_even_arithmetically_correct_model_confirmation(tmp_path):
    from tests.test_m20_verification import setup as final_setup
    from tests.verification_fixtures import decision
    from devwatch.review.contracts import FindingCandidate, VerificationDecision
    from devwatch.review.finalization import FinalAcceptanceGate, assemble_report, AcceptanceError
    repo, _, ref, claim = final_setup(tmp_path)
    claim = {**claim, 'description':'XOR flips the lowest set bit.', 'arithmetic_claims':[
        dict(field='description', expression='(n ^ (n - 1)) == 1',variables={'n':dict(start=3,stop=3,step=1)})]}
    record = VerificationDecision.model_validate(decision(claim, [ref]))
    gate = FinalAcceptanceGate({'f1': FindingCandidate.model_validate(claim)}, evidence_refs={ref},
        inspected_evidence={ref}, require_independent_support=True)
    draft = assemble_report(repo.snapshot_id, {'f1':claim}, [record], summary='review')
    with pytest.raises(AcceptanceError, match='independent'):
        gate.accept(draft, [record])


@pytest.mark.asyncio
async def test_runtime_renders_arithmetic_in_audit_without_duplicate_prose_encoding(tmp_path):
    from devwatch.review.verification import arithmetic_receipts
    repo, task, ref, good, _ = setup(tmp_path)
    good = {**good, 'description':'For n=1, the update retains 1. Integer assertion: (1 ^ (1 - 1)) == 1, so a loop can remain at 1.',
        'arithmetic_claims':[dict(field='description',expression='(1 ^ (1 - 1)) == 1',variables={})]}
    provider = ScriptedProvider([complete(task,[good],[ref])])
    graph = engine(repo,provider)
    result = await graph.run_specialist(task,private_state=AgentPrivateState(evidence_refs=[ref]))
    assert result['output'].stop_reason == 'evidence_complete'
    candidate = result['output'].candidates[0]
    assert candidate.description == good['description']
    receipt = arithmetic_receipts(candidate)[0]
    assert receipt.statement == 'Integer assertion: (1 ^ (1 - 1)) == 1.'
    assert receipt.result.status == 'supported'
    assert graph.budget.ledger.task_schema_repairs.get(task.task_id,0) == 0


@pytest.mark.asyncio
async def test_retained_candidate_cannot_end_before_required_contract_read_and_ack(tmp_path):
    from devwatch.review.repository import RepositoryContext
    from tests.test_repository_context import setup_repository
    from tests.test_audit_evidence import candidate
    _, artifacts, _, original, task = setup_repository(tmp_path)
    snapshot = artifacts.capture(owner='alice', files={'service.py':'def first(items):\n    return items[0]\n',
        'REVIEW_CONTRACT.md':'Empty input is allowed.\n'})
    repo = RepositoryContext(artifacts, original.cache, snapshot.snapshot_id, owner='alice')
    task = task.model_copy(update={'files':['service.py','REVIEW_CONTRACT.md']})
    ref = repo._read_source({'file_path':'service.py'}, task).evidence_ref
    record = candidate(repo, ref)
    class Provider(ScriptedProvider):
        async def generate_completion(self, request):
            body = json.loads(request.prompt)
            pages = body['selected_context']['evidence']
            refs = [p['evidence_ref'] for p in pages]
            if len(self.requests) == 0:
                action = complete(task, [record], [ref])
            elif 'REVIEW_CONTRACT.md' in (body.get('repair') or ''):
                action = dict(kind='call_tool', tool='read_source', arguments={'file_path':'REVIEW_CONTRACT.md'},
                    inspected_evidence=refs)
            else:
                action = complete(task, [record], refs)
            self.responses = iter([action])
            return await super().generate_completion(request)
    provider = Provider([])
    graph = engine(repo, provider)
    result = await graph.run_specialist(task, private_state=AgentPrivateState(evidence_refs=[ref]))
    assert result['output'].stop_reason == 'evidence_complete'
    assert set(result['output'].coverage.inspected_files) == {'service.py','REVIEW_CONTRACT.md'}
    assert len(result['output'].candidates) == 1
    assert len(provider.requests) == 3
    assert graph.budget.ledger.task_schema_repairs[task.task_id] == 1


@pytest.mark.asyncio
async def test_canonical_service_retains_detection_without_calling_it_confirmation(tmp_path):
    from scripts.evaluate_agents import load_corpus, review_input, run_case
    from tests.test_m19_evaluation import RecordingProvider
    case = load_corpus()[0]
    row = await run_case(case, tmp_path, mode='full', provider=RecordingProvider(review_input(case)))
    assert row['score']['true_positive'] == 1
    assert row['findings'] and all(f['kind']=='high_impact_candidate' for f in row['findings'])
    assert all(f['confidence']<=.5 for f in row['findings'])
    assert not row['coverage']['failed']


@pytest.mark.asyncio
async def test_benchmark_distinguishes_detection_from_independent_confirmation(tmp_path):
    from scripts.evaluate_reviews import evaluate
    from tests.test_canonical_evaluation import corpus
    summary = await evaluate([corpus()['cases'][0]], tmp_path)
    assert summary['confirmed_recall'] == 0
    assert summary['candidate_recall'] == 1
    assert summary['candidate_precision'] == 1
    assert summary['publication_policy_satisfied'] is True


@pytest.mark.asyncio
async def test_two_unproven_rejections_cannot_silently_discard_a_candidate(tmp_path):
    from tests.test_m20_verification import setup as final_setup
    from tests.test_audit_evidence import engine as final_engine
    from tests.verification_fixtures import decision
    repo, task, ref, claim = final_setup(tmp_path)
    record = decision(claim, [ref], verdict='rejected', statuses={'description':'unsupported'})
    action = dict(kind='submit_verification', inspected_evidence=[ref], payload=dict(decisions=[record]))
    graph, _ = final_engine(repo, [action, action])
    graph.require_verification_challenge = graph.require_independent_support = True
    state = await graph.run_final(snapshot_id=repo.snapshot_id, files=task.files, candidates={'f1':claim})
    assert state['verification'].decisions[0].verdict == 'uncertain'
    assert state['output'].report_draft.uncertain_high_impact_candidates[0].description == claim['description']
    assert [item.decision.verdict for item in state['verification'].review_observations] == ['rejected','rejected']


def test_uninspected_rejection_recovers_as_unreviewed_candidate(tmp_path):
    from tests.test_m20_recovery import setup as recovery_setup
    from tests.verification_fixtures import decision
    from devwatch.review.contracts import VerificationPhaseResult
    from devwatch.review.finalization import FinalAcceptanceGate
    from devwatch.review.workflow import _ReviewSession
    session, identity, ref = recovery_setup(tmp_path)
    raw = decision(session.board.candidates[identity], [ref], identity=identity,
        verdict='rejected', statuses={'impact':'unsupported'})
    result = _ReviewSession.partial_result(session, AgentPrivateState(stop_reason='invalid_schema'),
        verification=VerificationPhaseResult(decisions=[raw]))
    accepted = FinalAcceptanceGate(session.board.candidates, evidence_refs={ref}, inspected_evidence=set(),
        verification=result, allow_unreviewed=True, require_independent_support=True).accept(result.report_draft,result.decisions)
    assert accepted.draft.verification_audit.decisions[0].causal_review is None
    assert accepted.draft.uncertain_high_impact_candidates[0].confidence <= .5
