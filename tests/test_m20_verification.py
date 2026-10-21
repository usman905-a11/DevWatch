"""Semantic admission through the real bounded final-agent graph."""
import asyncio

import pytest

from tests.test_audit_evidence import candidate, engine
from tests.test_repository_context import setup_repository
from tests.verification_fixtures import decision


def setup(tmp_path):
    _, _, _, repo, task = setup_repository(tmp_path)
    ref = repo._read_source({'file_path': 'service.py'}, task).evidence_ref
    return repo, task, ref, candidate(repo, ref)


def run(repo, task, ref, claim, record, *, acknowledge=True):
    action = dict(kind='submit_verification', payload=dict(decisions=[record]),
        inspected_evidence=[ref] if acknowledge else [])
    runtime, _ = engine(repo, [action, action, dict(kind='finish')])
    return asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id, files=task.files,
                                        candidates={'f1': claim}))


def test_core_rationale_without_whole_claim_review_cannot_confirm(tmp_path):
    repo, task, ref, claim = setup(tmp_path)
    record = dict(finding_id='f1', verdict='confirmed', confidence=.9,
                  rationale='Index zero raises on empty input.', evidence_refs=[ref])
    state = run(repo, task, ref, claim, record)
    assert state['verification'] is None
    assert state['private_state'].stop_reason == 'invalid_schema'


@pytest.mark.parametrize('verdict', ['confirmed', 'advisory', 'uncertain'])
def test_known_unsupported_impact_cannot_survive_in_any_report_bucket(tmp_path, verdict):
    repo, task, ref, claim = setup(tmp_path)
    claim['impact'] = 'Empty input raises IndexError; arbitrary OS commands execute.'
    record = decision(claim, [ref], verdict=verdict, statuses={'impact': 'unsupported'})
    state = run(repo, task, ref, claim, record)
    assert state['verification'] is None
    assert state['private_state'].stop_reason == 'invalid_schema'


@pytest.mark.parametrize('corruption', ['missing_field', 'duplicate_field', 'stale_claim', 'unknown_reference'])
def test_review_cannot_omit_fields_replay_another_claim_or_invent_evidence(tmp_path, corruption):
    repo, task, ref, claim = setup(tmp_path)
    record = decision(claim, [ref])
    if corruption == 'missing_field': record['causal_review']['assessments'].pop()
    if corruption == 'duplicate_field': record['causal_review']['assessments'][-1]['field'] = 'impact'
    if corruption == 'stale_claim': claim['impact'] = 'Different impact including an unsupported consequence.'
    if corruption == 'unknown_reference': record['causal_review']['assessments'][0]['evidence_refs'] = ['invented']
    state = run(repo, task, ref, claim, record)
    assert state['verification'] is None
    assert state['private_state'].stop_reason == 'invalid_schema'


def test_advisory_requires_verifier_source_inspection_too(tmp_path):
    repo, task, ref, claim = setup(tmp_path)
    state = run(repo, task, ref, claim, decision(claim, [ref], verdict='advisory'), acknowledge=False)
    assert state['verification'] is None
    assert state['private_state'].stop_reason == 'invalid_schema'


@pytest.mark.parametrize('verdict,statuses', [
    ('confirmed', {}), ('rejected', {'impact': 'unsupported'}),
    ('uncertain', {'impact': 'uncertain'}), ('advisory', {}),
])
def test_complete_reviews_preserve_supported_rejected_and_genuinely_uncertain_decisions(tmp_path, verdict, statuses):
    repo, task, ref, claim = setup(tmp_path)
    record = decision(claim, [ref], verdict=verdict, statuses=statuses,
                      confidence=.7 if verdict == 'uncertain' else .9)
    state = run(repo, task, ref, claim, record)
    assert state['verification'] is not None
    assert state['verification'].decisions[0].verdict == verdict


def test_prompt_batching_keeps_digest_bindings_limited_to_the_delivered_candidates(tmp_path):
    import json
    from devwatch.review.budgets import BudgetManager
    from devwatch.review.contracts import AGENT_CONTRACTS, AgentPrivateState, AgentWorkItem, BalancedLimits
    repo, _, _, claim = setup(tmp_path)
    runtime, _ = engine(repo, [])
    runtime.budget = BudgetManager(BalancedLimits(model_context_tokens=16000))
    state = dict(task=AgentWorkItem(task_id='__final', agent_id='synthesizer_verifier', files=['service.py'], focus='Verify'),
        private_state=AgentPrivateState(), phase='verification', snapshot_id=repo.snapshot_id,
        candidates={f'f{index}': {**claim, 'description': 'Index zero is unguarded. ' * 70} for index in range(8)})
    prompt, ceiling = runtime._prepare_prompt(state, {'snapshot_id': repo.snapshot_id, 'scope': ['service.py'], 'evidence': []}, repair=False)
    body = json.loads(prompt)
    assert 0 < len(body['candidates']) < 8
    assert set(body['candidate_digests']) == set(body['candidates'])
    assert len(prompt.encode()) + len(AGENT_CONTRACTS[state['task'].agent_id].system_prompt.encode()) + 512 + ceiling <= 16000


@pytest.mark.parametrize('extra_key,exposed', [('candidate_provenance', True), ('SECRET_DO_NOT_ECHO', False)])
def test_review_schema_repair_names_known_protocol_fields_without_reflecting_arbitrary_keys(tmp_path, extra_key, exposed):
    import json
    from copy import deepcopy
    repo, task, ref, claim = setup(tmp_path)
    good = decision(claim, [ref])
    bad = deepcopy(good)
    bad['causal_review'][extra_key] = 'private response content'
    def action(record):
        return dict(kind='submit_verification', payload=dict(decisions=[record]), inspected_evidence=[ref])
    runtime, provider = engine(repo, [action(bad), action(good), dict(kind='finish')])
    result = asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id, files=task.files, candidates={'f1':claim}))
    repair = json.loads(provider.requests[1].prompt)['repair']
    assert 'decisions.0.causal_review' in repair
    assert (extra_key in repair) == exposed
    assert 'private response content' not in repair
    assert result['verification'].decisions[0].verdict == 'confirmed'


@pytest.mark.parametrize('origin,has_source,expected', [
    ('performance_scalability', True, True), ('logic_correctness', True, False),
    ('performance_scalability', False, False),
])
def test_verifier_loads_cost_guidance_only_for_performance_origin_with_delivered_source(tmp_path, origin, has_source, expected):
    import json
    repo, task, _, claim = setup(tmp_path)
    runtime, provider = engine(repo, [dict(kind='finish')])
    def context(state):
        selected = repo.context(state)
        selected['candidate_provenance'] = {'f1':dict(task_id='input', agent_id=origin)}
        if not has_source: selected['evidence'] = []
        return selected
    runtime.context = context
    asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id, files=task.files, candidates={'f1':claim}))
    body = json.loads(provider.requests[0].prompt)
    assert ('performance_cost' in body['policy_skills']) == expected
    assert ('performance_cost' in body['prompt_revision']['skills']) == expected
