import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { createElement } from 'react'
import { ReportPanel } from '../review/ReportPanel'
import fixture from './fixtures/canonical-wire.json'

describe('canonical report-only remediation', () => {
  it('preserves guidance and evidence without offering a source mutation', () => {
    const candidate = fixture.report.uncertain_high_impact_candidates[0]
    const html = renderToStaticMarkup(createElement(ReportPanel, { report: fixture.report as any, onSource: () => {} }))
    expect(html).toContain(candidate.remediation)
    expect(html).toContain(candidate.evidence_refs[0])
    expect(html).toContain('Reviewed source stays read-only')
    expect(html).not.toContain('Apply fix')
  })
})
