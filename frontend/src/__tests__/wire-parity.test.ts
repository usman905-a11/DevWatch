/** Fixtures come from actual canonical service/graph/stores, not legacy report adapters. */
import { describe, expect, it } from 'vitest'
import fixture from './fixtures/canonical-wire.json'
import { DurableReviewClient } from '../review/durable-client'
import { parseEvent } from '../review/durable-events'
import { parseJob, parseReport, parseSource } from '../review/wire'

describe('backend/browser canonical wire parity', () => {
  it('accepts additive runtime metadata while retaining old event payloads', () => {
    const original = fixture.events[0]
    const legacy = { ...original, payload: { status: original.payload.status, agent_id: original.payload.agent_id,
      task_id: original.payload.task_id, tool: original.payload.tool, evidence_ref: original.payload.evidence_ref,
      error_code: original.payload.error_code, duration_seconds: original.payload.duration_seconds,
      total_tokens: original.payload.total_tokens } }
    const old = parseEvent({ id: String(legacy.sequence), kind: legacy.kind, data: JSON.stringify(legacy) }, fixture.job.job_id)
    expect(old.kind).toBe('job_queued')
    const event = { ...original, kind: 'model_call_completed', payload: { ...original.payload,
      phase: 'investigation', iteration: 2, attempt: 1, operation_id: 'a'.repeat(32),
      outcome: 'succeeded', finish_reason: 'stop', total_tokens: 15 } }
    const parsed = parseEvent({ id: String(event.sequence), kind: event.kind, data: JSON.stringify(event) }, fixture.job.job_id)
    expect(parsed.payload.operation_id).toBe('a'.repeat(32))
    expect(parsed.payload.iteration).toBe(2)
    const invalid = { ...event, payload: { ...event.payload, attempt: -1 } }
    expect(() => parseEvent({ id: String(invalid.sequence), kind: invalid.kind, data: JSON.stringify(invalid) }, fixture.job.job_id)).toThrow()
  })
  it('preserves backend-valid failed task identities in partial reports', () => {
    const report = parseReport(fixture.failed_task_report, fixture.snapshot.snapshot_id)
    expect(report.coverage.failed).toEqual({ 'security.': 'tool_unavailable', con: 'tool_unavailable' })
    expect(report.uncertain_high_impact_candidates.length).toBe(1)
  })
  it('accepts bounded graph-node events and tool timeout diagnostics', () => {
    const original = fixture.events[0]
    const event = { ...original, kind: 'graph_node_completed', payload: { ...original.payload,
      node: 'execute_action', graph_scope: 'agent', operation_id: 'a'.repeat(32),
      task_id: 'logic-1', outcome: 'succeeded', error_code: 'tool_timeout' } }
    const parsed = parseEvent({ id: String(event.sequence), kind: event.kind, data: JSON.stringify(event) }, fixture.job.job_id)
    expect(parsed.payload.node).toBe('execute_action')
    expect(parsed.payload.error_code).toBe('tool_timeout')
    const invalid = { ...event, payload: { ...event.payload, node: 'private source content' } }
    expect(() => parseEvent({ id: String(invalid.sequence), kind: invalid.kind, data: JSON.stringify(invalid) }, fixture.job.job_id)).toThrow()
  })
  it('consumes actual finalized report and ownership-bound source schemas', () => {
    expect(parseJob(fixture.job).status).toBe('completed')
    const report = parseReport(fixture.report, fixture.snapshot.snapshot_id)
    expect(report.confirmed_defects).toEqual([])
    expect(report.uncertain_high_impact_candidates.length).toBe(1)
    expect(report.coverage.skipped['dist/generated.js']).toBe('excluded_source')
    expect(parseSource(fixture.source, fixture.snapshot.snapshot_id, 'service.py', 1, 2).data).toBe('def first(items):\n    return items[0]')
  })
  it('preserves all actual persisted event types and seven-role identities', () => {
    const decoded = fixture.events.map(event => parseEvent({ id: String(event.sequence), kind: event.kind, data: JSON.stringify(event) }, fixture.job.job_id))
    expect(decoded[0].kind).toBe('job_queued')
    expect(decoded[decoded.length - 1].kind).toBe('job_completed')
    expect(decoded.some(event => event.payload.agent_id === 'synthesizer_verifier')).toBe(true)
  })
  it('accepts valid Unicode task IDs with backend character-count semantics', () => {
    const event = fixture.unicode_event
    const parsed = parseEvent({ id: String(event.sequence), kind: event.kind, data: JSON.stringify(event) }, fixture.job.job_id)
    expect(parsed.payload.task_id).toBe('任务.' + '𠀀'.repeat(120))
  })
  it('checks real manifest hashes with Python Unicode key ordering', async () => {
    const api = new DurableReviewClient('http://localhost:8000', '', async () =>
      new Response(JSON.stringify(fixture.snapshot), { headers: { 'Content-Type': 'application/json' } }))
    const snapshot = await api.capture(fixture.files, fixture.snapshot.capture_coverage)
    expect(snapshot.entries['😀.py'].byte_count).toBe(5)
    expect(snapshot.content_hash).toBe(fixture.snapshot.content_hash)
  })
})
