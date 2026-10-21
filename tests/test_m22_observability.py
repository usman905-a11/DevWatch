"""Real graph events and durable, metadata-only export ancestry."""
import asyncio
import json
import time
from uuid import uuid4

import pytest

from devwatch.review.budgets import BudgetManager
from devwatch.review.jobs import EventPayload, EventStore, PersistedEvent
from devwatch.review.observability import MetadataExporter
from devwatch.review.subgraphs import AgentSubgraphs, PermissionedTools
from devwatch.review.tool_errors import HINTS, ToolFailure
from tests.test_control_agents import MODELS
from tests.test_iterative_agents import ScriptedProvider, task
from tests.test_m8_observability import recorder


def test_nested_nodes_stream_before_provider_returns_and_close_on_cancel():
    async def scenario():
        entered, events = asyncio.Event(), []
        class Held:
            async def generate_completion(self, request):
                entered.set()
                await asyncio.Event().wait()
        runtime = AgentSubgraphs(Held(), PermissionedTools(), BudgetManager(), lambda state: {},
                                 models=MODELS, emit=recorder(events))
        work = asyncio.create_task(runtime.run_specialist(task()))
        await asyncio.wait_for(entered.wait(), 2)
        starts = [p for k, p in events if k == 'graph_node_started']
        assert len(starts) == 1
        assert starts[0]['node'] == 'investigate' and starts[0]['graph_scope'] == 'agent'
        assert starts[0]['task_id'] == task().task_id
        assert not [p for k, p in events if k == 'graph_node_completed']
        work.cancel()
        with pytest.raises(asyncio.CancelledError):
            await work
        ends = [p for k, p in events if k == 'graph_node_completed']
        assert len(ends) == 1 and ends[0]['operation_id'] == starts[0]['operation_id']
        assert ends[0]['run_id'] == starts[0]['run_id']
        assert ends[0]['outcome'] == 'cancelled' and ends[0]['duration_seconds'] >= 0
    asyncio.run(scenario())


@pytest.mark.parametrize('error,code', [(TimeoutError('private tool token'), 'tool_timeout'),
    (RuntimeError('private tool token'), 'execution_failed'),
    *[(ToolFailure(code, 'private tool token', recoverable=False), code) for code in HINTS]])
def test_failed_tool_preserves_diagnostic_without_breaking_event_schema(error, code):
    async def scenario():
        events, tools = [], PermissionedTools()
        async def broken(*args):
            raise error
        tools.register('parse_ast', broken)
        provider = ScriptedProvider([dict(kind='call_tool', tool='parse_ast', arguments={'file_path': 'service.py'})])
        output = await AgentSubgraphs(provider, tools, BudgetManager(), lambda state: {},
            models=MODELS, emit=recorder(events)).run_specialist(task())
        failed = [p for k, p in events if k == 'tool_result']
        assert len(failed) == 1 and failed[0]['outcome'] == 'failed' and failed[0]['error_code'] == code
        assert output['private_state'].tool_diagnostics
        assert 'private tool token' not in json.dumps(events)
    asyncio.run(scenario())


def test_completed_review_records_root_and_nested_node_transitions(tmp_path):
    from devwatch.review.contracts import ModelTier
    from devwatch.review.jobs import DurableJobManager
    from devwatch.review.stores import RepoCache
    from devwatch.review.workflow import CanonicalReviewExecutor
    from tests.test_canonical_workflow import ReviewProvider, stores
    async def scenario():
        layout, artifacts, snapshot, jobs, events = stores(tmp_path)
        provider = ReviewProvider()
        executor = CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events,
            provider, models={tier: tier.value for tier in ModelTier})
        manager = DurableJobManager(jobs, events, executor)
        try:
            job = await manager.submit(owner='alice', request={'snapshot_id': snapshot.snapshot_id}, idempotency_key='m22')
            assert (await manager.wait(job.job_id, owner='alice')).status == 'completed'
            timeline = events.replay(job.job_id)
            starts = [e for e in timeline if e.kind == 'graph_node_started']
            ends = [e for e in timeline if e.kind == 'graph_node_completed']
            assert len(starts) == len(ends) and len(starts) > 11
            assert len({e.payload.operation_id for e in starts}) == len(starts)
            assert {e.payload.operation_id for e in starts} == {e.payload.operation_id for e in ends}
            root = [e.payload.node for e in starts if e.payload.graph_scope == 'review']
            assert root == ['repository_intelligence', 'deterministic_analysis', 'change_analyzer',
                'planner_agent', 'context_manager', 'budget_manager', 'deterministic_router',
                'specialist_subgraphs', 'shared_blackboard', 'structural_evidence_gate', 'completion_workflow']
            assert all(e.payload.outcome == 'succeeded' for e in ends)
            assert len(provider.requests) == 4
            assert all('return items[0]' not in e.model_dump_json() for e in timeline)
        finally:
            await manager.close()
    asyncio.run(scenario())


