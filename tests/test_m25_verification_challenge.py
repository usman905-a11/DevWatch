"""A provisional approval must not bypass a later counterexample or interruption."""
import asyncio
import json

import pytest

from tests.test_audit_evidence import engine
from tests.test_m20_verification import setup
from tests.verification_fixtures import decision
from devwatch.review.contracts import VerificationPhaseResult
from devwatch.review import verification


def action(record, ref):
    return dict(kind='submit_verification', inspected_evidence=[ref],
                payload=dict(decisions=[record]))


@pytest.mark.parametrize('challenge_verdict', ['rejected', 'uncertain', 'advisory'])
def test_counterexample_cannot_be_overridden_by_first_positive_judgment(tmp_path, challenge_verdict):
    repo, task, ref, claim = setup(tmp_path)
    first = decision(claim, [ref])
    statuses = ({'impact': 'unsupported'} if challenge_verdict == 'rejected' else
                {'impact': 'uncertain'} if challenge_verdict == 'uncertain' else {})
    second = decision(claim, [ref], verdict=challenge_verdict, statuses=statuses,
                      confidence=.7 if challenge_verdict == 'uncertain' else .85)
    runtime, provider = engine(repo, [action(first, ref), action(second, ref), {'kind': 'finish'}])
    runtime.require_verification_challenge = True
    state = asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id, files=task.files,
                                          candidates={'f1': claim}))
    assert state['verification'].decisions[0].verdict == ('uncertain' if challenge_verdict == 'rejected' else challenge_verdict)
    assert state['verification'].decisions[0].confidence <= second['confidence']
    challenge = json.loads(provider.requests[1].prompt)
    assert challenge['verification_challenge'] is True
    assert first['rationale'] not in json.dumps(challenge.get('verified'))


def test_interruption_after_first_approval_cannot_publish_it(tmp_path):
    repo, task, ref, claim = setup(tmp_path)
    runtime, _ = engine(repo, [action(decision(claim, [ref]), ref), {'kind': 'finish'}])
    runtime.require_verification_challenge = True
    state = asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id, files=task.files,
                                          candidates={'f1': claim}))
    assert state['verification'] is None
    assert state['provisional_verification'].decisions[0].verdict == 'confirmed'
    assert state.get('output') is None


@pytest.mark.parametrize('first_verdict,second_verdict,expected', [
    ('confirmed', 'confirmed', 'confirmed'),
    ('advisory', 'confirmed', 'advisory'),
    ('uncertain', 'confirmed', 'uncertain'),
    ('rejected', 'confirmed', 'uncertain'),
])
def test_reconciliation_cannot_turn_disagreement_into_confirmation(tmp_path, first_verdict, second_verdict, expected):
    _, _, ref, claim = setup(tmp_path)
    def result(verdict, confidence):
        statuses = {'impact': 'unsupported'} if verdict == 'rejected' else {'impact': 'uncertain'} if verdict == 'uncertain' else {}
        return VerificationPhaseResult(decisions=[decision(claim, [ref], verdict=verdict,
            statuses=statuses, confidence=confidence)])
    reconciled = verification.reconcile_challenge({'f1': claim},
        result(first_verdict, .7 if first_verdict == 'uncertain' else .9), result(second_verdict, .85))
    assert len(reconciled.decisions) == 1
    assert reconciled.decisions[0].verdict == expected
    assert reconciled.decisions[0].confidence <= .85


def test_reconciliation_rejects_judgments_bound_to_another_claim(tmp_path):
    _, _, ref, claim = setup(tmp_path)
    first = VerificationPhaseResult(decisions=[decision(claim, [ref])])
    changed = {**claim, 'impact': 'A different unsupported consequence.'}
    second = VerificationPhaseResult(decisions=[decision(changed, [ref])])
    with pytest.raises(ValueError, match='different candidate'):
        verification.reconcile_challenge({'f1': claim}, first, second)


