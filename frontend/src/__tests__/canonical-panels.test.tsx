import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import fixture from './fixtures/canonical-wire.json'
import { ReportPanel } from '../review/ReportPanel'
import { JobActivity } from '../review/JobActivity'
import { SnapshotSource } from '../review/SnapshotSource'
import { PersistedEvent } from '../review/wire'

describe('canonical review presentation', () => {
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
  it('uses actual snapshot line numbers and escapes source content', () => {
    const html = renderToStaticMarkup(<SnapshotSource source={{ ...fixture.source, start_line: 42, end_line: 42, data: '<script>alert(1)</script>' } as any}
      error={null} path="service.py" onRead={() => {}} />)
    expect(html).toContain('Line 42')
    expect(html).toContain('&lt;script&gt;')
    expect(html).not.toContain('<script>')
    expect(html).toContain('Read-only snapshot')
  })
})
