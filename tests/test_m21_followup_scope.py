"""The model receives runtime-admissible follow-up targets before proposing work."""
import asyncio
import json

import pytest

from tests.test_audit_evidence import engine
from tests.test_m20_verification import setup
from tests.verification_fixtures import decision


@pytest.mark.parametrize('targets', [set(), {'original-review'}])
def test_supplied_target_scope_preserves_review_without_optional_proposal_repairs(tmp_path, targets):
    repo, task, ref, claim = setup(tmp_path)
    runtime, provider = engine(repo, [])
    generate = provider.generate_completion
    async def complete(request):
        body=json.loads(request.prompt)
        allowed=body['followup_task_ids']
        assert allowed == sorted(targets)
        record=decision(claim,[ref],verdict='rejected',statuses={'impact':'unsupported'})
        followups=[dict(task_id=identity,question='Provide a narrower supported impact.',evidence_needed='Documented input domain.')
                   for identity in allowed]
        provider.responses=iter([dict(kind='submit_verification',inspected_evidence=[ref],
            payload=dict(decisions=[record],followup_requests=followups))])
        return await generate(request)
    provider.generate_completion=complete
    state=asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id,files=task.files,
        candidates={'f1':claim},review_tasks=targets))
    assert state['private_state'].stop_reason=='evidence_complete'
    assert state['output'].decisions[0].verdict=='rejected'
    assert {request.task_id for request in state['output'].followup_requests}==targets
    assert runtime.budget.ledger.task_schema_repairs == {}
    assert len(provider.requests)==1


def test_unknown_followup_target_still_cannot_enter_recorded_verification(tmp_path):
    repo, task, ref, claim=setup(tmp_path)
    action=dict(kind='submit_verification',inspected_evidence=[ref],payload=dict(decisions=[decision(claim,[ref])],
        followup_requests=[dict(task_id='not-authorized',question='Investigate.',evidence_needed='Source.')]))
    runtime,_=engine(repo,[action,action])
    state=asyncio.run(runtime.run_final(snapshot_id=repo.snapshot_id,files=task.files,
        candidates={'f1':claim},review_tasks={'original-review'}))
    assert state['verification'] is None
    assert state['private_state'].stop_reason=='invalid_schema'
