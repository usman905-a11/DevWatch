/** Public report audit from an actual canonical backend job. */
import { expect, it } from 'vitest'
import current from './fixtures/m20-wire.json'
import legacy from './fixtures/canonical-wire.json'
import { parseReport } from '../review/wire'

it('accepts the additive verification audit and contributing specialist provenance', () => {
  const parsed = parseReport(current.report, current.snapshot_id)
  expect(parsed).toMatchObject({ verification_audit: {
    decisions: [{ verdict: 'uncertain', causal_review: { assessments: [
      { field: 'title', status: 'supported' }, { field: 'description', status: 'supported' },
      { field: 'impact', status: 'uncertain' }, { field: 'remediation', status: 'supported' },
    ] } }], provenance: current.report.verification_audit.provenance,
  } })
})

it('continues to accept reports persisted before verification audits existed', () => {
  expect(parseReport(legacy.report, legacy.snapshot.snapshot_id).uncertain_high_impact_candidates).toHaveLength(1)
})
