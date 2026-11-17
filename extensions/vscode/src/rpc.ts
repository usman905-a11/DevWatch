import { randomUUID } from 'node:crypto'
import { Rpc } from './session'

/** Direct HTTP RPC adapter to the local canonical DevWatch FastAPI service. */
export function bridge(_python: string, _cwd: string, serviceUrl: string, apiKey: string, signal: AbortSignal): Rpc {
  const base = serviceUrl.replace(/\/+$/, '')

  async function requestJson(path: string, init: RequestInit = {}): Promise<any> {
    const headers = new Headers(init.headers)
    if (apiKey) headers.set('X-API-Key', apiKey)
    if (init.body !== undefined && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
    const controller = new AbortController()
    const abort = () => controller.abort()
    signal.addEventListener('abort', abort, { once: true })
    const timer = setTimeout(abort, 30000)
    try {
      const response = await fetch(`${base}${path}`, { ...init, headers, signal: controller.signal })
      if (!response.ok) throw Error(`Service operation failed (HTTP ${response.status})`)
      return await response.json()
    } finally {
      clearTimeout(timer)
      signal.removeEventListener('abort', abort)
    }
  }

  async function requestText(path: string): Promise<string> {
    const headers = new Headers()
    if (apiKey) headers.set('X-API-Key', apiKey)
    const response = await fetch(`${base}${path}`, { headers, signal })
    if (!response.ok) throw Error(`Service operation failed (HTTP ${response.status})`)
    return response.text()
  }

  async function collectWorkspaceFiles(root: string): Promise<Record<string, string>> {
    await requestJson('/workspace', { method: 'POST', body: JSON.stringify({ path: root }) })
    const files: Record<string, string> = {}
    const queue = ['']
    let totalBytes = 0
    while (queue.length > 0 && Object.keys(files).length < 100) {
      const dir = queue.shift()!
      const listed = await requestJson(`/fs/list?path=${encodeURIComponent(dir)}`)
      for (const entry of listed.entries ?? []) {
        if (entry.ignored || entry.isSymlink) continue
        if (entry.type === 'dir') {
          queue.push(entry.path)
        } else if (entry.type === 'file' && entry.size <= 500_000 && totalBytes + entry.size <= 10_000_000) {
          const read = await requestJson(`/fs/read?path=${encodeURIComponent(entry.path)}`)
          if (!read.binary && !read.tooLarge && typeof read.content === 'string') {
            files[entry.path] = read.content
            totalBytes += entry.size
          }
        }
        if (Object.keys(files).length >= 100) break
      }
    }
    return files
  }

  return async request => {
    const action = request.action
    if (action === 'capture') {
      const files = await collectWorkspaceFiles(String(request.root ?? ''))
      const snap = await requestJson('/api/snapshots', { method: 'POST', body: JSON.stringify({ files }) })
      return { intent: { snapshot_id: snap.snapshot_id, idempotency_key: randomUUID().replace(/-/g, '') } }
    }
    if (action === 'submit') {
      const intent = request.intent as { snapshot_id: string; changed_files?: string[] | null; idempotency_key: string }
      return requestJson('/api/jobs', {
        method: 'POST',
        headers: { 'Idempotency-Key': intent.idempotency_key },
        body: JSON.stringify({ snapshot_id: intent.snapshot_id, ...(intent.changed_files ? { changed_files: intent.changed_files } : {}) }),
      })
    }
    const jobId = String(request.job_id ?? '')
    if (action === 'status') return requestJson(`/api/jobs/${encodeURIComponent(jobId)}`)
    if (action === 'cancel' || action === 'resume') return requestJson(`/api/jobs/${encodeURIComponent(jobId)}/${action}`, { method: 'POST' })
    if (action === 'events') {
      const page = await requestJson(`/api/jobs/${encodeURIComponent(jobId)}/events?after=${Number(request.after ?? 0)}`)
      return {
        ...page,
        events: (page.events ?? []).map((event: any) => ({ ...event, sequence: event.sequence ?? event.seq, kind: event.kind ?? event.type })),
      }
    }
    if (action === 'report') {
      const format = String(request.format ?? 'json')
      return { text: await requestText(`/api/jobs/${encodeURIComponent(jobId)}/report?format=${encodeURIComponent(format)}`) }
    }
    if (action === 'source') {
      const params = new URLSearchParams({
        file_path: String(request.file_path ?? ''),
        start_line: String(request.start_line ?? 1),
        end_line: String(request.end_line ?? 1),
      })
      return requestJson(`/api/jobs/${encodeURIComponent(jobId)}/source?${params.toString()}`)
    }
    throw Error(`Unsupported IDE RPC action: ${action}`)
  }
}
