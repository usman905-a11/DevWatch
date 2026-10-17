import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import AgentPanel, { Finding } from '../components/AgentPanel'

const candidate: Finding = {
  id: 'manual-1',
  agent: 'security',
  severity: 'high',
  title: 'Possible permission bypass',
  description: 'Needs a closer look.',
  fileId: 'auth.py',
  fileName: 'auth.py',
  line: 12,
  suggestion: 'Check the permission branch.',
  replacement_code: 'unsafe_mutation()',
}

describe('report-only review panel', () => {
  it('shows progress details while the review runs', () => {
    const markup = renderToStaticMarkup(
      <AgentPanel
        analysisRunning
        analysisComplete={false}
        onFindingClick={() => {}}
        findings={[]}
        manualReviewCandidates={[]}
        progressSteps={[{
          agent_name: 'Planner Agent',
          status: 'RUNNING',
          message: 'Routing changed code',
          specialist: 'security',
          elapsed_ms: 1234,
        }]}
        reviewError={null}
        partial={false}
      />
    )
    expect(markup).toContain('Planner Agent')
    expect(markup).toContain('Routing changed code')
    expect(markup).toContain('security')
  })

  it('separates manual candidates and never offers a mutation action', () => {
    const markup = renderToStaticMarkup(
      <AgentPanel
        analysisRunning={false}
        analysisComplete
        onFindingClick={() => {}}
        findings={[]}
        manualReviewCandidates={[candidate]}
        progressSteps={[]}
        reviewError={null}
        partial
      />
    )
    expect(markup).toContain('Manual review')
    expect(markup).toContain('Possible permission bypass')
    expect(markup).toContain('Partial review')
    expect(markup).toContain('Check the permission branch.')
    expect(markup).not.toContain('unsafe_mutation()')
    expect(markup).not.toContain('Suggested fix')
    expect(markup).not.toContain('Apply')
  })
})
