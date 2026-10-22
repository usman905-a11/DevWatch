import { expect, it } from 'vitest'
import fixture from './fixtures/m20-wire.json'
import { parseReport, type ReportDraft } from '../review/wire'

function report(): ReportDraft {
  const value: ReportDraft = structuredClone(fixture.report) as ReportDraft
  value.verification_audit!.arithmetic_checks = { f1: [{
    candidate_digest: 'a'.repeat(64), claim_index: 0, field: 'description',
    statement: 'For integers n in [3, 3] step 1: (n ^ (n - 1)) == 1.',
    result: { status: 'supported', checked_assignments: 1, counterexample: null,
      reason: 'entire_declared_domain_checked' },
  }] }
  return value
}

it('preserves independently checked mathematical scope in the public report', () => {
  const parsed = parseReport(report(), fixture.snapshot_id)
  expect(parsed.verification_audit?.arithmetic_checks?.f1[0].result).toEqual({
    status: 'supported', checked_assignments: 1, counterexample: null,
    reason: 'entire_declared_domain_checked',
  })
})

it('refuses malformed mathematical evidence instead of silently dropping it', () => {
  const value = report()
  value.verification_audit!.arithmetic_checks!.f1[0].result.checked_assignments = 4097
  expect(() => parseReport(value, fixture.snapshot_id)).toThrow()
})
