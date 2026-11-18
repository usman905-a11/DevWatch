import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import codeEditor from '../components/CodeEditor.tsx?raw'
import explorer from '../components/FileExplorer.tsx?raw'
import { CodeEditor } from '../components/CodeEditor'
import { FileExplorer } from '../components/FileExplorer'
import fixture from './fixtures/canonical-wire.json'
import { DurableReviewClient } from '../review/durable-client'
import { ReviewSession } from '../review/review-session'
import { deriveAgentStatuses, deriveReviewStage } from '../review/durable-events'
import { mergeSourceExcerpt, isRangeCoveredByTab } from '../review/source-buffer'

const json = (data: unknown) => new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })
const eof = () => new Response('', { headers: { 'Content-Type': 'text/event-stream' } })

describe('Phase 4 frontend contracts and session tracking', () => {
  it('supports GET /api/jobs history and optional execution/context parameters on submit', async () => {
    const calls: Array<{ url: string; body?: string }> = []
    const api = new DurableReviewClient('http://localhost:8000', '', async (url, init) => {
      calls.push({ url: String(url), body: init?.body ? String(init.body) : undefined })
      if (String(url).includes('/api/jobs?')) return json({ jobs: [fixture.job] })
      if (String(url).endsWith('/api/jobs')) return json(fixture.job)
      return json(fixture.job)
    })

    const jobs = await (api as any).listJobs(20)
    expect(jobs).toHaveLength(1)
    expect(jobs[0].job_id).toBe(fixture.job.job_id)
    expect(calls[0].url).toContain('/api/jobs?limit=20')

    await api.submit({
      workspace_path: 'E:/repo',
      context_files: ['README.md'],
      execution_mode: 'balanced',
      job_tokens: 40000,
      idempotency_key: 'p4-opts',
    } as any)
    expect(JSON.parse(calls[1].body!)).toEqual({
      workspace_path: 'E:/repo',
      context_files: ['README.md'],
      execution_mode: 'balanced',
      job_tokens: 40000,
    })
  })

  it('derives structured lifecycle stage and per-agent statuses cleanly from events', async () => {
    const base = { job_id: fixture.job.job_id, timestamp: 10 }
    const events: any[] = [
      { ...base, seq: 1, type: 'graph_node_started', payload: { node: 'planner', agent_id: 'planner' } },
      { ...base, seq: 2, type: 'agent_started', payload: { agent_id: 'bug_reliability', task_id: 'bug-1' } },
      { ...base, seq: 3, type: 'tool_called', payload: { agent_id: 'bug_reliability', task_id: 'bug-1', tool: 'read_file' } },
      { ...base, seq: 4, type: 'agent_completed', payload: { agent_id: 'bug_reliability', task_id: 'bug-1', outcome: 'succeeded', total_tokens: 22 } },
    ]
    expect(deriveReviewStage(events, { ...fixture.job, status: 'running' } as any)).toBe('investigating')
    const statuses = deriveAgentStatuses(events, [], { ...fixture.job, status: 'running' } as any)
    expect(statuses.bug_reliability.state).toBe('completed')
    expect(statuses.bug_reliability.tokens).toBe(22)
    expect(statuses.planner.state).toBe('running')

    const api = new DurableReviewClient('http://localhost:8000', '', async url => {
      if (String(url).includes('/api/jobs?')) return json({ jobs: [fixture.job] })
      if (String(url).includes('/stream?')) return eof()
      if (String(url).includes('/report?')) return json(fixture.report)
      return json(fixture.job)
    })
    const session = new ReviewSession(api)
    await (session as any).refreshHistory()
    expect((session.getSnapshot() as any).history).toHaveLength(1)
    session.dispose()
  })

  it('merges sparse line ranges so multi-finding re-navigation keeps prior lines and populates newly requested ranges', () => {
    const first = mergeSourceExcerpt(null, { startLine: 40, endLine: 42, data: 'L40\nL41\nL42' })
    expect(isRangeCoveredByTab(first, { startLine: 40, endLine: 42 })).toBe(true)
    expect(isRangeCoveredByTab(first, { startLine: 5, endLine: 6 })).toBe(false)

    const merged = mergeSourceExcerpt(first, { startLine: 4, endLine: 6, data: 'L4\nL5\nL6' })
    expect(isRangeCoveredByTab(merged, { startLine: 5, endLine: 6 })).toBe(true)
    expect(isRangeCoveredByTab(merged, { startLine: 40, endLine: 42 })).toBe(true)
    const lines = merged.content.split('\n')
    expect(lines[3]).toBe('L4')
    expect(lines[4]).toBe('L5')
    expect(lines[39]).toBe('L40')
  })

  it('uses real CSS classes instead of missing unbundled Tailwind utility classes', () => {
    const editorHtml = renderToStaticMarkup(
      createElement(CodeEditor, {
        tabs: [
          {
            path: 'a.py',
            loading: false,
            file: { path: 'a.py', size: 5, binary: false, tooLarge: false, maxBytes: 100000, lineCount: 1, content: 'x = 1' },
          },
        ],
        activePath: 'a.py',
        highlightRange: null,
        onSelectTab: () => {},
        onCloseTab: () => {},
      }),
    )
    const explorerHtml = renderToStaticMarkup(
      createElement(FileExplorer, {
        workspacePath: 'E:/repo',
        selectedFile: 'a.py',
        onSelectFile: () => {},
        loadDir: async () => [],
      }),
    )
    expect(editorHtml).toContain('code-editor')
    expect(editorHtml).toContain('editor-tabbar')
    expect(explorerHtml).toContain('explorer-panel')
    expect(explorer).toContain('explorer-row')
    expect(codeEditor).not.toContain('bg-zinc-950')
    expect(codeEditor).not.toContain('bg-amber-500/20')
    expect(explorer).not.toContain('bg-zinc-950/60')
  })
})
