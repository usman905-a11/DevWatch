import { afterEach, describe, expect, it, vi } from 'vitest'
import { DurableReviewClient } from '../review/durable-client'
import fixture from './fixtures/canonical-wire.json'

const jobId = 'b'.repeat(32)
const payload = { status: null, agent_id: 'planner', task_id: '__planner', tool: null,
  evidence_ref: null, error_code: null, duration_seconds: null, total_tokens: 15 }
const event = (sequence: number, kind = 'agent_started') => ({ event_id: 'e' + sequence,
  job_id: jobId, sequence, kind, payload, timestamp: 1 })
const frame = (value: ReturnType<typeof event>, separator = '\n') =>
  `id: ${value.sequence}${separator}event: ${value.kind}${separator}data: ${JSON.stringify(value)}${separator}${separator}`
function stream(text: string, cuts: number[] = []) {
  const bytes = new TextEncoder().encode(text)
  return new Response(new ReadableStream({ start(controller) {
    let offset = 0
    for (const size of [...cuts, bytes.length]) {
      controller.enqueue(bytes.slice(offset, offset + size)); offset += size
      if (offset >= bytes.length) break
    }
    controller.close()
  } }), { headers: { 'Content-Type': 'text/event-stream' } })
}
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers() })

async function events() { return import('../review/durable-events') }

