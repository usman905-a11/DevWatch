import asyncio
import json

import pytest

from devwatch.review.contracts import AGENT_CONTRACTS, AgentAction, AgentId, AgentWorkItem, ModelTier, ReviewTask
from devwatch.review.subgraphs import AgentSubgraphs
from devwatch.review.budgets import BudgetManager
from tests.test_repository_context import setup_repository
from tests.test_iterative_agents import ScriptedProvider


@pytest.mark.parametrize('agent', list(AgentId))
def test_catalogue_exposes_only_registered_role_tools_and_exact_arguments(tmp_path, agent):
    _, _, manifest, repo, _ = setup_repository(tmp_path)
    work = (AgentWorkItem if agent in {AgentId.PLANNER, AgentId.SYNTHESIZER_VERIFIER} else ReviewTask)(
        task_id='catalogue', agent_id=agent, files=['service.py'], focus='catalogue')
    tools = repo.tools()
    catalogue = tools.catalogue(work)
    names = {entry['name'] for entry in catalogue}
    assert names == AGENT_CONTRACTS[agent].allowed_tools.intersection(tools._handlers)
    source = next(entry for entry in catalogue if entry['name'] == 'read_source')
    assert source['arguments']['required'] == ['file_path']
    assert source['arguments']['additionalProperties'] is False
    assert source['arguments']['properties']['start_line']['minimum'] == 1
    assert source['description'] and source['output']
    provider = ScriptedProvider([{'kind': 'finish'}])
    engine = AgentSubgraphs(provider, tools, BudgetManager(), repo.context, models={t:t.value for t in ModelTier})
    async def run():
        if agent == AgentId.PLANNER:
            await engine.run_planner(snapshot_id=manifest.snapshot_id, files=work.files)
        elif agent == AgentId.SYNTHESIZER_VERIFIER:
            await engine.run_final(snapshot_id=manifest.snapshot_id, files=work.files, candidates={})
        else:
            await engine.run_specialist(work)
    asyncio.run(run())
    visible = json.loads(provider.requests[0].prompt)['tool_catalogue']
    expected = ({'read_source'} if agent not in {AgentId.PLANNER, AgentId.SYNTHESIZER_VERIFIER}
                else names - {'read_evidence'})
    assert visible == [entry for entry in catalogue if entry['name'] in expected]


@pytest.mark.parametrize('arguments', [
    {'file_path': 'service.py', 'start_line': True},
    {'file_path': 'service.py', 'start_line': '1'},
    {'file_path': 'service.py', 'surprise': 1}, {},
])
def test_catalogue_argument_validation_precedes_handler(tmp_path, arguments):
    _, _, _, repo, task = setup_repository(tmp_path)
    with pytest.raises(ValueError):
        asyncio.run(repo.tools().execute(task, AgentAction(kind='call_tool', tool='read_source', arguments=arguments)))
