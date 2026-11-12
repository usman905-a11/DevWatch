import { describe, expect, it, vi } from 'vitest'
import fixture from './fixtures/canonical-wire.json'
import { DurableReviewClient } from '../review/durable-client'
import { ReviewSession } from '../review/review-session'

const json = (data: unknown) => new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })
const eof = () => new Response('', { headers: { 'Content-Type': 'text/event-stream' } })

describe('durable UI session', () => {
  it('does not create duplicate captures on simultaneous starts', async () => {
    let release!: (response: Response) => void
    let captures = 0
    const api = new DurableReviewClient('http://localhost:8000', '', async () => {
      captures++; return new Promise(resolve => { release = resolve })
    })
    const session = new ReviewSession(api)
    const first = session.start(fixture.files, fixture.snapshot.capture_coverage)
    await vi.waitFor(() => expect(captures).toBe(1))
    const second = session.start(fixture.files, fixture.snapshot.capture_coverage)
    await new Promise(resolve => setTimeout(resolve, 10))
    expect(captures).toBe(1)
    session.reset(); release(json(fixture.snapshot))
    await Promise.all([first, second])
  })
  it('preserves unknown submission intent and retries only on explicit action', async () => {
    const submissions: Array<{ body: string; key: string }> = []
    const api = new DurableReviewClient('http://localhost:8000', '', async (url, options) => {
      if (String(url).endsWith('/api/snapshots')) return json(fixture.snapshot)
      if (String(url).endsWith('/api/jobs')) {
        submissions.push({ body: String(options?.body), key: new Headers(options?.headers).get('Idempotency-Key')! })
        if (submissions.length === 1) throw new Error('connection dropped after acceptance')
        return json(fixture.job)
      }
      if (String(url).includes('/stream?')) return eof()
      if (String(url).includes('/report?')) return json(fixture.report)
      return json(fixture.job)
    })
    const session = new ReviewSession(api)
    await session.start(fixture.files, fixture.snapshot.capture_coverage)
    expect(session.getSnapshot().error).toMatch(/unknown/i)
    expect(session.getSnapshot().intent?.snapshot_id).toBe(fixture.snapshot.snapshot_id)
    expect(submissions).toHaveLength(1)
    const originalIntent = session.getSnapshot().intent
    session.reset()
    await session.attach('invalid-job-id')
    await session.start(fixture.files, fixture.snapshot.capture_coverage)
    expect(session.getSnapshot().intent).toEqual(originalIntent)
    expect(submissions).toHaveLength(1)
    await session.retrySubmission()
    await vi.waitFor(() => expect(session.getSnapshot().report?.snapshot_id).toBe(fixture.snapshot.snapshot_id))
    expect(submissions).toHaveLength(2)
    expect(submissions[1]).toEqual(submissions[0])
    expect(JSON.parse(submissions[0].body)).toEqual({ snapshot_id: fixture.snapshot.snapshot_id })
    session.dispose()
  })
  it('reopens an existing job and reads snapshot source without submission or live file reads', async () => {
    const paths: string[] = []
    const api = new DurableReviewClient('http://localhost:8000', '', async (url, options) => {
      paths.push(`${options?.method} ${url}`)
      if (String(url).endsWith('/snapshot')) return json(fixture.snapshot)
      if (String(url).includes('/source?')) return json(fixture.source)
      if (String(url).includes('/stream?')) return eof()
      if (String(url).includes('/report?')) return json(fixture.report)
      return json(fixture.job)
    })
    const session = new ReviewSession(api)
    await session.attach(fixture.job.job_id)
    await vi.waitFor(() => expect(session.getSnapshot().report?.uncertain_high_impact_candidates).toHaveLength(1))
    await session.openSource('service.py', 1, 2)
    expect(session.getSnapshot().source?.data).toContain('return items[0]')
    expect(session.getSnapshot().manifest?.entries['service.py'].line_count).toBe(2)
    expect(paths.every(path => path.startsWith('GET ') && !/\/fs\/|\/review/.test(path))).toBe(true)
    session.dispose()
  })
  it('disposing a viewer stops observation without canceling the job', async () => {
    const paths: string[] = []
    const api = new DurableReviewClient('http://localhost:8000', '', async url => {
      paths.push(String(url))
      if (String(url).endsWith('/snapshot')) return json(fixture.snapshot)
      if (String(url).includes('/stream?')) return new Response(new ReadableStream(), { headers: { 'Content-Type': 'text/event-stream' } })
      return json({ ...fixture.job, status: 'running' })
    })
    const session = new ReviewSession(api)
    await session.attach(fixture.job.job_id)
    session.dispose()
    expect(paths.some(path => path.endsWith('/cancel'))).toBe(false)
  })
  it('invalidating a pending capture prevents stale submission', async () => {
    let release!: (response: Response) => void
    const paths: string[] = []
    const api = new DurableReviewClient('http://localhost:8000', '', async url => {
      paths.push(String(url)); return new Promise(resolve => { release = resolve })
    })
    const session = new ReviewSession(api)
    const pending = session.start(fixture.files, fixture.snapshot.capture_coverage)
    await vi.waitFor(() => expect(paths).toHaveLength(1))
    session.reset()
    release(json(fixture.snapshot))
    await pending
    expect(paths).toHaveLength(1)
    expect(session.getSnapshot().job).toBeNull()
    expect(session.getSnapshot().intent).toBeNull()
  })
  it('only explicit cancellation sends a cancel request', async () => {
    const paths: string[] = []
    const api = new DurableReviewClient('http://localhost:8000', '', async url => {
      paths.push(String(url))
      if (String(url).endsWith('/snapshot')) return json(fixture.snapshot)
      if (String(url).includes('/stream?')) return new Response(new ReadableStream(), { headers: { 'Content-Type': 'text/event-stream' } })
      return json({ ...fixture.job, status: String(url).endsWith('/cancel') ? 'cancelled' : 'running' })
    })
    const session = new ReviewSession(api)
    await session.attach(fixture.job.job_id)
    await session.cancel()
    expect(session.getSnapshot().job?.status).toBe('cancelled')
    expect(paths.filter(path => path.endsWith('/cancel'))).toHaveLength(1)
    session.dispose()
  })
  it('retains RUNNING steps across >200 deltas and reconciles RUNNING steps on terminal job status', async () => {
    const jobId = fixture.job.job_id
    const basePayload = {
      status: 'RUNNING',
      agent_id: 'bug_reliability',
      task_id: 'bug-1',
      tool: null,
      evidence_ref: null,
      error_code: null,
      duration_seconds: null,
      total_tokens: null,
    }
    const frames: string[] = []
    // Step 0 stays RUNNING while 210 deltas arrive on step 1
    const step0 = {
      event_id: 's0-0',
      job_id: jobId,
      sequence: 1,
      kind: 'step_update',
      timestamp: 1,
      payload: {
        ...basePayload,
        step_idx: 0,
        parent_step_idx: null,
        agent_name: 'bug_reliability',
        step_type: 'agent_run',
        step_status: 'RUNNING',
        delta_seq: 0,
        render_info: { title: 'Running bug_reliability' },
      },
    }
    frames.push(`id: 1\nevent: step_update\ndata: ${JSON.stringify(step0)}\n\n`)
    for (let d = 0; d < 205; d++) {
      const seq = d + 2
      const delta = {
        event_id: `s1-${d}`,
        job_id: jobId,
        sequence: seq,
        kind: 'step_update',
        timestamp: 1,
        payload: {
          ...basePayload,
          step_idx: 1,
          parent_step_idx: 0,
          agent_name: 'bug_reliability',
          step_type: 'run_command',
          step_status: 'RUNNING',
          delta_seq: d,
          render_info: d === 0 ? { title: 'Running pytest', command: 'pytest' } : { stdout_append: `out-${d}\n` },
        },
      }
      frames.push(`id: ${seq}\nevent: step_update\ndata: ${JSON.stringify(delta)}\n\n`)
    }
    const sseBody = frames.join('')
    let streamFetched = false
    const api = new DurableReviewClient('http://localhost:8000', '', async url => {
      if (String(url).endsWith('/snapshot')) return json(fixture.snapshot)
      if (String(url).includes('/stream?')) {
        streamFetched = true
        return new Response(sseBody, { headers: { 'Content-Type': 'text/event-stream' } })
      }
      if (String(url).includes('/report?')) return json(fixture.report)
      return json({ ...fixture.job, status: streamFetched ? 'failed' : 'running' })
    })
    const session = new ReviewSession(api)
    await session.attach(jobId)
    await vi.waitFor(() => expect(session.getSnapshot().job?.status).toBe('failed'))
    const steps = session.getSnapshot().steps
    expect(steps.map(s => s.stepIdx)).toEqual([0, 1])
    // Both steps were RUNNING when the stream ended and job became 'failed', so both reconcile to ERROR
    expect(steps[0].status).toBe('ERROR')
    expect(steps[0].errorDetails).toBe('Interrupted by job termination')
    expect(steps[1].status).toBe('ERROR')
    expect(steps[1].stdout).toContain('out-1\n')
    expect(steps[1].stdout).toContain('out-204\n')
    session.dispose()
  })
})