def test_export_rebuilds_review_and_agent_hierarchy_after_exporter_restart(tmp_path):
    store, calls = EventStore(tmp_path / 'events.sqlite'), []
    job, run = uuid4().hex, uuid4().hex
    events = []
    for sequence, (kind, payload) in enumerate([
        ('job_queued', {}), ('agent_started', dict(run_id=run, task_id='private-task')),
        ('model_call_completed', dict(run_id=run, operation_id=uuid4().hex, outcome='failed',
            error_code='provider_timeout', task_id='private-task', evidence_ref='private-evidence')),
        ('agent_completed', dict(run_id=run, outcome='failed'))], 1):
        event = PersistedEvent(event_id=uuid4().hex, job_id=job, sequence=sequence, kind=kind,
            payload=EventPayload(**payload), timestamp=time.time() + sequence)
        store.append(event)
        events.append(event)
    class Client:
        def create_run(self, **kwargs):
            calls.append(kwargs)
    async def scenario():
        assert await MetadataExporter(store, client=Client()).export_once(limit=2) == 2
        reopened = EventStore(store.path)
        assert await MetadataExporter(reopened, client=Client()).export_once(limit=2) == 2
        assert await MetadataExporter(reopened, client=Client()).export_once() == 0
    asyncio.run(scenario())
    root, agent, model, completed = calls
    assert root['trace_id'] == root['id']
    assert agent['parent_run_id'] == root['id']
    assert model['parent_run_id'] == agent['id'] == completed['parent_run_id']
    assert all(c['trace_id'] == root['id'] for c in calls)
    assert model['dotted_order'].startswith(agent['dotted_order'] + '.')
    assert model['error'] == 'provider_timeout'
    assert all(c['inputs'] == c['outputs'] == {} for c in calls)
    encoded = json.dumps(calls, default=str)
    assert job not in encoded and 'private-task' not in encoded and 'private-evidence' not in encoded


def test_resume_preserves_nested_progress_and_trace_root_without_repeating_paid_work(tmp_path):
    from devwatch.review.contracts import ModelTier
    from devwatch.review.jobs import DurableJobManager
    from devwatch.review.stores import RepoCache
    from devwatch.review.workflow import CanonicalReviewExecutor
    from tests.assembly_fixtures import held_assembly
    from tests.test_canonical_workflow import ReviewProvider, stores
    async def scenario():
        layout, artifacts, snapshot, jobs, events = stores(tmp_path)
        entered, first = asyncio.Event(), ReviewProvider()
        def executor(provider):
            return CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events,
                provider, models={tier: tier.value for tier in ModelTier})
        initial = executor(first)
        manager = DurableJobManager(jobs, events, initial)
        with held_assembly(first, entered):
            job = await manager.submit(owner='alice', request={'snapshot_id': snapshot.snapshot_id}, idempotency_key='resume')
            await asyncio.wait_for(entered.wait(), 10)
            await manager.close()
        before = jobs.get(job.job_id, owner='alice')
        assert before.status == 'interrupted'
        prefix = events.replay(job.job_id)
        assert any(e.kind == 'graph_node_completed' and e.payload.outcome == 'cancelled' for e in prefix)
        second = ReviewProvider()
        resumed_executor = executor(second)
        resumed = DurableJobManager(jobs, events, resumed_executor)
        try:
            await resumed.resume(job.job_id, owner='alice')
            result = await resumed.wait(job.job_id, owner='alice')
            assert result.status == 'completed' and second.requests == []
            assert result.ledger.total_tokens == before.ledger.total_tokens
            timeline = events.replay(job.job_id)
            assert timeline[:len(prefix)] == prefix
            assert [e.sequence for e in timeline] == list(range(1, len(timeline) + 1))
            assert sum(e.kind == 'job_queued' for e in timeline) == 2  # explicit resume has its own queued event
            roots = {events.trace_ancestors(e)[0].event_id for e in timeline}
            assert roots == {prefix[0].event_id}
            final_checkpoints = []
            with initial.checkpoints._transaction() as db:
                final_checkpoints = list(db.execute('SELECT state FROM agent_progress'))
            states = [json.loads(row[0]) for row in final_checkpoints]
            observations = [o for state in states for o in state.get('provider_observations', [])]
            assert len(observations) == len(first.requests) == 4
            assert all(o['status'] == 'returned' and o['charged_tokens'] == 15 for o in observations)
        finally:
            await resumed.close()
    asyncio.run(scenario())


def test_root_failure_records_safe_node_diagnostic(tmp_path, monkeypatch):
    from devwatch.review.contracts import ModelTier
    from devwatch.review.jobs import DurableJobManager
    from devwatch.review.repository import RepositoryContext
    from devwatch.review.stores import RepoCache
    from devwatch.review.workflow import CanonicalReviewExecutor
    from tests.test_canonical_workflow import ReviewProvider, stores
    def fail(repository):
        raise RuntimeError('private source token')
    monkeypatch.setattr(RepositoryContext, 'analyze', fail)
    async def scenario():
        layout, artifacts, snapshot, jobs, events = stores(tmp_path)
        provider = ReviewProvider()
        manager = DurableJobManager(jobs, events, CanonicalReviewExecutor(layout, artifacts,
            RepoCache(layout.repo_cache), jobs, events, provider, models={tier: tier.value for tier in ModelTier}))
        try:
            job = await manager.submit(owner='alice', request={'snapshot_id': snapshot.snapshot_id}, idempotency_key='failure')
            assert (await manager.wait(job.job_id, owner='alice')).status == 'failed'
            timeline = events.replay(job.job_id)
            ends = [e.payload for e in timeline if e.kind == 'graph_node_completed']
            assert len(ends) == 1 and ends[0].node == 'repository_intelligence'
            assert ends[0].outcome == 'failed' and ends[0].error_code == 'execution_failed'
            assert provider.requests == []
            assert 'private source token' not in json.dumps([e.model_dump(mode='json') for e in timeline])
        finally:
            await manager.close()
    asyncio.run(scenario())


