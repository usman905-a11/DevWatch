"""Completed causal verification must not pay for a redundant summary generation."""
import asyncio
import json

from devwatch.review.contracts import AgentPrivateState
from tests.test_audit_evidence import engine
from tests.test_m20_verification import setup
from tests.verification_fixtures import decision


def test_verified_report_finishes_after_one_call_with_audit_and_conflicts(tmp_path):
    repo, task, ref, claim = setup(tmp_path)
    runtime, provider = engine(repo, [dict(kind='submit_verification', inspected_evidence=[ref],
        payload=dict(decisions=[decision(claim, [ref])], conflicts=['Only the captured function was reviewed.']))])
    state = asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id, files=task.files, candidates={'f1':claim}))
    assert state['private_state'].stop_reason == 'evidence_complete'
    assert len(provider.requests) == 1
    draft = state['output'].report_draft
    assert len(draft.confirmed_defects) == 1
    assert state['output'].decisions[0].causal_review is not None
    assert 'Only the captured function was reviewed.' in draft.limitations
    assert draft.coverage.inspected_files == ['service.py']


def restored(repo, ref, claim):
    # Capture a real post-verification checkpoint before deterministic assembly.
    seen = []
    runtime, provider = engine(repo, [dict(kind='submit_verification', inspected_evidence=[ref],
        payload=dict(decisions=[decision(claim, [ref])]))])
    async def persist(state, ledger):
        if state.get('phase') == 'synthesis':
            from devwatch.review.workflow import _serializable
            seen.append(_serializable(state))
    runtime.persist = persist
    asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id, files=['service.py'], candidates={'f1':claim}))
    assert seen
    return seen[0]


def test_restored_verified_phase_needs_no_provider_call(tmp_path):
    repo, _, ref, claim = setup(tmp_path)
    checkpoint = restored(repo, ref, claim)
    runtime, provider = engine(repo, [])
    state = asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id, files=['service.py'], candidates={'f1':claim},
        private_state=AgentPrivateState.model_validate(checkpoint['private_state']), restored_state=checkpoint))
    assert state['private_state'].stop_reason == 'evidence_complete'
    assert len(provider.requests) == 0
    assert len(state['output'].report_draft.confirmed_defects) == 1


def test_restored_verified_phase_rechecks_complete_inspection(tmp_path):
    repo, _, ref, claim = setup(tmp_path)
    checkpoint = restored(repo, ref, claim)
    private = AgentPrivateState.model_validate(checkpoint['private_state'])
    private.evidence_progress[ref].inspected = []
    runtime, provider = engine(repo, [])
    state = asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id, files=['service.py'], candidates={'f1':claim},
        private_state=private, restored_state=checkpoint))
    assert state['private_state'].stop_reason != 'evidence_complete'
    assert state['output'] is None
    assert len(provider.requests) == 0


def test_missing_causal_review_in_restored_phase_cannot_finish(tmp_path):
    repo, _, ref, claim = setup(tmp_path)
    checkpoint = restored(repo, ref, claim)
    checkpoint['verification']['decisions'][0]['causal_review'] = None
    runtime, provider = engine(repo, [])
    state = asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id, files=['service.py'], candidates={'f1':claim},
        private_state=AgentPrivateState.model_validate(checkpoint['private_state']), restored_state=checkpoint))
    assert state['private_state'].stop_reason != 'evidence_complete'
    assert state['output'] is None
    assert len(provider.requests) == 0


def test_revalidation_keeps_one_unresolved_disagreement_limitation(tmp_path):
    from devwatch.review.contracts import FindingCandidate
    from devwatch.review.finalization import FinalAcceptanceGate
    from tests.test_m20_relations import with_relation
    state = with_relation(tmp_path, 'unresolved', verdicts=('uncertain','uncertain'))
    claims = {identity:FindingCandidate.model_validate(raw) for identity,raw in state['candidates'].items()}
    refs = {ref for claim in claims.values() for ref in claim.evidence_refs}
    accepted = FinalAcceptanceGate(claims, evidence_refs=refs, inspected_evidence=refs,
        verification=state['verification']).accept(state['output'].report_draft,state['verification'].decisions)
    assert sum(note.startswith('Unresolved disagreement:') for note in accepted.draft.limitations) == 1