@pytest.mark.parametrize('missing', [True, False])
def test_reconciliation_requires_the_same_distinct_candidate_set(tmp_path, missing):
    _, _, ref, claim = setup(tmp_path)
    first = VerificationPhaseResult(decisions=[decision(claim, [ref])])
    second = VerificationPhaseResult(decisions=[] if missing else [decision(claim, [ref]), decision(claim, [ref])])
    with pytest.raises(ValueError, match='candidate'):
        verification.reconcile_challenge({'f1': claim}, first, second)


def serializable(state):
    return json.loads(json.dumps(state, default=lambda value: value.model_dump(mode='json')))


def test_legacy_inflight_approval_cannot_bypass_the_current_challenge_policy(tmp_path):
    repo, task, ref, claim = setup(tmp_path)
    legacy, _ = engine(repo, [action(decision(claim, [ref]), ref)])
    old = asyncio.run(legacy.run_final(snapshot_id=repo.snapshot_id, files=task.files, candidates={'f1': claim}))
    runtime, provider = engine(repo, [action(decision(claim, [ref], verdict='rejected', statuses={'impact': 'unsupported'}), ref)])
    runtime.require_verification_challenge = True
    runtime.budget = legacy.budget
    prior_iterations = runtime.budget.ledger.task_iterations['__final']
    state = asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id, files=task.files, candidates={'f1': claim},
        restored_state=serializable(old), private_state=old['private_state']))
    assert state['verification'].decisions[0].verdict == 'uncertain'
    assert len(provider.requests) == 1
    assert runtime.budget.ledger.task_iterations['__final'] == prior_iterations + 1


def test_pending_challenge_survives_restart_without_repeating_the_first_pass(tmp_path):
    repo, task, ref, claim = setup(tmp_path)
    runtime, _ = engine(repo, [action(decision(claim, [ref]), ref), {'kind': 'finish'}])
    runtime.require_verification_challenge = True
    paused = asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id, files=task.files, candidates={'f1': claim}))
    prior_iterations = runtime.budget.ledger.task_iterations['__final']
    from tests.test_iterative_agents import ScriptedProvider
    provider = ScriptedProvider([action(decision(claim, [ref], verdict='rejected', statuses={'impact': 'unsupported'}), ref)])
    runtime.provider = provider
    state = asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id, files=task.files, candidates={'f1': claim},
        restored_state=serializable(paused), private_state=paused['private_state']))
    assert state['verification'].decisions[0].verdict == 'uncertain'
    assert len(provider.requests) == 1
    assert runtime.budget.ledger.task_iterations['__final'] == prior_iterations + 1


def test_timeout_recovery_does_not_admit_a_legacy_positive_checkpoint(tmp_path):
    _, _, ref, claim = setup(tmp_path)
    raw = dict(verification=VerificationPhaseResult(decisions=[decision(claim, [ref])]).model_dump(mode='json'))
    assert verification.checkpoint_verification(raw) is None


def test_reconciled_checkpoint_retains_its_recorded_verdict_on_recovery(tmp_path):
    _, _, ref, claim = setup(tmp_path)
    raw = dict(verification_policy=verification.CHALLENGE_POLICY,
        verification=VerificationPhaseResult(decisions=[decision(claim, [ref])]).model_dump(mode='json'))
    result = verification.checkpoint_verification(raw)
    assert result.decisions[0].verdict == 'confirmed'


@pytest.mark.asyncio
async def test_canonical_report_preserves_disputed_candidate_without_confirmation(tmp_path):
    from scripts.evaluate_agents import load_corpus, review_input, run_case
    from tests.test_m19_evaluation import RecordingProvider
    case = load_corpus()[0]
    class Counterexample(RecordingProvider):
        async def generate_completion(self, request):
            response = await super().generate_completion(request)
            body = json.loads(request.prompt)
            value = json.loads(response.content)
            if body.get('verification_challenge') and value['kind'] == 'submit_verification':
                for record in value['payload']['decisions']:
                    record['verdict'] = 'rejected'
                    record['causal_review']['assessments'][2]['status'] = 'unsupported'
            return response.model_copy(update={'content': json.dumps(value)})
    provider = Counterexample(review_input(case))
    row = await run_case(case, tmp_path, mode='full', provider=provider)
    assert row['candidate_score']['true_positive'] == 1
    assert len(row['findings']) == 1
    assert row['findings'][0]['kind'] == 'high_impact_candidate'
    assert row['findings'][0]['confidence'] < .8
    assert any(json.loads(request.prompt).get('verification_challenge') for request in provider.requests)


