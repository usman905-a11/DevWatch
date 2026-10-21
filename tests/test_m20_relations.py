"""Duplicate and disagreement semantics use reviewed identities, never textual votes."""
import asyncio

import pytest

from tests.test_audit_evidence import candidate, engine
from tests.test_repository_context import setup_repository
from tests.verification_fixtures import decision


def scenario(tmp_path, *, verdicts=('confirmed', 'confirmed'), other_file=False, relation=None, groups=None):
    _, _, _, repo, task = setup_repository(tmp_path)
    ref = repo._read_source({'file_path': 'service.py'}, task).evidence_ref
    claims = {'f1': candidate(repo, ref), 'f2': {**candidate(repo, ref), 'title': 'Another view of the same empty index'}}
    if other_file:
        claims['f2']['location'] = {**claims['f2']['location'], 'file_path': 'other.py', 'start_line': 1, 'end_line': 1}
    records = [decision(claim, [ref], identity=identity, verdict=verdict,
        statuses={'impact': 'uncertain'} if verdict == 'uncertain' else {},
        confidence=.7 if verdict == 'uncertain' else .9)
        for (identity, claim), verdict in zip(claims.items(), verdicts)]
    payload = dict(decisions=records, duplicate_groups=groups or [], **(relation or {}))
    action = dict(kind='submit_verification', inspected_evidence=[ref], payload=payload)
    runtime, _ = engine(repo, [action, action, dict(kind='finish')])
    state = asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id, files=list(repo.manifest.entries), candidates=claims))
    return state


def test_duplicate_groups_require_recorded_causal_equivalence(tmp_path):
    state = scenario(tmp_path, groups=[['f1', 'f2']])
    assert state['verification'] is None
    assert state['private_state'].stop_reason == 'invalid_schema'


def test_equivalent_source_backed_duplicates_are_accepted(tmp_path):
    # Use a provider fixture that takes the real reference from its received request.
    state = with_relation(tmp_path, 'duplicate')
    assert state['verification'] is not None
    assert state['verification'].duplicate_groups == [['f1', 'f2']]


def test_equivalent_uncertain_duplicates_preserve_the_same_recorded_evidence_gap(tmp_path):
    state = with_relation(tmp_path, 'duplicate', verdicts=('uncertain', 'uncertain'))
    assert state['verification'] is not None
    assert [item.verdict for item in state['verification'].decisions] == ['uncertain', 'uncertain']


def with_relation(tmp_path, kind, *, verdicts=('confirmed', 'confirmed'), other_file=False):
    from tests.test_audit_evidence import engine as make_engine
    _, _, _, repo, task = setup_repository(tmp_path)
    task = task.model_copy(update={'files': list(repo.manifest.entries)})
    ref = repo._read_source({'file_path': 'service.py'}, task).evidence_ref
    claims = {'f1': candidate(repo, ref), 'f2': {**candidate(repo, ref), 'title': 'Same index from another specialist'}}
    refs = [ref]
    if other_file:
        second = repo._read_source({'file_path':'other.py'}, task).evidence_ref
        refs.append(second)
        claims['f2']['evidence_refs'] = [second]
        claims['f2']['location'] = {**claims['f2']['location'], 'file_path': 'other.py', 'start_line': 1, 'end_line': 1}
    records = [decision(claim, claim['evidence_refs'], identity=identity, verdict=verdict,
        statuses={'impact': 'uncertain'} if verdict == 'uncertain' else {},
        confidence=.7 if verdict == 'uncertain' else .9)
        for (identity, claim), verdict in zip(claims.items(), verdicts)]
    relation = dict(finding_ids=['f1', 'f2'], rationale='Same empty-index source operation.', evidence_refs=refs)
    if kind == 'duplicate':
        extras = dict(duplicate_groups=[['f1', 'f2']], duplicate_reviews=[relation])
    else:
        relation['resolution'] = kind
        extras = dict(disagreements=[relation])
    action = dict(kind='submit_verification', inspected_evidence=refs, payload=dict(decisions=records, **extras))
    runtime, _ = make_engine(repo, [action, action, dict(kind='finish')])
    return asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id, files=list(repo.manifest.entries), candidates=claims))


@pytest.mark.parametrize('kind,verdicts', [
    ('duplicate', ('confirmed', 'confirmed')), ('unresolved', ('confirmed', 'confirmed')),
    ('resolved', ('confirmed', 'confirmed')),
])
def test_unrelated_duplicate_or_unresolved_and_double_positive_conflicts_are_rejected(tmp_path, kind, verdicts):
    state = with_relation(tmp_path, kind, verdicts=verdicts, other_file=kind == 'duplicate')
    assert state['verification'] is None
    assert state['private_state'].stop_reason == 'invalid_schema'


@pytest.mark.parametrize('kind,verdicts', [
    ('unresolved', ('uncertain', 'uncertain')), ('resolved', ('confirmed', 'rejected')),
])
def test_disagreement_preserves_uncertainty_or_one_supported_position(tmp_path, kind, verdicts):
    state = with_relation(tmp_path, kind, verdicts=verdicts)
    assert state['verification'] is not None
    assert state['verification'].disagreements[0].resolution == kind
