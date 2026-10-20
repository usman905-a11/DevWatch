"""Crowded, immutable evidence contexts retain relevant pages and scope checks."""
import json

import pytest

from devwatch.review.contracts import AgentAction, AgentPrivateState, EvidenceProgress
from tests.test_repository_context import setup_repository


def inspected(repo,task,ref):
    page=repo.evidence_page(ref,task)
    spans=[]
    while True:
        spans.append((page['offset'],page['end_offset']))
        if page['next_offset'] is None:
            break
        page=repo.evidence_page(ref,task,offset=page['next_offset'])
    return EvidenceProgress(processed=True,delivered=spans,inspected=spans,
        total_chars=page['total_chars'],source_file=page['source_file'])


def test_uninspected_source_survives_crowding_by_newer_inspected_facts(tmp_path):
    _,_,_,repo,task=setup_repository(tmp_path)
    source=repo._read_source({'file_path':'service.py'},task).evidence_ref
    facts=[repo._record(dict(tool='parse_ast',source_scope=task.files,data='x'*1300+str(i)),work=task).evidence_ref
           for i in range(4)]
    private=AgentPrivateState(evidence_refs=[source,*facts],
        evidence_progress={ref:inspected(repo,task,ref) for ref in facts})
    before=private.model_dump_json()
    context=repo.context(dict(task=task,private_state=private))
    assert context['evidence'][0]['evidence_ref']==source
    assert any(page['evidence_ref']==source for page in context['evidence'])
    assert len(json.dumps(context,separators=(',',':')).encode())<=repo.CONTEXT_BYTES
    assert private.model_dump_json()==before
    assert source not in private.evidence_progress


def test_active_candidate_evidence_precedes_other_uninspected_source(tmp_path):
    _,_,_,repo,task=setup_repository(tmp_path)
    active=repo._read_source({'file_path':'service.py','start_line':2},task).evidence_ref
    newer=repo._read_source({'file_path':'service.py'},task).evidence_ref
    work=task.model_copy(update={'evidence_refs':[active]})
    context=repo.context(dict(task=work,private_state=AgentPrivateState(evidence_refs=[newer])))
    assert [page['evidence_ref'] for page in context['evidence']]==[active,newer]


def test_requested_offset_stays_first_without_acknowledging_or_widening_scope(tmp_path):
    _,_,_,repo,task=setup_repository(tmp_path)
    source=repo._read_source({'file_path':'service.py'},task).evidence_ref
    fact=repo._record(dict(tool='parse_ast',source_scope=task.files,data='x'*4000),work=task).evidence_ref
    private=AgentPrivateState(evidence_refs=[fact,source],evidence_cursors={fact:1500})
    context=repo.context(dict(task=task,private_state=private))
    assert context['evidence'][0]['evidence_ref']==fact
    assert context['evidence'][0]['offset']==1500
    assert not private.evidence_progress and not private.coverage.inspected_files
    outside=task.model_copy(update={'files':['other.py']})
    foreign=repo._read_source({'file_path':'other.py'},outside).evidence_ref
    private.evidence_refs.append(foreign)
    with pytest.raises(PermissionError):
        repo.context(dict(task=task,private_state=private))


@pytest.mark.asyncio
async def test_new_processed_tool_result_is_delivered_before_crowded_source(tmp_path):
    from devwatch.review.repository import RepositoryContext
    _,artifacts,_,original,task=setup_repository(tmp_path)
    source=''.join('value_%d = %r\n' % (i,'x'*80) for i in range(300))
    snapshot=artifacts.capture(owner='alice',files={'service.py':source})
    repo=RepositoryContext(artifacts,original.cache,snapshot.snapshot_id,owner='alice')
    refs=[repo._read_source({'file_path':'service.py','start_line':line,'end_line':line+79},task).evidence_ref
          for line in (1,81,161)]
    observed=await repo.tools().execute(task,AgentAction(kind='call_tool',tool='parse_ast',arguments={'file_path':'service.py'}))
    refs.append(observed.evidence_ref)
    private=AgentPrivateState(evidence_refs=refs,
        evidence_progress={ref:EvidenceProgress(processed=True) for ref in refs})
    context=repo.context(dict(task=task,private_state=private))
    assert context['evidence'][0]['evidence_ref']==observed.evidence_ref
    assert any(page['source_file']=='service.py' for page in context['evidence'])
    assert context['omitted_evidence_count']>0
    assert not any(receipt.delivered or receipt.inspected for receipt in private.evidence_progress.values())