def test_challenge_batch_shrinking_keeps_undelivered_candidates_provisional(tmp_path):
    from devwatch.review.budgets import BudgetManager
    from devwatch.review.contracts import BalancedLimits
    from tests.test_iterative_agents import ScriptedProvider
    repo, task, ref, claim = setup(tmp_path)
    candidates = {f'f{index}': {**claim, 'description': 'Index zero is unguarded. ' * 70} for index in range(8)}
    provisional = VerificationPhaseResult(decisions=[decision(value, [ref], identity=identity)
        for identity, value in candidates.items()])
    class Provider(ScriptedProvider):
        async def generate_completion(self, request):
            body = json.loads(request.prompt)
            self.responses = iter([dict(kind='submit_verification', inspected_evidence=[ref],
                payload=dict(decisions=[decision(value, [ref], identity=identity)
                    for identity, value in body['candidates'].items()]))])
            return await super().generate_completion(request)
    provider = Provider([])
    runtime, _ = engine(repo, [])
    runtime.provider = provider
    runtime.require_verification_challenge = True
    runtime.budget = BudgetManager(BalancedLimits(model_context_tokens=24000))
    restored = dict(snapshot_id=repo.snapshot_id, candidates=candidates,
        task=dict(agent_id='synthesizer_verifier'), phase='verification',
        provisional_verification=provisional.model_dump(mode='json'), verification_policy=verification.CHALLENGE_POLICY)
    state = asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id, files=task.files, candidates=candidates,
        restored_state=restored))
    assert state['private_state'].stop_reason == 'evidence_complete', state.get('validation_error')
    batches = [set(json.loads(request.prompt)['candidates']) for request in provider.requests]
    assert 1 < len(batches) <= 8
    assert all(len(batch) < 8 for batch in batches)
    assert set.union(*batches) == set(candidates)
    assert sum(map(len, batches)) == 8
    assert {item.finding_id for item in state['verification'].decisions} == set(candidates)
    assert state['provisional_verification'] is None


def test_failed_challenge_preserves_unknown_usage_and_publishes_no_approval(tmp_path):
    from tests.test_iterative_agents import ScriptedProvider
    repo, task, ref, claim = setup(tmp_path)
    class FailingChallenge(ScriptedProvider):
        async def generate_completion(self, request):
            if json.loads(request.prompt).get('verification_challenge'):
                self.requests.append(request)
                raise TimeoutError('Synthetic ambiguous transport timeout')
            return await super().generate_completion(request)
    provider = FailingChallenge([action(decision(claim, [ref]), ref)])
    runtime, _ = engine(repo, [])
    runtime.provider = provider
    runtime.require_verification_challenge = True
    state = asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id, files=task.files, candidates={'f1': claim}))
    assert len(provider.requests) == 2
    assert state['verification'] is None
    assert state['provisional_verification'] is not None
    assert state['provider_observations'][-1]['status'] == 'unknown'
    assert state['provider_observations'][-1]['charged_tokens'] > 0


def test_disagreement_does_not_retain_relations_that_could_merge_a_vetoed_claim(tmp_path):
    _, _, ref, claim = setup(tmp_path)
    claims = {'f1': claim, 'f2': {**claim, 'title': 'The same empty-index defect'}}
    first = VerificationPhaseResult(decisions=[decision(value, [ref], identity=identity)
        for identity, value in claims.items()])
    second = VerificationPhaseResult(decisions=[decision(claim, [ref], verdict='rejected', statuses={'impact':'unsupported'}),
        decision(claims['f2'], [ref], identity='f2')],
        duplicate_groups=[['f1','f2']], conflicts=['A retained evidence qualification.'])
    result = verification.reconcile_challenge(claims, first, second)
    assert result.duplicate_groups == result.duplicate_reviews == result.disagreements == []
    assert result.decisions[0].verdict == 'uncertain'
    assert 'A retained evidence qualification.' in result.conflicts
