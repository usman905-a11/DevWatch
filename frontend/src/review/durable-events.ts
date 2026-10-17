/** Authenticated, bounded SSE replay. Stopping observation never cancels execution. */
import { ConnectionError, DurableReviewClient } from './durable-client'
import { identity, JobView, PersistedEvent, ProtocolError, ReportDraft, validateWire } from './wire'

export interface SseFrame { id: string; kind: string; data: string }
export class SseParser {
  private line = ''
  private frame: SseFrame = { id: '', kind: '', data: '' }
  private data: string[] = []
  private skipLf = false
  private bytes = 0
  feed(text: string): SseFrame[] {
    const frames: SseFrame[] = []
    for (const character of text) {
      if (this.skipLf && character === '\n') { this.skipLf = false; continue }
      this.skipLf = false
      this.bytes += new TextEncoder().encode(character).byteLength
      if (this.bytes > 16384) throw new ProtocolError('Event frame byte limit exceeded')
      if (character === '\r' || character === '\n') {
        if (this.line === '') {
          if (this.data.length) frames.push({ ...this.frame, data: this.data.join('\n') })
          this.frame = { id: '', kind: '', data: '' }; this.data = []; this.bytes = 0
        } else if (!this.line.startsWith(':')) {
          const colon = this.line.indexOf(':')
          const field = colon === -1 ? this.line : this.line.slice(0, colon)
          let value = colon === -1 ? '' : this.line.slice(colon + 1)
          if (value.startsWith(' ')) value = value.slice(1)
          if (field === 'data') this.data.push(value)
          if (field === 'id') this.frame.id = value
          if (field === 'event') this.frame.kind = value
        }
        this.line = ''; this.skipLf = character === '\r'
      } else { this.line += character }
    }
    return frames
  }
  finish(): void { this.line = ''; this.data = []; this.frame = { id: '', kind: '', data: '' }; this.bytes = 0; this.skipLf = false }
}

export function parseEvent(frame: SseFrame, jobId: string): PersistedEvent {
  let data: unknown
  try { data = JSON.parse(frame.data) } catch { throw new ProtocolError() }
  const event = validateWire<PersistedEvent>('PersistedEvent', data)
  if (event.job_id !== jobId || !Number.isSafeInteger(event.sequence) || frame.id !== String(event.sequence)
    || frame.kind !== event.kind) throw new ProtocolError()
  return event
}

export interface JobObserver {
  onEvent(event: PersistedEvent): void | Promise<void>
  onJob?(job: JobView): void | Promise<void>
  onReport?(report: ReportDraft): void | Promise<void>
  onConnection?(state: 'connecting' | 'connected' | 'reconnecting' | 'disconnected'): void
  onError?(error: Error): void
}
export interface Observation { stop(): void; readonly cursor: number; readonly finished: Promise<void> }

