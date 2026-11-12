/** Authenticated, bounded SSE replay. Stopping observation never cancels execution. */
import { ConnectionError, DurableReviewClient } from './durable-client'
import {
  ActivityEvent,
  identity,
  JobStatus,
  JobView,
  PersistedEvent,
  ProtocolError,
  ReportDraft,
  StepStatus,
  StepType,
  StepUpdatePayload,
  StreamEvent,
  validateWire,
} from './wire'

const LIVE_STEP_OUTPUT_CAP_BYTES = 65536

export interface TrajectoryStep {
  stepIdx: number
  parentStepIdx: number | null
  agentName: string
  stepType: StepType
  status: StepStatus
  lastDeltaSeq: number
  title: string
  subtitle?: string
  command?: string
  stdout: string
  stderr: string
  truncated: boolean
  exitCode?: number
  files: string[]
  matchCount?: number
  query?: string
  durationMs?: number
  evidenceRef?: string
  errorDetails?: string | null
}

function appendBoundedStream(
  currentStdout: string,
  currentStderr: string,
  stdoutAppend?: string | null,
  stderrAppend?: string | null,
  alreadyTruncated = false,
): { stdout: string; stderr: string; truncated: boolean } {
  let stdout = currentStdout
  let stderr = currentStderr
  let truncated = alreadyTruncated
  const encoder = new TextEncoder()
  let usedBytes = encoder.encode(stdout).byteLength + encoder.encode(stderr).byteLength

  const appendChunk = (target: 'stdout' | 'stderr', chunk?: string | null) => {
    if (!chunk) return
    if (usedBytes >= LIVE_STEP_OUTPUT_CAP_BYTES) {
      truncated = true
      return
    }
    const chunkBytes = encoder.encode(chunk).byteLength
    if (usedBytes + chunkBytes <= LIVE_STEP_OUTPUT_CAP_BYTES) {
      if (target === 'stdout') stdout += chunk
      else stderr += chunk
      usedBytes += chunkBytes
    } else {
      const remaining = Math.max(0, LIVE_STEP_OUTPUT_CAP_BYTES - usedBytes)
      const slice = chunk.slice(0, remaining)
      if (target === 'stdout') stdout += slice
      else stderr += slice
      usedBytes = LIVE_STEP_OUTPUT_CAP_BYTES
      truncated = true
    }
  }

  appendChunk('stdout', stdoutAppend)
  appendChunk('stderr', stderrAppend)
  return { stdout, stderr, truncated }
}

export function applyStepUpdate(
  stepsByIdx: Map<number, TrajectoryStep>,
  payload: StepUpdatePayload,
  fallbackAgentName?: string | null,
): Map<number, TrajectoryStep> {
  const next = new Map(stepsByIdx)
  const existing = next.get(payload.step_idx)
  if (existing && payload.delta_seq <= existing.lastDeltaSeq) {
    return next
  }
  const info = payload.render_info ?? {}
  const appended = appendBoundedStream(
    existing?.stdout ?? '',
    existing?.stderr ?? '',
    info.stdout_append,
    info.stderr_append,
    Boolean(existing?.truncated || info.truncated || info.output_truncated),
  )
  const step: TrajectoryStep = {
    stepIdx: payload.step_idx,
    parentStepIdx: payload.parent_step_idx !== undefined ? payload.parent_step_idx : (existing?.parentStepIdx ?? null),
    agentName: payload.agent_name || info.agent_name || existing?.agentName || fallbackAgentName || 'review',
    stepType: payload.step_type ?? existing?.stepType ?? 'tool',
    status: payload.status ?? existing?.status ?? 'RUNNING',
    lastDeltaSeq: payload.delta_seq,
    title: info.title ?? existing?.title ?? payload.step_type,
    subtitle: info.subtitle ?? existing?.subtitle,
    command: info.command ?? existing?.command,
    stdout: appended.stdout,
    stderr: appended.stderr,
    truncated: appended.truncated,
    exitCode: info.exit_code !== undefined && info.exit_code !== null ? info.exit_code : existing?.exitCode,
    files: info.files ?? existing?.files ?? [],
    matchCount: info.match_count !== undefined && info.match_count !== null ? info.match_count : existing?.matchCount,
    query: info.query ?? existing?.query,
    durationMs: info.duration_ms !== undefined && info.duration_ms !== null ? info.duration_ms : existing?.durationMs,
    evidenceRef: info.evidence_ref ?? existing?.evidenceRef,
    errorDetails: payload.error_details !== undefined ? payload.error_details : existing?.errorDetails,
  }
  next.set(payload.step_idx, step)
  return next
}