def test_websocket_streams_nested_node_start_and_replays_after_disconnect(tmp_path):
    import threading
    from fastapi.testclient import TestClient
    from tests.test_canonical_workflow import ReviewProvider
    from tests.test_review_service import ALICE, app, completed, submit
    entered, release = threading.Event(), threading.Event()
    class Held(ReviewProvider):
        async def generate_completion(self, request):
            if json.loads(request.prompt)['task']['agent_id'] == 'logic_correctness':
                entered.set()
                while not release.is_set():
                    await asyncio.sleep(.01)
            return await super().generate_completion(request)
    with TestClient(app(tmp_path, Held())) as client:
        identity, _ = submit(client)
        assert entered.wait(5)
        try:
            with client.websocket_connect(f'/api/jobs/{identity}/ws', headers=ALICE) as socket:
                observed = []
                while not observed or not (observed[-1]['kind'] == 'model_call_started'
                        and observed[-1]['payload']['task_id'] == 'logic-1'):
                    observed.append(socket.receive_json())
            nested = [e for e in observed if e['kind'] == 'graph_node_started'
                and e['payload']['task_id'] == 'logic-1']
            assert len(nested) == 1 and nested[0]['payload']['node'] == 'investigate'
            assert not [e for e in observed if e['kind'] == 'graph_node_completed'
                and e['payload']['operation_id'] == nested[0]['payload']['operation_id']]
            cursor = observed[-1]['sequence']
        finally:
            release.set()
        assert completed(client, identity)['status'] == 'completed'
        replay = client.get(f'/api/jobs/{identity}/events?after={cursor}&limit=1000', headers=ALICE).json()['events']
        sse = client.get(f'/api/jobs/{identity}/stream', headers={**ALICE, 'Last-Event-ID': str(cursor)})
        assert [json.loads(line[6:]) for line in sse.text.splitlines() if line.startswith('data: ')] == replay
        assert any(e['kind'] == 'graph_node_completed'
            and e['payload']['operation_id'] == nested[0]['payload']['operation_id'] for e in replay)


def test_cancellation_drains_synchronous_node_before_publishing_completion():
    import threading
    from devwatch.review.observability import observed_node
    entered, release, drained = threading.Event(), threading.Event(), threading.Event()
    events = []
    def node(state):
        entered.set()
        assert release.wait(5)
        drained.set()
        return {}
    def emit(kind, state, **payload):
        events.append((kind, payload))
    async def scenario():
        work = asyncio.create_task(observed_node('repository_intelligence', node, emit, scope='review')({}))
        while not entered.is_set():
            await asyncio.sleep(.01)
        work.cancel()
        await asyncio.sleep(.03)
        assert not work.done() and not drained.is_set() and len(events) == 1
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await work
        assert drained.is_set() and events[-1][1]['outcome'] == 'cancelled'
    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_installed_langsmith_sdk_serializes_hierarchy_without_private_content(tmp_path, monkeypatch):
    import requests
    from langsmith import Client
    sent = []
    def send(session, request, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response._content = b'{}'
        response.request = request
        if request.method == 'POST':
            sent.append(json.loads(request.body))
        return response
    monkeypatch.setattr(requests.Session, 'send', send)
    store = EventStore(tmp_path / 'events.sqlite')
    job = uuid4().hex
    for sequence, kind in enumerate(('job_queued', 'graph_node_completed'), 1):
        store.append(PersistedEvent(event_id=uuid4().hex, job_id=job, sequence=sequence, kind=kind,
            payload=EventPayload(task_id='private-task', node='investigate' if sequence == 2 else None), timestamp=time.time()))
    client = Client(api_url='http://localhost:1984', api_key='synthetic-sdk-test', auto_batch_tracing=False,
        hide_inputs=True, hide_outputs=True, omit_traced_runtime_info=True, disable_prompt_cache=True)
    try:
        assert asyncio.run(MetadataExporter(store, client=client).export_once()) == 2
    finally:
        client.close()
    assert len(sent) == 2
    assert sent[0]['trace_id'] == sent[0]['id']
    assert sent[1]['parent_run_id'] == sent[0]['id']
    assert sent[1]['dotted_order'].startswith(sent[0]['dotted_order'] + '.')
    assert all(row['inputs'] == row['outputs'] == {} for row in sent)
    assert job not in json.dumps(sent) and 'private-task' not in json.dumps(sent)
