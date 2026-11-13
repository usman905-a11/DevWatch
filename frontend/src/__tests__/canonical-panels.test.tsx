import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import fixture from './fixtures/canonical-wire.json'
import { ReportPanel } from '../review/ReportPanel'
import { JobActivity } from '../review/JobActivity'
import { CodeEditor, detectMonacoLanguage } from '../components/CodeEditor'
import { ActivityEvent, PersistedEvent } from '../review/wire'

describe('canonical review presentation', () => {
  it('uses the completed response as the authoritative text after deltas', () => {
    const started: ActivityEvent = { version: 1, eventId: 'start', sequence: 1, timestamp: 1,
      runId: 'run', agentRunId: 'agent', activityId: 'response', type: 'activity.started',
      activityType: 'response', data: { agentId: 'planner' } }
    const delta: ActivityEvent = { ...started, eventId: 'delta', sequence: 2, type: 'activity.delta',
      data: { text: 'draft' } }
    const completed: ActivityEvent = { ...started, eventId: 'complete', sequence: 3,
      type: 'activity.completed', data: { text: 'accepted final text' } }
    const html = renderToStaticMarkup(<JobActivity events={[started, delta, completed]}
      job={null} connection="connected" />)
    expect(html).toContain('Planner')
    expect(html).toContain('accepted final text')
    expect(html).not.toContain('<pre class="activity-output">draft</pre>')
  })
  it('shows graph progress and completion outcomes in the existing activity panel', () => {
    const event: PersistedEvent = { ...fixture.events[0], kind: 'graph_node_completed',
      payload: { ...fixture.events[0].payload, status: null, agent_id: 'logic_correctness',
        task_id: 'logic-1', graph_scope: 'agent', node: 'execute_action', outcome: 'succeeded' } }
    const html = renderToStaticMarkup(<JobActivity events={[event]} job={null} connection="connected" />)
    expect(html).toContain('Node: execute_action')
    expect(html).toContain('Outcome: succeeded')
    expect(html).toContain('Task: logic-1')
  })
  it('keeps confirmed, uncertain and advisory outputs separate with explicit coverage', () => {
    const candidate = fixture.report.uncertain_high_impact_candidates[0]
    const report = { ...fixture.report, confirmed_defects: [{ ...candidate, kind: 'defect' as const, finding_id: 'confirmed', confidence: .9 }],
      advisories: [{ ...candidate, kind: 'advisory' as const, finding_id: 'advice' }] }
    const html = renderToStaticMarkup(<ReportPanel report={report as any} onSource={() => {}} />)
    expect(html).toContain('Confirmed defects (1)')
    expect(html).toContain('Uncertain high-impact candidates (1)')
    expect(html).toContain('Advisories (1)')
    expect(html).toContain('dist/generated.js')
    expect(html).toContain('excluded_source')
    expect(html).toContain(candidate.verification_rationale)
    expect(html).not.toContain('Apply fix')
  })
  it('displays all seven roles and persisted metadata without introducing extra AI agents', () => {
    const html = renderToStaticMarkup(<JobActivity events={fixture.events as any} job={fixture.job as any} connection="connected" />)
    for (const name of ['Planner', 'Bug &amp; Reliability', 'Logic &amp; Correctness', 'Code Quality &amp; Testability',
      'Architecture &amp; Security', 'Performance &amp; Scalability', 'Synthesizer / Verifier']) expect(html).toContain(name)
    expect(html).toContain('Total tokens')
    expect(html).not.toContain('Supervisor')
  })
  it('renders CodeEditor tabs and clear tooLarge / binary states with language detection', () => {
    expect(detectMonacoLanguage('src/app.tsx')).toBe('typescript')
    expect(detectMonacoLanguage('review/service.py')).toBe('python')
    const tooLargeHtml = renderToStaticMarkup(
      <CodeEditor
        tabs={[{
          path: 'big.log',
          loading: false,
          file: { path: 'big.log', size: 3_000_000, binary: false, tooLarge: true, maxBytes: 2_000_000, lineCount: null, content: null },
        }]}
        activePath="big.log"
        highlightRange={null}
        onSelectTab={() => {}}
        onCloseTab={() => {}}
      />,
    )
    expect(tooLargeHtml).toContain('File is too large to display in the editor')
    const binaryHtml = renderToStaticMarkup(
      <CodeEditor
        tabs={[{
          path: 'image.png',
          loading: false,
          file: { path: 'image.png', size: 1200, binary: true, tooLarge: false, maxBytes: 2_000_000, lineCount: null, content: null },
        }]}
        activePath="image.png"
        highlightRange={null}
        onSelectTab={() => {}}
        onCloseTab={() => {}}
      />,
    )
    expect(binaryHtml).toContain('Binary file cannot be displayed')
  })
  it('renders nested trajectory steps with terminal drawer, search match pill, planner row, and error callout', () => {
    const base = fixture.events[0]
    const stepEvents: PersistedEvent[] = [
      {
        ...base,
        event_id: 'st-0',
        sequence: 1,
        kind: 'step_update',
        payload: {
          ...base.payload,
          status: 'RUNNING',
          step_status: 'RUNNING',
          agent_id: 'bug_reliability',
          agent_name: 'bug_reliability',
          step_idx: 0,
          parent_step_idx: null,
          step_type: 'agent_run',
          delta_seq: 0,
          render_info: { title: 'Running bug_reliability (bug-1)', subtitle: 'bug-1' },
        },
      },
      {
        ...base,
        event_id: 'st-1-0',
        sequence: 2,
        kind: 'step_update',
        payload: {
          ...base.payload,
          status: 'DONE',
          step_status: 'DONE',
          agent_id: 'bug_reliability',
          agent_name: 'bug_reliability',
          step_idx: 1,
          parent_step_idx: 0,
          step_type: 'planner',
          delta_seq: 1,
          render_info: { title: 'Selected tool: code_search', duration_ms: 15 },
        },
      },
      {
        ...base,
        event_id: 'st-2-0',
        sequence: 3,
        kind: 'step_update',
        payload: {
          ...base.payload,
          status: 'DONE',
          step_status: 'DONE',
          agent_id: 'bug_reliability',
          agent_name: 'bug_reliability',
          step_idx: 2,
          parent_step_idx: 0,
          step_type: 'code_search',
          delta_seq: 1,
          render_info: {
            title: "Searching for 'compute'",
            query: 'compute',
            match_count: 3,
            files: ['service.py', 'utils.py'],
            duration_ms: 8,
            evidence_ref: 'evidence-' + 'a'.repeat(64),
          },
        },
      },
      {
        ...base,
        event_id: 'st-3-0',
        sequence: 4,
        kind: 'step_update',
        payload: {
          ...base.payload,
          status: 'ERROR',
          step_status: 'ERROR',
          agent_id: 'bug_reliability',
          agent_name: 'bug_reliability',
          step_idx: 3,
          parent_step_idx: 0,
          step_type: 'run_command',
          delta_seq: 1,
          render_info: {
            title: 'Running run_tests (pytest-unit)',
            command: 'pytest -q',
            stdout_append: '1 failed\n',
            stderr_append: 'AssertionError\n',
            exit_code: 1,
            truncated: true,
            duration_ms: 120,
          },
          error_details: 'Command exited with code 1',
        },
      },
    ]
    const html = renderToStaticMarkup(<JobActivity events={stepEvents} job={null} connection="connected" />)
    expect(html).toContain('Trajectory steps')
    expect(html).toContain('Selected tool: code_search')
    expect(html).toContain('Found 3 matches across 2 files')
    expect(html).toContain('$ pytest -q')
    expect(html).toContain('1 failed')
    expect(html).toContain('AssertionError')
    expect(html).toContain('Command exited with code 1')
    expect(html).toContain('Output truncated at 64KB')
  })
})
