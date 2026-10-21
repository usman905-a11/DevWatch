"""Accepted exports expose decisions and contributors, including rejected findings."""
import pymupdf

from devwatch.review.contracts import VerificationDecision
from devwatch.review.finalization import FinalAcceptanceGate, assemble_report, render_accepted_report
from devwatch.review.pdf import render_accepted_pdf
from tests.test_m20_acceptance import claim
from tests.verification_fixtures import decision


def accepted():
    candidate = claim()
    record = VerificationDecision.model_validate(decision(candidate, ['ev1'], verdict='rejected', statuses={'impact': 'unsupported'}))
    draft = assemble_report('snapshot', {'f1': candidate}, [record], summary='Model summary')
    return FinalAcceptanceGate({'f1': candidate}, evidence_refs={'ev1'}, inspected_evidence={'ev1'},
        provenance={'f1': dict(task_id='logic-1', agent_id='logic_correctness')}).accept(draft, [record])


def test_markdown_exposes_rejected_decision_and_its_specialist_contributor():
    markdown = render_accepted_report(accepted())['markdown']
    assert 'f1: rejected' in markdown
    assert 'logic\\_correctness/logic-1' in markdown
    assert 'impact: unsupported' in markdown


def test_pdf_exposes_the_same_rejected_decision_and_its_specialist_contributor():
    data = render_accepted_pdf(accepted())
    with pymupdf.open(stream=data, filetype='pdf') as document:
        text = ''.join(page.get_text() for page in document)
    assert 'f1: rejected' in text
    assert 'logic_correctness/logic-1' in text
    assert 'impact: unsupported' in text
