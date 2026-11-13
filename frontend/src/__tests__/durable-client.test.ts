import { afterEach, describe, expect, it, vi } from 'vitest'
import type { SnapshotManifest } from '../review/wire'
import { canonicalJson, hashUtf8 } from '../review/wire-hashes'

const snapshotId = 'a'.repeat(32), jobId = 'b'.repeat(32)
const git_metadata = { diffs: {}, history: {}, limitations: [] }
const coverage = { inspected_files: [], inspected_symbols: [], skipped: {}, failed: {}, limitations: [] }
const report = { snapshot_id: snapshotId, summary: 'Source inspection was partial', confirmed_defects: [],
  uncertain_high_impact_candidates: [], advisories: [], coverage, limitations: ['Test fixture'] }
const limits = { review_seconds: 600, job_tokens: 250000, specialist_tokens: 50000, planner_tokens: 25000,
  final_agent_tokens: 50000, concurrent_model_calls: 3, iterations_per_task: 8, tool_calls_per_task: 12,
  review_rounds: 2, transient_retries: 2, schema_repairs_per_task: 1, provider_timeout_seconds: 30, command_timeout_seconds: 120,
  model_context_tokens: 32768 }
const ledger = { review_round: 1, agent_usage: {}, inflight: {}, task_iterations: {}, task_tools: {},
  task_schema_repairs: {}, operation_retries: {}, elapsed_seconds: 0 }
const job = { job_id: jobId, snapshot_id: snapshotId, status: 'running', workflow_version: 'seven-agent-v1',
  ledger, limits, created_at: 1, updated_at: 1 }

async function client(fetcher: typeof fetch) {
  const { DurableReviewClient } = await import('../review/durable-client')
  return new DurableReviewClient('http://localhost:8000', 'private-key', fetcher)
}
function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
}
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers() })

it('binds bounded evidence retrieval to the requested snapshot', async () => {
  const good = { snapshot_id: snapshotId, source_scope: ['service.py'], tool: 'read_source', data: 'immutable source' }
  const api = await client(async () => json(good))
  expect(await api.evidence(jobId, snapshotId, 'evidence-' + 'e'.repeat(64))).toEqual(good)
  const foreign = await client(async () => json({ ...good, snapshot_id: 'f'.repeat(32) }))
  await expect(foreign.evidence(jobId, snapshotId, 'evidence-' + 'e'.repeat(64))).rejects.toThrow(/invalid/i)
})