export function pruneTrajectorySteps(
  stepsByIdx: Map<number, TrajectoryStep>,
  maxCompleted = 200,
): Map<number, TrajectoryStep> {
  const running: TrajectoryStep[] = []
  const completed: TrajectoryStep[] = []
  for (const step of [...stepsByIdx.values()].sort((a, b) => a.stepIdx - b.stepIdx)) {
    if (step.status === 'RUNNING') running.push(step)
    else completed.push(step)
  }
  const retainedCompleted = completed.slice(-maxCompleted)
  const next = new Map<number, TrajectoryStep>()
  for (const step of [...running, ...retainedCompleted].sort((a, b) => a.stepIdx - b.stepIdx)) {
    next.set(step.stepIdx, step)
  }
  return next
}

export function reconcileTerminalJobSteps(
  stepsByIdx: Map<number, TrajectoryStep>,
  jobStatus?: JobStatus | null,
): Map<number, TrajectoryStep> {
  if (!jobStatus || !['completed', 'failed', 'cancelled', 'interrupted'].includes(jobStatus)) {
    return stepsByIdx
  }
  let changed = false
  const next = new Map(stepsByIdx)
  for (const [idx, step] of next.entries()) {
    if (step.status === 'RUNNING') {
      changed = true
      next.set(idx, {
        ...step,
        status: 'ERROR',
        errorDetails: step.errorDetails || 'Interrupted by job termination',
      })
    }
  }
  return changed ? next : stepsByIdx
}

export function reduceTrajectorySteps(
  events: StreamEvent[],
  jobStatus?: JobStatus | null,
  maxCompleted = 200,
): TrajectoryStep[] {
  let map = new Map<number, TrajectoryStep>()
  for (const event of events) {
    if (!('kind' in event) || event.kind !== 'step_update') continue
    const p = event.payload
    if (p.step_idx == null || !p.step_type) continue
    const stepStatus = (p.step_status ?? (p.status as StepStatus | null) ?? 'RUNNING') as StepStatus
    map = applyStepUpdate(
      map,
      {
        step_idx: p.step_idx,
        parent_step_idx: p.parent_step_idx ?? null,
        agent_name: p.agent_name ?? p.agent_id ?? undefined,
        step_type: p.step_type,
        status: stepStatus,
        delta_seq: p.delta_seq ?? 0,
        render_info: p.render_info ?? {},
        error_details: p.error_details ?? null,
      },
      p.agent_id,
    )
  }
  map = pruneTrajectorySteps(map, maxCompleted)
  map = reconcileTerminalJobSteps(map, jobStatus)
  return [...map.values()].sort((a, b) => a.stepIdx - b.stepIdx)
}

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
      if (this.bytes > 72000) throw new ProtocolError('Event frame byte limit exceeded')
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

export function parseEvent(frame: SseFrame, jobId: string): StreamEvent {
  let data: unknown
  try { data = JSON.parse(frame.data) } catch { throw new ProtocolError() }
  if (data && typeof data === 'object' && 'type' in data) {
    const event = validateWire<ActivityEvent>('ActivityEvent', data)
    if (event.runId !== jobId || !Number.isSafeInteger(event.sequence) || frame.id !== String(event.sequence)
      || frame.kind !== event.type) throw new ProtocolError()
    return event
  }
  const event = validateWire<PersistedEvent>('PersistedEvent', data)
  if (event.job_id !== jobId || !Number.isSafeInteger(event.sequence) || frame.id !== String(event.sequence)
    || frame.kind !== event.kind) throw new ProtocolError()
  return event
}

export interface JobObserver {
  onEvent(event: StreamEvent): void | Promise<void>
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
  const seenIds = new Set<string>()
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
              const eventId = 'type' in event ? event.eventId : event.event_id
              if (seenIds.has(eventId)) { cursor = event.sequence; continue }
              await consume(observer.onEvent, event)
              if (lifecycle.signal.aborted) return
              cursor = event.sequence
              seenIds.add(eventId)
              if (seenIds.size > 2000) seenIds.delete(seenIds.values().next().value!)
              if ('kind' in event && event.kind === 'budget_updated' && observer.onJob && performance.now() - lastAccountingRefresh >= 1000) {
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
