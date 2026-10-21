"""Final publication must not bypass semantic admission or inflate completeness."""
import pytest

from devwatch.review.contracts import FindingCandidate, VerificationDecision
from devwatch.review.finalization import AcceptanceError, FinalAcceptanceGate, assemble_report
from tests.verification_fixtures import decision


def claim():
    return FindingCandidate(category='bug', title='Empty input raises', description='items[0] raises for items=[]',
        impact='The call raises IndexError for empty input.', confidence=.9, evidence_refs=['ev1'],
        location=dict(snapshot_id='snapshot', file_path='service.py', start_line=2, end_line=2))


def gate(candidate):
    return FinalAcceptanceGate({'f1': candidate}, evidence_refs={'ev1'}, inspected_evidence={'ev1'}, snapshot_id='snapshot')


def draft(candidate, record, **kwargs):
    return assemble_report('snapshot', {'f1': candidate}, [record], summary='Every repository path is exhaustively reviewed.', **kwargs)


@pytest.mark.parametrize('corruption', ['missing_review', 'unsupported_field', 'stale_claim'])
def test_final_acceptance_revalidates_semantic_decisions_including_restored_results(corruption):
    candidate = claim()
    raw = decision(candidate, ['ev1'])
    if corruption == 'missing_review': raw.pop('causal_review')
    if corruption == 'unsupported_field': raw['causal_review']['assessments'][2]['status'] = 'unsupported'
    if corruption == 'stale_claim': candidate.impact = 'A different, unreviewed impact.'
    record = VerificationDecision.model_validate(raw)
    with pytest.raises(AcceptanceError):
        gate(candidate).accept(draft(candidate, record), [record])


def test_accepted_report_retains_rejection_review_trace_and_replaces_unbounded_summary():
    candidate = claim()
    record = VerificationDecision.model_validate(decision(candidate, ['ev1'], verdict='rejected', statuses={'impact': 'unsupported'}))
    result = gate(candidate).accept(draft(candidate, record), [record]).draft.model_dump(mode='json')
    assert not result['confirmed_defects'] and not result['uncertain_high_impact_candidates']
    audit = result.get('verification_audit')
    assert audit is not None and audit['decisions'][0]['verdict'] == 'rejected'
    assert audit['decisions'][0]['causal_review']['assessments'][2]['status'] == 'unsupported'
    assert 'exhaustively' not in result['summary']


def test_incomplete_coverage_cannot_be_hidden_by_synthesis_summary():
    from devwatch.review.contracts import Coverage
    candidate = claim()
    record = VerificationDecision.model_validate(decision(candidate, ['ev1']))
    report = draft(candidate, record, coverage=Coverage(inspected_files=['service.py'],
        skipped={'unopened.py': 'budget'}, failed={'test': 'tool_unavailable'}))
    accepted = gate(candidate).accept(report, [record]).draft
    assert accepted.summary.startswith('Partial review:')
    assert 'exhaustively' not in accepted.summary
    assert accepted.coverage.skipped == {'unopened.py': 'budget'}
    assert accepted.coverage.failed == {'test': 'tool_unavailable'}