describe('persistent authenticated event observation', () => {
  it('refreshes owned accounting during an open stream on budget updates', async () => {
    const { observeJob } = await events()
    let push!: ReadableStreamDefaultController<Uint8Array>
    const api = new DurableReviewClient('http://localhost:8000', '', async url => {
      if (String(url).includes('/stream?')) return new Response(new ReadableStream({ start(controller) { push = controller } }),
        { headers: { 'Content-Type': 'text/event-stream' } })
      return new Response(JSON.stringify({ ...fixture.job, job_id: jobId, status: 'running' }),
        { headers: { 'Content-Type': 'application/json' } })
    })
    let updated!: () => void
    const received = new Promise<void>(resolve => { updated = resolve })
    const subscription = observeJob(api, jobId, { onEvent: () => {}, onJob: value => {
      expect(value.status).toBe('running'); updated()
    } })
    await new Promise(resolve => setTimeout(resolve, 0))
    push.enqueue(new TextEncoder().encode(frame(event(1, 'budget_updated'))))
    await Promise.race([received, new Promise((_, reject) => setTimeout(() => reject(new Error('No live accounting refresh')), 100))])
    subscription.stop(); await subscription.finished
  })
  it.each(['onEvent', 'onJob', 'onReport'] as const)('stops while %s is pending without committing or publishing later', async phase => {
    const { observeJob } = await events()
    let complete!: () => void, entered!: () => void
    const pending = new Promise<void>(resolve => { complete = resolve })
    const ready = new Promise<void>(resolve => { entered = resolve })
    const callbacks: string[] = [], states: string[] = [], paths: string[] = []
    const api = new DurableReviewClient('http://localhost:8000', '', async url => {
      paths.push(String(url))
      if (String(url).includes('/stream?')) return stream(phase === 'onEvent' ? frame(event(1)) : '')
      const data = String(url).includes('/report?') ? fixture.report : fixture.job
      return new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })
    })
    const callback = (name: string) => { callbacks.push(name); if (name === phase) { entered(); return pending } }
    const subscription = observeJob(api, phase === 'onEvent' ? jobId : fixture.job.job_id, {
      onEvent: () => callback('onEvent'), onJob: () => callback('onJob'), onReport: () => callback('onReport'),
      onConnection: state => states.push(state), onError: error => { throw error } })
    await ready
    subscription.stop()
    const settled = await Promise.race([subscription.finished.then(() => true), new Promise(resolve => setTimeout(() => resolve(false), 50))])
    expect(settled).toBe(true)
    expect(states[states.length - 1]).toBe('disconnected')
    expect(subscription.cursor).toBe(0)
    const before = callbacks.slice()
    complete()
    await subscription.finished
    expect(callbacks).toEqual(before)
    expect(paths.every(path => !/cancel|resume/.test(path))).toBe(true)
  })

  it('deadline expiry escapes a pending callback and handles its late rejection', async () => {
    const { observeJob } = await events()
    vi.useFakeTimers()
    let reject!: (error: Error) => void, entered!: () => void
    const pending = new Promise<void>((_, fail) => { reject = fail })
    const ready = new Promise<void>(resolve => { entered = resolve })
    const states: string[] = []
    const api = new DurableReviewClient('http://localhost:8000', '', async () => stream(frame(event(1))))
    const subscription = observeJob(api, jobId, { onEvent: () => { entered(); return pending }, onConnection: state => states.push(state) })
    await ready
    let settled = false
    void subscription.finished.then(() => { settled = true })
    await vi.advanceTimersByTimeAsync(650000)
    expect(settled).toBe(true)
    expect(subscription.cursor).toBe(0)
    expect(states[states.length - 1]).toBe('disconnected')
    reject(new Error('late private callback failure'))
    await subscription.finished
  })
  it('decodes split UTF-8 and CR/LF frames without inventing partial events', async () => {
    const { SseParser } = await events()
    const parser = new SseParser()
    expect(parser.feed('id: 1\r')).toEqual([])
    expect(parser.feed('\nevent: agent_started\r\ndata: {"hello":"')).toEqual([])
    expect(parser.feed('世界"}\r\n\r\n')).toEqual([{ id: '1', kind: 'agent_started', data: '{"hello":"世界"}' }])
    expect(parser.feed('id: 2\nevent: agent_completed\ndata: {}')).toEqual([])
    parser.finish() // EOF without a blank line discards the incomplete event.
  })

  it('rejects mismatched job identity, unsafe cursors, raw payload and ninth agent', async () => {
    const { parseEvent } = await events()
    for (const bad of [{ ...event(1), job_id: 'a'.repeat(32) }, { ...event(1), sequence: Number.MAX_SAFE_INTEGER + 1 },
      { ...event(1), payload: { ...payload, tool_input: 'private source' } },
      { ...event(1), payload: { ...payload, agent_id: 'supervisor' } }]) {
      expect(() => parseEvent({ id: String(bad.sequence), kind: bad.kind, data: JSON.stringify(bad) }, jobId)).toThrow(/invalid/i)
    }
    expect(() => parseEvent({ id: '2', kind: 'agent_completed', data: JSON.stringify(event(1)) }, jobId)).toThrow(/invalid/i)
  })
  it('rejects trailing-newline wire values accepted by JavaScript end anchors', async () => {
    const { parseEvent } = await events()
    const bad = { ...event(1), payload: { ...payload, tool: 'read_source\n' } }
    expect(() => parseEvent({ id: '1', kind: bad.kind, data: JSON.stringify(bad) }, jobId)).toThrow(/invalid/i)
    const { identity } = await import('../review/wire')
    expect(() => identity(jobId + '\n')).toThrow(/invalid/i)
  })

  it('reconnects at last accepted cursor and deduplicates replay without resubmission', async () => {
    const { observeJob } = await events()
    const paths: string[] = [], cursors: string[] = [], seen: number[] = [], states: string[] = []
    const api = new DurableReviewClient('http://localhost:8000', 'private-key', async (url, options) => {
      paths.push(String(url)); cursors.push(new Headers(options?.headers).get('Last-Event-ID') || '')
      if (paths.length === 1) return stream(frame(event(1)))
      if (paths.length === 2) throw new Error('network reset private source') // Status could not be fetched.
      return stream(frame(event(1)) + frame(event(2)), [7, 12, 35])
    })
    let subscription: Awaited<ReturnType<typeof observeJob>>
    subscription = observeJob(api, jobId, { onEvent: value => { seen.push(value.sequence); if (value.sequence === 2) subscription.stop() },
      onConnection: state => states.push(state), onError: error => { throw error } }, { retryDelayMs: 1 })
    await subscription.finished
    expect(seen).toEqual([1, 2])
    expect(subscription.cursor).toBe(1) // Stop prevents acceptance of the pending event.
    expect(paths).toEqual([`http://localhost:8000/api/jobs/${jobId}/stream?after=0`,
      `http://localhost:8000/api/jobs/${jobId}`, `http://localhost:8000/api/jobs/${jobId}/stream?after=1`])
    expect(cursors).toEqual(['0', '', '1'])
    expect(states).toContain('reconnecting')
  })

  it('stopping observation aborts pending transport and makes no cancel request', async () => {
    const { observeJob } = await events()
    const paths: string[] = [], errors: Error[] = []
    let aborted = false
    const api = new DurableReviewClient('http://localhost:8000', '', (url, options) => new Promise((_, reject) => {
      paths.push(String(url)); options!.signal!.addEventListener('abort', () => { aborted = true; reject(new Error('aborted')) })
    }))
    const subscription = observeJob(api, jobId, { onEvent: () => {}, onError: error => errors.push(error) })
    subscription.stop()
    await subscription.finished
    expect(aborted).toBe(true)
    expect(paths).toEqual([`http://localhost:8000/api/jobs/${jobId}/stream?after=0`])
    expect(errors).toEqual([])
  })

  it('fails closed on malformed or unbounded frames, without retrying protocol failures', async () => {
    const { SseParser, observeJob } = await events()
    expect(() => new SseParser().feed('data: ' + 'x'.repeat(16385))).toThrow(/limit/i)
    let calls = 0
    const errors: Error[] = []
    const api = new DurableReviewClient('http://localhost:8000', '', async () => { calls++; return stream('id: 1\nevent: agent_started\ndata: private-source\n\n') })
    const subscription = observeJob(api, jobId, { onEvent: () => {}, onError: error => errors.push(error) })
    await subscription.finished
    expect(calls).toBe(1)
    expect(errors.length).toBe(1)
    expect(errors[0].message).not.toContain('private-source')
  })
})
