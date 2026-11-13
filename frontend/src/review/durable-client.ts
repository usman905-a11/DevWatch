/** Job submission and observation are separate: abandoning HTTP never cancels a job. */
import { identity, JobView, parseJob, parseReport, parseSource, ProtocolError,
  ReportDraft, sourcePath, SourceExcerpt } from './wire'

export interface FsEntry {
  name: string
  path: string
  type: 'file' | 'dir'
  size: number
  isSymlink: boolean
  ignored: boolean
}

export interface FsListResponse {
  root: string
  path: string
  entries: FsEntry[]
}

export interface FsReadResponse {
  path: string
  size: number
  binary: boolean
  tooLarge: boolean
  maxBytes: number
  lineCount: number | null
  content: string | null
}

export interface WorkspaceResponse {
  path: string | null
  cancelled?: boolean
  error?: string
}

export interface SubmissionIntent {
  workspace_path?: string
  snapshot_id?: string
  changed_files?: readonly string[]
  idempotency_key: string
}
export class ServiceError extends Error {
  constructor(public status: number) { super(`Service request rejected (HTTP ${status})`) }
}
export class ConnectionError extends Error {
  constructor() { super('Service connection failed; outcome may be unknown. No submission retry or cancellation was issued.') }
}

export class DurableReviewClient {
  readonly serviceUrl: string
  constructor(serviceUrl = 'http://localhost:8000', private readonly apiKey = '', private readonly fetcher: typeof fetch = (input, options) => fetch(input, options)) {
    const url = new URL(serviceUrl)
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash
      || /[\x00-\x20\x7f]/.test(serviceUrl) || (apiKey && !/^[\x21-\x7e]{1,256}$/.test(apiKey))) throw new ProtocolError('Invalid service configuration')
    this.serviceUrl = url.href.replace(/\/$/, '')
  }

  /** Headers and signal are usable by the SSE observer; credentials remain memory-only. */
  async open(path: string, options: RequestInit, signal: AbortSignal): Promise<Response> {
    if (!/^\/api\/jobs\/[0-9a-f]{32}\/stream\?after=\d+$/.test(path)) throw new ProtocolError('Invalid event endpoint')
    return this.fetchResponse(path, options, signal)
  }

  private async fetchResponse(path: string, options: RequestInit, signal: AbortSignal): Promise<Response> {
    const headers = new Headers(options.headers)
    if (this.apiKey) headers.set('X-API-Key', this.apiKey)
    let response: Response
    try {
      response = await this.fetcher(this.serviceUrl + path, { ...options, headers, signal,
        cache: 'no-store', credentials: 'omit', redirect: 'error' })
      signal.throwIfAborted()
    } catch { throw new ConnectionError() }
    if (!response.ok) { void response.body?.cancel().catch(() => {}); throw new ServiceError(response.status) }
    return response
  }

  private async requestBytes(path: string, options: RequestInit = {}, mime = 'application/json', limit = 1000000, signal?: AbortSignal): Promise<ArrayBuffer> {
    const controller = new AbortController()
    const abort = () => controller.abort()
    signal?.addEventListener('abort', abort, { once: true })
    if (signal?.aborted) controller.abort()
    const timer = setTimeout(abort, 10000)
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined
    try {
      const response = await this.fetchResponse(path, { method: 'GET', ...options }, controller.signal)
      if (response.headers.get('Content-Type')?.split(';')[0].trim() !== mime || !response.body) throw new ProtocolError()
      reader = response.body.getReader()
      const chunks: Uint8Array[] = []
      let size = 0
      while (true) {
        const chunk = await reader.read()
        controller.signal.throwIfAborted()
        if (chunk.done) break
        size += chunk.value.byteLength
        if (size > limit) throw new ProtocolError('Service response byte limit exceeded')
        chunks.push(chunk.value)
      }
      const buffer = new ArrayBuffer(size), bytes = new Uint8Array(buffer)
      let offset = 0
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength }
      return buffer
    } catch (error) {
      if (error instanceof ProtocolError || error instanceof ServiceError || error instanceof ConnectionError) throw error
      throw new ConnectionError()
    } finally {
      clearTimeout(timer)
      signal?.removeEventListener('abort', abort)
      controller.abort()
      void reader?.cancel().catch(() => {})
    }
  }

  private async request(path: string, options: RequestInit = {}, mime = 'application/json', limit = 1000000, signal?: AbortSignal): Promise<string> {
    const bytes = await this.requestBytes(path, options, mime, limit, signal)
    try { return new TextDecoder('utf-8', { fatal: true }).decode(bytes) }
    catch { throw new ProtocolError('Invalid service response encoding') }
  }

  private async json(path: string, options: RequestInit = {}, signal?: AbortSignal, limit = 1000000): Promise<unknown> {
    const text = await this.request(path, options, 'application/json', limit, signal)
    try { return JSON.parse(text) } catch { throw new ProtocolError() }
  }

  async getWorkspace(signal?: AbortSignal): Promise<WorkspaceResponse> {
    return (await this.json('/workspace', {}, signal)) as WorkspaceResponse
  }

  async setWorkspace(path: string, signal?: AbortSignal): Promise<WorkspaceResponse> {
    if (!path.trim()) throw new ProtocolError('Workspace path must not be empty')
    return (await this.json('/workspace', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    }, signal)) as WorkspaceResponse
  }

  async pickWorkspace(signal?: AbortSignal): Promise<WorkspaceResponse> {
    return (await this.json('/workspace/pick', { method: 'POST' }, signal)) as WorkspaceResponse
  }

  async listDir(path = '', signal?: AbortSignal): Promise<FsListResponse> {
    const query = new URLSearchParams({ path })
    return (await this.json(`/fs/list?${query}`, {}, signal, 5000000)) as FsListResponse
  }

  async readFile(path: string, signal?: AbortSignal): Promise<FsReadResponse> {
    if (!path.trim()) throw new ProtocolError('File path must not be empty')
    const query = new URLSearchParams({ path })
    return (await this.json(`/fs/read?${query}`, {}, signal, 5000000)) as FsReadResponse
  }

  async submit(intent: SubmissionIntent, signal?: AbortSignal): Promise<JobView> {
    if (intent.snapshot_id) identity(intent.snapshot_id)
    if (!/^[\x21-\x7e]{1,256}$/.test(intent.idempotency_key)) throw new ProtocolError('Invalid idempotency key')
    intent.changed_files?.forEach(sourcePath)
    const body = {
      ...(intent.workspace_path ? { workspace_path: intent.workspace_path } : {}),
      ...(intent.snapshot_id ? { snapshot_id: intent.snapshot_id } : {}),
      ...(intent.changed_files === undefined ? {} : { changed_files: intent.changed_files }),
    }
    return parseJob(await this.json('/api/jobs', { method: 'POST', headers: {
      'Content-Type': 'application/json', 'Idempotency-Key': intent.idempotency_key }, body: JSON.stringify(body) }, signal))
  }

  async status(jobId: string, signal?: AbortSignal): Promise<JobView> {
    return parseJob(await this.json(`/api/jobs/${identity(jobId)}`, {}, signal), jobId)
  }
  async evidence(jobId: string, snapshotId: string, reference: string, signal?: AbortSignal): Promise<Record<string, unknown>> {
    identity(jobId); identity(snapshotId)
    if (!/^evidence-[0-9a-f]{64}$/.test(reference)) throw new ProtocolError()
    const value = await this.json(`/api/jobs/${jobId}/evidence/${reference}`, {}, signal, 1000000)
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new ProtocolError()
    const record = value as Record<string, unknown>
    if (record.snapshot_id !== snapshotId || !Array.isArray(record.source_scope) || record.source_scope.length > 100
      || typeof record.tool !== 'string' || !/^[a-z][a-z_]{0,63}$/.test(record.tool)) throw new ProtocolError()
    record.source_scope.forEach(path => { if (typeof path !== 'string') throw new ProtocolError(); sourcePath(path) })
    return record
  }
  async cancel(jobId: string, signal?: AbortSignal): Promise<JobView> {
    return parseJob(await this.json(`/api/jobs/${identity(jobId)}/cancel`, { method: 'POST' }, signal), jobId)
  }
  async resume(jobId: string, signal?: AbortSignal): Promise<JobView> {
    return parseJob(await this.json(`/api/jobs/${identity(jobId)}/resume`, { method: 'POST' }, signal), jobId)
  }
  async report(jobId: string, signal?: AbortSignal): Promise<ReportDraft> {
    const job = await this.status(jobId, signal)
    if (job.status !== 'completed') throw new ProtocolError('Report is not finalized')
    return parseReport(await this.json(`/api/jobs/${jobId}/report?format=json`, {}, signal, 10000000), job.snapshot_id)
  }
  async markdown(jobId: string, signal?: AbortSignal): Promise<string> {
    await this.report(jobId, signal)
    return this.request(`/api/jobs/${jobId}/report?format=markdown`, {}, 'text/markdown', 10000000, signal)
  }
  async source(jobId: string, snapshotId: string, path: string, start: number, end: number, signal?: AbortSignal): Promise<SourceExcerpt> {
    identity(jobId); identity(snapshotId); sourcePath(path)
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 1 || end < start || end - start >= 200) throw new ProtocolError('Invalid source range')
    const query = new URLSearchParams({ file_path: path, start_line: String(start), end_line: String(end) })
    return parseSource(await this.json(`/api/jobs/${jobId}/source?${query}`, {}, signal), snapshotId, path, start, end)
  }
}