describe('canonical durable browser client', () => {
  it('downloads PDF bytes only after validating a completed snapshot report', async () => {
    const bytes = new Uint8Array([37, 80, 68, 70, 45, 49, 46, 55, 10, 255, 10, 37, 37, 69, 79, 70, 10])
    const paths: string[] = []
    const api = await client(async url => {
      paths.push(String(url))
      return String(url).endsWith('format=pdf') ? new Response(bytes, { headers: { 'Content-Type': 'application/pdf' } })
        : String(url).endsWith('format=json') ? json(report) : json({ ...job, status: 'completed' })
    })
    expect(typeof api.pdf).toBe('function')
    expect(new Uint8Array(await api.pdf(jobId))).toEqual(bytes)
    expect(paths).toEqual([`http://localhost:8000/api/jobs/${jobId}`,
      `http://localhost:8000/api/jobs/${jobId}/report?format=json`, `http://localhost:8000/api/jobs/${jobId}/report?format=pdf`])
  })
  it('rejects unfinished jobs, wrong PDF MIME, malformed PDF and oversized bytes', async () => {
    const pending = await client(async () => json(job))
    expect(typeof pending.pdf).toBe('function')
    await expect(pending.pdf(jobId)).rejects.toThrow(/finalized/i)
    for (const [mime, body] of [['text/html', '%PDF-1.7\n%%EOF'], ['application/pdf', '<html>'],
      ['application/pdf', '%PDF-' + 'x'.repeat(10000000) + '%%EOF']]) {
      const api = await client(async url => String(url).endsWith('format=pdf') ? new Response(body, { headers: { 'Content-Type': mime } })
        : String(url).endsWith('format=json') ? json(report) : json({ ...job, status: 'completed' }))
      await expect(api.pdf(jobId)).rejects.toThrow(/invalid|limit/i)
    }
  })
  it('opens workspace, lists directory entries, and reads files via /fs/* endpoints', async () => {
    const requests: string[] = []
    const api = await client(async (url, options) => {
      requests.push(`${options?.method ?? 'GET'} ${url}`)
      if (String(url).endsWith('/workspace')) return json({ path: 'E:/repo' })
      if (String(url).includes('/fs/list')) {
        return json({
          root: 'E:/repo',
          path: '',
          entries: [
            { name: 'node_modules', path: 'node_modules', type: 'dir', size: 0, isSymlink: false, ignored: true },
            { name: 'service.py', path: 'service.py', type: 'file', size: 120, isSymlink: false, ignored: false },
          ],
        })
      }
      if (String(url).includes('/fs/read')) {
        return json({ path: 'service.py', size: 120, binary: false, tooLarge: false, maxBytes: 2_000_000, lineCount: 2, content: 'pass\n' })
      }
      return json({})
    })
    expect((await api.setWorkspace('E:/repo')).path).toBe('E:/repo')
    const listing = await api.listDir('')
    expect(listing.entries).toHaveLength(2)
    expect(listing.entries[0].ignored).toBe(true)
    const file = await api.readFile('service.py')
    expect(file.content).toBe('pass\n')
    expect(requests[0]).toBe('POST http://localhost:8000/workspace')
  })
  it('reuses exact submission intent and credentials stay in headers', async () => {
    const requests: Array<[string, RequestInit]> = []
    const api = await client(async (url, options) => { requests.push([String(url), options!]); return json(job, 202) })
    const intent = { snapshot_id: snapshotId, changed_files: ['service.py'], idempotency_key: 'stable-intent' }
    expect((await api.submit(intent)).job_id).toBe(jobId)
    await api.submit(intent)
    expect(requests.length).toBe(2)
    expect(requests[0][1].body).toBe(requests[1][1].body)
    expect(new Headers(requests[0][1].headers).get('Idempotency-Key')).toBe('stable-intent')
    expect(new Headers(requests[0][1].headers).get('X-API-Key')).toBe('private-key')
    expect(requests[0][0]).toBe('http://localhost:8000/api/jobs')
    expect(requests[0][1].redirect).toBe('error')
  })

  it('does not retry an unknown submission or echo transport secrets', async () => {
    let calls = 0
    const api = await client(async () => { calls++; throw new Error('private source and credential') })
    await expect(api.submit({ snapshot_id: snapshotId, changed_files: [], idempotency_key: 'intent' })).rejects.toThrow(/unknown/i)
    expect(calls).toBe(1)
  })

  it('validates job schema, version, identity and finite budget accounting', async () => {
    for (const bad of [{ ...job, status: 'clean' }, { ...job, job_id: 'c'.repeat(32) },
      { ...job, workflow_version: 'legacy' }, { ...job, limits: { ...limits, concurrent_model_calls: 10 } },
      { ...job, ledger: { ...ledger, task_tools: { task: -1 } } }]) {
      const api = await client(async () => json(bad))
      await expect(api.status(jobId)).rejects.toThrow(/invalid/i)
    }
  })

  it('never fetches a report until completed status is verified', async () => {
    const paths: string[] = []
    const api = await client(async url => { paths.push(String(url)); return json(job) })
    await expect(api.report(jobId)).rejects.toThrow(/finalized/i)
    expect(paths).toEqual([`http://localhost:8000/api/jobs/${jobId}`])
  })

  it('validates final buckets, snapshot ranges and confidence without legacy mapping', async () => {
    const finding = { finding_id: 'f1', category: 'logic', kind: 'defect', title: 'Empty input raises',
      description: 'Index without guard', impact: 'Request fails', confidence: .9,
      location: { snapshot_id: snapshotId, file_path: 'service.py', start_line: 2, end_line: 2 },
      evidence_refs: ['evidence-' + 'd'.repeat(64)], remediation: '', verification_rationale: 'Input contract established' }
    const accepted = { ...report, confirmed_defects: [finding] }
    let next = accepted
    const api = await client(async url => String(url).endsWith('/report?format=json')
      ? json(next) : json({ ...job, status: 'completed' }))
    expect((await api.report(jobId)).confirmed_defects[0].finding_id).toBe('f1')
    for (const bad of [{ ...finding, confidence: .5 }, { ...finding, kind: 'advisory' },
      { ...finding, location: { ...finding.location, snapshot_id: 'e'.repeat(32) } },
      { ...finding, location: { ...finding.location, file_path: '../escape.py' } },
      { ...finding, location: { ...finding.location, end_line: 1 } }]) {
      next = { ...report, confirmed_defects: [bad] }
      await expect(api.report(jobId)).rejects.toThrow(/invalid/i)
    }
  })

  it('reads bounded immutable source from the job, never live filesystem', async () => {
    const paths: string[] = []
    const source = { snapshot_id: snapshotId, snapshot_hash: 'f'.repeat(64), source_scope: ['service.py'],
      tool: 'read_source', file_path: 'service.py', start_line: 2, end_line: 2, content_hash: 'd'.repeat(64), data: 'return items[0]' }
    const api = await client(async url => { paths.push(String(url)); return String(url).includes('/source?') ? json(source) : json(job) })
    expect((await api.source(jobId, snapshotId, 'service.py', 2, 2)).data).toBe('return items[0]')
    expect(paths).toEqual([`http://localhost:8000/api/jobs/${jobId}/source?file_path=service.py&start_line=2&end_line=2`])
    await expect(api.source(jobId, snapshotId, '../outside.py', 1, 500)).rejects.toThrow(/invalid/i)
    expect(paths.length).toBe(1)
  })

  it('refuses foreign source scopes and bounded-response violations', async () => {
    const api = await client(async () => new Response('x'.repeat(1000001), { headers: { 'Content-Type': 'application/json' } }))
    await expect(api.status(jobId)).rejects.toThrow(/limit/i)
    const other = await client(async () => json({ snapshot_id: 'c'.repeat(32), snapshot_hash: 'f'.repeat(64),
      source_scope: ['service.py'], tool: 'read_source', file_path: 'service.py', start_line: 1, end_line: 1,
      content_hash: 'd'.repeat(64), data: 'pass' }))
    await expect(other.source(jobId, snapshotId, 'service.py', 1, 1)).rejects.toThrow(/invalid/i)
  })

  it('offers explicit cancel and resume independently of observation', async () => {
    const paths: string[] = []
    const api = await client(async (url, options) => { paths.push(options!.method + ' ' + String(url)); return json({ ...job, status: 'interrupted' }) })
    await api.cancel(jobId); await api.resume(jobId)
    expect(paths).toEqual([`POST http://localhost:8000/api/jobs/${jobId}/cancel`, `POST http://localhost:8000/api/jobs/${jobId}/resume`])
  })
})

export { snapshotId, jobId, report, job, json }
