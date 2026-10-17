/** Job submission and observation are separate: abandoning HTTP never cancels a job. */
import { CaptureCoverage, identity, JobView, parseJob, parseReport, parseSource, ProtocolError,
  ReportDraft, sourcePath, SourceExcerpt, SnapshotManifest, validateWire } from './wire'
import { canonicalJson, hashUtf8 } from './wire-hashes'

export interface SubmissionIntent {
  snapshot_id: string
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

  async capture(files: Readonly<Record<string, string>>, coverage: CaptureCoverage = { skipped: {}, failed: {}, limitations: [] },
    signal?: AbortSignal): Promise<SnapshotManifest> {
    validateWire('CaptureCoverage', coverage)
    for (const [path, reason] of [...Object.entries(coverage.skipped), ...Object.entries(coverage.failed)]) {
      sourcePath(path)
      if (!/^[a-z][a-z_]{0,127}$/.test(reason)) throw new ProtocolError('Invalid capture omission')
    }
    if (coverage.limitations.some(text => !text || new TextEncoder().encode(text).byteLength > 512)) throw new ProtocolError('Invalid capture limitation')
    if (Object.keys(files).length > 100) throw new ProtocolError('Snapshot file count limit exceeded')
    const expected: SnapshotManifest['entries'] = Object.create(null)
    let total = 0
    for (const [path, content] of Object.entries(files)) {
      sourcePath(path)
      if (typeof content !== 'string') throw new ProtocolError('Invalid source content')
      const bytes = new TextEncoder().encode(content).byteLength
      if (bytes > 500000 || (total += bytes) > 10000000) throw new ProtocolError('Snapshot source byte limit exceeded')
      const lines = content.split(/\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]/u)
      if (lines[lines.length - 1] === '') lines.pop()
      expected[path] = { content_hash: await hashUtf8(content), byte_count: bytes, line_count: lines.length }
    }
    const body = JSON.stringify({ files, capture_coverage: coverage })
    if (new TextEncoder().encode(body).byteLength > 11000000) throw new ProtocolError('Snapshot request byte limit exceeded')
    const manifest = validateWire<SnapshotManifest>('SnapshotManifest', await this.json('/api/snapshots', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body }, signal))
    identity(manifest.snapshot_id)
    if (canonicalJson(manifest.entries) !== canonicalJson(expected) || canonicalJson(manifest.capture_coverage) !== canonicalJson(coverage)
      || manifest.content_hash !== await hashUtf8(canonicalJson(expected)) || manifest.capture_hash !== await hashUtf8(canonicalJson(coverage))) throw new ProtocolError()
    await this.verifyGitMetadata(manifest)
    if (canonicalJson(manifest.git_metadata) !== canonicalJson({ diffs: {}, history: {}, limitations: [] })) throw new ProtocolError()
    return manifest
  }

  private async verifyGitMetadata(manifest: SnapshotManifest): Promise<void> {
    const metadata = manifest.git_metadata
    if (manifest.git_hash !== await hashUtf8(canonicalJson(metadata))
      || new TextEncoder().encode(JSON.stringify(metadata)).byteLength > 200000) throw new ProtocolError()
    for (const path of [...Object.keys(metadata.diffs), ...Object.keys(metadata.history)]) {
      sourcePath(path)
      if (!Object.prototype.hasOwnProperty.call(manifest.entries, path)) throw new ProtocolError()
    }
    for (const value of Object.values(metadata.diffs)) {
      if (Object.keys(value).sort().join(',') !== 'staged,unstaged'
        || Object.values(value).some(text => new TextEncoder().encode(text).byteLength > 8192)) throw new ProtocolError()
    }
    if (Object.values(metadata.history).some(values => values.length > 5 || values.some(text => new TextEncoder().encode(text).byteLength > 1024))
      || metadata.limitations.some(text => new TextEncoder().encode(text).byteLength > 512)) throw new ProtocolError()
  }

  async submit(intent: SubmissionIntent, signal?: AbortSignal): Promise<JobView> {
    identity(intent.snapshot_id)
    if (!/^[\x21-\x7e]{1,256}$/.test(intent.idempotency_key)) throw new ProtocolError('Invalid idempotency key')
    intent.changed_files?.forEach(sourcePath)
    const body = { snapshot_id: intent.snapshot_id, ...(intent.changed_files === undefined ? {} : { changed_files: intent.changed_files }) }
    const job = parseJob(await this.json('/api/jobs', { method: 'POST', headers: {
      'Content-Type': 'application/json', 'Idempotency-Key': intent.idempotency_key }, body: JSON.stringify(body) }, signal))
    if (job.snapshot_id !== intent.snapshot_id) throw new ProtocolError()
    return job
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
  async snapshot(jobId: string, snapshotId: string, signal?: AbortSignal): Promise<SnapshotManifest> {
    identity(snapshotId)
    const manifest = validateWire<SnapshotManifest>('SnapshotManifest', await this.json(`/api/jobs/${identity(jobId)}/snapshot`, {}, signal))
    if (manifest.snapshot_id !== snapshotId) throw new ProtocolError()
    for (const path of Object.keys(manifest.entries)) sourcePath(path)
    if (manifest.content_hash !== await hashUtf8(canonicalJson(manifest.entries))
      || manifest.capture_hash !== await hashUtf8(canonicalJson(manifest.capture_coverage))) throw new ProtocolError()
    await this.verifyGitMetadata(manifest)
    return manifest
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
  async pdf(jobId: string, signal?: AbortSignal): Promise<ArrayBuffer> {
    await this.report(jobId, signal)
    const buffer = await this.requestBytes(`/api/jobs/${jobId}/report?format=pdf`, {}, 'application/pdf', 10000000, signal)
    const bytes = new Uint8Array(buffer), decoder = new TextDecoder()
    if (decoder.decode(bytes.subarray(0, 5)) !== '%PDF-' || !decoder.decode(bytes.subarray(-64)).trimEnd().endsWith('%%EOF')) throw new ProtocolError('Invalid PDF report')
    return buffer
  }
  async source(jobId: string, snapshotId: string, path: string, start: number, end: number, signal?: AbortSignal): Promise<SourceExcerpt> {
    identity(jobId); identity(snapshotId); sourcePath(path)
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 1 || end < start || end - start >= 200) throw new ProtocolError('Invalid source range')
    const query = new URLSearchParams({ file_path: path, start_line: String(start), end_line: String(end) })
    return parseSource(await this.json(`/api/jobs/${jobId}/source?${query}`, {}, signal), snapshotId, path, start, end)
  }
}
