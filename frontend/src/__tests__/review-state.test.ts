import { describe, expect, it } from 'vitest'
import { mapReviewReport, appendProgressStep } from '../hooks/useCodeReview'
import { ReviewReport } from '../types'

const report: ReviewReport = {
  target_path: 'app.py',
  summary: '# Partial review',
  total_issues: 1,
  critical_count: 0,
  high_count: 1,
  medium_count: 0,
  low_count: 0,
  issues: [{
    finding_id: 'confirmed-1',
    file_path: 'app.py',
    line_number: 2,
    severity: 'HIGH',
    category: 'Security',
    title: 'Confirmed issue',
    description: 'Verified source issue',
    suggestion: 'Use safe input',
  }],
  manual_review_candidates: [{
    finding_id: 'manual-1',
    file_path: 'auth.py',
    line_number: 3,
    severity: 'HIGH',
    category: 'Security',
    title: 'Possible bypass',
    description: 'Requires human review',
    suggestion: 'Inspect policy',
  }],
  metrics: { partial: true },
}

describe('review presentation data', () => {
  it('keeps confirmed and manual candidates separate and exposes partial status', () => {
    const view = mapReviewReport(report)
    expect(view.findings.map((finding) => finding.id)).toEqual(['confirmed-1'])
    expect(view.manualReviewCandidates.map((finding) => finding.id)).toEqual(['manual-1'])
    expect(view.partial).toBe(true)
  })

  it('retains only recent progress events', () => {
    const steps = Array.from({ length: 30 }, (_, index) => ({
      agent_name: 'planner',
      status: 'RUNNING' as const,
      message: `step ${index}`,
    }))
    const retained = steps.reduce(appendProgressStep, [])
    expect(retained).toHaveLength(20)
    expect(retained[0].message).toBe('step 10')
    expect(retained[19].message).toBe('step 29')
  })
})
