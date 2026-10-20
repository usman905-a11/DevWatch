"""Presentation follows trusted command/owner grants; handlers still enforce them."""
import sys

import pytest

from devwatch.review.contracts import AgentAction, AgentId, AgentPrivateState
from devwatch.review.database_tools import DatabasePolicy, DatabaseTools
from devwatch.review.tool_runtime import TrustedCommand, TrustedToolRuntime
from tests.test_m15_database import configured
from tests.test_trusted_runtime import setup


def selected(tools,repo,task):
    ref=repo._read_source({'file_path':task.files[0]},task).evidence_ref
    state=dict(task=task,private_state=AgentPrivateState(evidence_refs=[ref]))
    catalogue,metrics=tools.for_model(state,repo.context(state))
    return {tool['name'] for tool in catalogue},metrics


@pytest.mark.asyncio
async def test_only_scope_approved_commands_are_advertised_and_effects_still_require_scope(tmp_path):
    _,_,repo,jobs,job,task=setup(tmp_path,"print('approved')\n")
    commands=(TrustedCommand(command_id='probe',tool='run_tests',argv=(sys.executable,'probe.py'),files=('probe.py',)),
              TrustedCommand(command_id='outside',tool='lint',argv=(sys.executable,'outside.py'),files=('outside.py',)))
    runtime=TrustedToolRuntime(repo,jobs,job,commands=commands)
    tools=repo.tools(runtime)
    names,_=selected(tools,repo,task)
    assert 'run_tests' in names
    assert not {'lint','type_check','run_command'}.intersection(names)
    with pytest.raises(PermissionError):
        await tools.execute(task,AgentAction(kind='call_tool',tool='lint',arguments={'command_id':'outside'}))
    assert runtime.active_processes==0
    observation=await tools.execute(task,AgentAction(kind='call_tool',tool='run_tests',arguments={'command_id':'probe'}))
    assert repo.evidence(observation.evidence_ref)['data']['exit_code']==0
    assert runtime.active_processes==0
    runtime.commands.clear()
    assert 'run_tests' not in selected(tools,repo,task)[0]
    with pytest.raises(PermissionError):
        await tools.execute(task,AgentAction(kind='call_tool',tool='run_tests',arguments={'command_id':'probe'}))


@pytest.mark.asyncio
async def test_database_tool_visibility_tracks_owner_grants_and_forced_calls_stay_denied(tmp_path):
    repo,granted,task=configured(tmp_path)
    policy=next(iter(granted.policies.values()))
    denied=DatabaseTools(repo,granted.job,policies=(DatabasePolicy(database_id='fixture',path=policy.path,owners={'bob'}),))
    hidden=repo.tools(database_runtime=denied)
    names,_=selected(hidden,repo,task)
    assert not {'db_analyze','query_analyze'}.intersection(names)
    with pytest.raises(PermissionError):
        await hidden.execute(task,AgentAction(kind='call_tool',tool='db_analyze',arguments={'database_id':'fixture'}))
    visible=repo.tools(database_runtime=granted)
    names,_=selected(visible,repo,task)
    assert {'db_analyze','query_analyze'}.issubset(names)
    observation=await visible.execute(task,AgentAction(kind='call_tool',tool='db_analyze',arguments={'database_id':'fixture'}))
    assert repo.evidence(observation.evidence_ref)['data']['tables'][0]['name']=='items'


@pytest.mark.asyncio
async def test_measurement_tool_requires_operator_and_runtime_grants_and_real_measurement(tmp_path):
    _,_,repo,jobs,job,task=setup(tmp_path,"print('measured')\n")
    task=task.model_copy(update={'agent_id':AgentId.PERFORMANCE_SCALABILITY})
    command=TrustedCommand(command_id='probe',tool='benchmark',argv=(sys.executable,'probe.py'),
                           files=('probe.py',),produces_measurement_artifact=True)
    runtime=TrustedToolRuntime(repo,jobs,job,commands=(command,))
    tools=repo.tools(runtime)
    assert 'write_artifact' not in selected(tools,repo,task)[0]
    tools.grant_measurement_artifact(task)
    assert {'write_artifact','benchmark'}.issubset(selected(tools,repo,task)[0])
    ref=repo._read_source({'file_path':'probe.py'},task).evidence_ref
    with pytest.raises(PermissionError):
        await tools.execute(task,AgentAction(kind='call_tool',tool='write_artifact',arguments={'evidence_ref':ref}))
    measured=await tools.execute(task,AgentAction(kind='call_tool',tool='benchmark',arguments={'command_id':'probe'}))
    stored=await tools.execute(task,AgentAction(kind='call_tool',tool='write_artifact',arguments={'evidence_ref':measured.evidence_ref}))
    assert repo.evidence(stored.evidence_ref)['data']['artifact_ref'].startswith('measurement-')
    runtime.commands.clear()
    assert 'write_artifact' not in selected(tools,repo,task)[0]
