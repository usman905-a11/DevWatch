"""Larger reviews fit existing token ceilings without losing inspection gates."""
import json

import pytest

from devwatch.review.budgets import BudgetManager
from devwatch.review.contracts import AgentId, AgentPrivateState, AgentWorkItem, ModelTier, ReviewTask
from devwatch.review.subgraphs import AgentSubgraphs, PermissionedTools
from tests.test_iterative_agents import ScriptedProvider


@pytest.mark.parametrize('role', [AgentId.LOGIC_CORRECTNESS, AgentId.SYNTHESIZER_VERIFIER])
def test_nonplanner_response_reservation_fits_remaining_role_allowance(role):
    budget = BudgetManager()
    runtime = AgentSubgraphs(ScriptedProvider([]), PermissionedTools(), budget, lambda state: {},
                            models={tier:tier.value for tier in ModelTier})
    work = AgentWorkItem if role == AgentId.SYNTHESIZER_VERIFIER else ReviewTask
    state = dict(task=work(task_id='work',agent_id=role,files=['subject.py'],focus='Check contract'),
                 private_state=AgentPrivateState(), snapshot_id='snapshot',
                 phase='verification' if role == AgentId.SYNTHESIZER_VERIFIER else 'investigation', candidates={})
    context = dict(evidence=[],scope=['subject.py'],snapshot_id='snapshot')
    prompt, _ = runtime._prepare_prompt(state, context, repair=False)
    from devwatch.review.contracts import AGENT_CONTRACTS
    framing = len(AGENT_CONTRACTS[role].system_prompt.encode()) + 512
    required = len(prompt.encode()) + framing
    ticket = budget.reserve_model(role, 50000-required-1024)
    budget.record_model(ticket,prompt_tokens=50000-required-1024,completion_tokens=0)
    prompt, output = runtime._prepare_prompt(state, context, repair=False)
    assert output == 1024
    assert len(prompt.encode()) + framing + output <= budget.model_allowance(role)
    assert json.loads(prompt)['result_schema']['additionalProperties'] is False
    assert budget.limits.specialist_tokens == budget.limits.final_agent_tokens == 50000


@pytest.mark.parametrize('partial', [False, True])
def test_bounded_source_batch_completes_three_files_without_fabricating_inspection(tmp_path, partial):
    import asyncio
    from devwatch.providers.base import LLMResponse, LLMUsage
    from devwatch.review.repository import RepositoryContext
    from devwatch.review.stores import ArtifactStore, RepoCache
    artifacts = ArtifactStore(tmp_path/'artifacts')
    manifest = artifacts.capture(owner='alice',files={'a.py':('A = 1\n' if not partial else 'A = '+repr('x'*6000)+'\n'),'b.py':'B = 2\n','c.py':'C = 3\n'})
    repo = RepositoryContext(artifacts,RepoCache(tmp_path/'cache.sqlite'),manifest.snapshot_id,owner='alice')
    task = ReviewTask(task_id='batch',agent_id=AgentId.LOGIC_CORRECTNESS,files=['a.py','b.py','c.py'],focus='Check constants')
    requests = []
    class Provider:
        async def generate_completion(self, request):
            body = json.loads(request.prompt)
            requests.append(body)
            if len(requests)==1:
                action = dict(kind='call_tool',tool='read_source',arguments=dict(file_path='a.py',additional_files=['b.py','c.py']))
            else:
                assert set(body['investigation']['remaining_files']) == {'a.py','b.py','c.py'}
                pages = body['selected_context']['evidence']
                assert {p['source_file'] for p in pages} == {'a.py','b.py','c.py'}
                action = dict(kind='submit_candidates',inspected_evidence=[p['evidence_ref'] for p in pages],
                    payload=dict(task_id='batch',agent_id='logic_correctness',candidates=[],coverage={},stop_reason='evidence_complete'))
            return LLMResponse(content=json.dumps(action),finish_reason='stop',model=request.model,provider='fixture',latency_ms=1,
                usage=LLMUsage(prompt_tokens=10,completion_tokens=5,total_tokens=15))
    runtime = AgentSubgraphs(Provider(),repo.tools(),BudgetManager(),repo.context,models={tier:tier.value for tier in ModelTier})
    state = asyncio.run(runtime.run_specialist(task))
    assert state['private_state'].stop_reason == ('evidence_incomplete' if partial else 'evidence_complete')
    assert set(state['output'].coverage.inspected_files) == ({'b.py','c.py'} if partial else {'a.py','b.py','c.py'})
    assert state['private_state'].tool_call_count == 1
    assert state['private_state'].iteration_count == 2
    assert len(state['private_state'].evidence_progress) == 3


def test_source_batch_denies_one_unassigned_path_before_calling_any_handler():
    import asyncio
    from devwatch.review.contracts import AgentAction
    from devwatch.review.subgraphs import ToolObservation
    tools = PermissionedTools()
    calls = []
    async def handler(arguments,task):
        calls.append(arguments)
        return ToolObservation(evidence_ref='never')
    tools.register('read_source',handler)
    task = ReviewTask(task_id='batch',agent_id=AgentId.LOGIC_CORRECTNESS,files=['a.py'],focus='Check constants')
    with pytest.raises(PermissionError):
        asyncio.run(tools.execute(task,AgentAction(kind='call_tool',tool='read_source',arguments={
            'file_path':'a.py','additional_files':['private.py']})))
    assert calls == []


@pytest.mark.parametrize('additional', [['b.py','c.py','d.py','e.py'], ['../private.py'], ['a.py'], ['b.py','b.py']])
def test_source_batch_rejects_oversize_traversal_and_duplicate_paths(additional):
    from devwatch.review.tool_catalogue import SourceArguments
    with pytest.raises(ValueError):
        SourceArguments.model_validate(dict(file_path='a.py',additional_files=additional))