export function observeJob(client: DurableReviewClient, jobId: string, observer: JobObserver,
  options: { after?: number; retryDelayMs?: number } = {}): Observation {
  identity(jobId)
  let cursor = options.after ?? 0
  const retryDelay = options.retryDelayMs ?? 250
  if (!Number.isSafeInteger(cursor) || cursor < 0 || !Number.isFinite(retryDelay) || retryDelay < 1 || retryDelay > 10000) throw new ProtocolError('Invalid replay options')
  const lifecycle = new AbortController()
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined
  const stop = () => { lifecycle.abort(); void reader?.cancel().catch(() => {}) }
  const totalTimer = setTimeout(stop, 650000)
  async function consume<T>(callback: (value: T) => void | Promise<void>, value: T): Promise<void> {
    lifecycle.signal.throwIfAborted()
    const pending = Promise.resolve(callback(value))
    await new Promise<void>((resolve, reject) => {
      const abort = () => { cleanup(); reject(new ConnectionError()) }
      const cleanup = () => lifecycle.signal.removeEventListener('abort', abort)
      // Keep both handlers attached after abort so late failures are consumed.
      pending.then(() => {
        cleanup()
        if (lifecycle.signal.aborted) reject(new ConnectionError()); else resolve()
      }, error => { cleanup(); reject(error) })
      lifecycle.signal.addEventListener('abort', abort, { once: true })
      if (lifecycle.signal.aborted) abort()
    })
  }
  async function run() {
    let totalBytes = 0
    let lastAccountingRefresh = -Infinity
    try {
      for (let attempt = 0; attempt <= 2 && !lifecycle.signal.aborted; attempt++) {
        const connection = new AbortController()
        const abort = () => connection.abort()
        lifecycle.signal.addEventListener('abort', abort, { once: true })
        let idleTimer: ReturnType<typeof setTimeout>
        const resetIdle = () => { clearTimeout(idleTimer); idleTimer = setTimeout(abort, 150000) }
        resetIdle()
        try {
          observer.onConnection?.(attempt ? 'reconnecting' : 'connecting')
          const response = await client.open(`/api/jobs/${jobId}/stream?after=${cursor}`, {
            method: 'GET', headers: { Accept: 'text/event-stream', 'Last-Event-ID': String(cursor) } }, connection.signal)
          if (response.headers.get('Content-Type')?.split(';')[0].trim() !== 'text/event-stream' || !response.body) throw new ProtocolError()
          observer.onConnection?.('connected')
          reader = response.body.getReader()
          const decoder = new TextDecoder('utf-8', { fatal: true }), parser = new SseParser()
          while (!lifecycle.signal.aborted) {
            let chunk: ReadableStreamReadResult<Uint8Array>
            try { chunk = await reader.read(); connection.signal.throwIfAborted() } catch { throw new ConnectionError() }
            if (chunk.done) { parser.finish(); break }
            totalBytes += chunk.value.byteLength
            if (totalBytes > 8000000) throw new ProtocolError('Event stream total byte limit exceeded')
            resetIdle()
            let decoded: string
            try { decoded = decoder.decode(chunk.value, { stream: true }) } catch { throw new ProtocolError() }
            for (const frame of parser.feed(decoded)) {
              const event = parseEvent(frame, jobId)
              if (event.sequence <= cursor) continue
              await consume(observer.onEvent, event)
              if (lifecycle.signal.aborted) return
              cursor = event.sequence
              if (event.kind === 'budget_updated' && observer.onJob && performance.now() - lastAccountingRefresh >= 1000) {
                const currentJob = await client.status(jobId, lifecycle.signal)
                await consume(observer.onJob, currentJob)
                lastAccountingRefresh = performance.now()
              }
            }
          }
          if (lifecycle.signal.aborted) return
          const job = await client.status(jobId, lifecycle.signal)
          if (observer.onJob) await consume(observer.onJob, job)
          if (lifecycle.signal.aborted) return
          if (job.status === 'completed') {
            if (observer.onReport) await consume(observer.onReport, await client.report(jobId, lifecycle.signal))
            return
          }
          if (!['queued', 'running'].includes(job.status)) return
          throw new ConnectionError()
        } catch (error) {
          if (lifecycle.signal.aborted) return
          if (!(error instanceof ConnectionError) || attempt === 2) throw error
          // GET-only replay, at the last consumer-accepted sequence. Never submit/resume/cancel.
        } finally {
          clearTimeout(idleTimer!)
          lifecycle.signal.removeEventListener('abort', abort)
          connection.abort()
          void reader?.cancel().catch(() => {}); reader = undefined
        }
        await new Promise<void>(resolve => {
          const abort = () => { clearTimeout(timer); resolve() }
          const timer = setTimeout(() => { lifecycle.signal.removeEventListener('abort', abort); resolve() }, retryDelay * (attempt + 1))
          lifecycle.signal.addEventListener('abort', abort, { once: true })
          if (lifecycle.signal.aborted) abort()
        })
      }
    } catch (error) {
      if (!lifecycle.signal.aborted) observer.onError?.(error instanceof ProtocolError || error instanceof ConnectionError
        ? error : new ProtocolError('Review observation failed'))
    } finally {
      clearTimeout(totalTimer)
      observer.onConnection?.('disconnected')
    }
  }
  return { stop, get cursor() { return cursor }, finished: run() }
}
