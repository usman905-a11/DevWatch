import { useCallback, useEffect, useRef, useState } from 'react'
import { CodeEditor, LineRange, OpenTab } from '../components/CodeEditor'
import { FileExplorer } from '../components/FileExplorer'
import { DurableReviewClient } from './durable-client'
import { JobActivity } from './JobActivity'
import { ReportPanel } from './ReportPanel'
import { useReviewSession } from './useReviewSession'
import { ReportFinding } from './wire'

export function DurableApp() {
  const [client, setClient] = useState(() => new DurableReviewClient())
  const { session, state } = useReviewSession(client)
  const [serviceUrl, setServiceUrl] = useState(client.serviceUrl)
  const [apiKey, setApiKey] = useState('')
  const [jobId, setJobId] = useState('')
  const [workspacePath, setWorkspacePath] = useState<string | null>(null)
  const [pathInput, setPathInput] = useState('')
  const [folderBusy, setFolderBusy] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)
  const [tabs, setTabs] = useState<OpenTab[]>([])
  const [activePath, setActivePath] = useState<string | null>(null)
  const [highlightRange, setHighlightRange] = useState<LineRange | null>(null)
  const [mobilePane, setMobilePane] = useState('review')
  const [evidence, setEvidence] = useState<string | null>(null)
  const evidenceRequest = useRef<AbortController | null>(null)

  const busy = state.busy || folderBusy
  const inputLocked = busy || session.hasPendingSubmission()
  const canChangeInput = () => !folderBusy && !session.getSnapshot().busy && !session.hasPendingSubmission()
  const active = state.job?.status === 'queued' || state.job?.status === 'running'

  useEffect(() => {
    let cancelled = false
    client.getWorkspace()
      .then(res => {
        if (!cancelled && res.path) {
          setWorkspacePath(res.path)
          setPathInput(res.path)
        }
      })
      .catch(() => {
        // Service may not be started yet; ignore initial probe failure.
      })
    return () => { cancelled = true }
  }, [client])

  useEffect(() => {
    evidenceRequest.current?.abort()
    setEvidence(null)
    return () => { evidenceRequest.current?.abort() }
  }, [state.job?.job_id])

  const loadDir = useCallback(
    async (dirPath: string) => {
      const res = await client.listDir(dirPath)
      return res.entries
    },
    [client],
  )

  const applyWorkspace = (resolved: string) => {
    session.reset()
    setWorkspacePath(resolved)
    setPathInput(resolved)
    setTabs([])
    setActivePath(null)
    setHighlightRange(null)
    setLocalError(null)
  }

  async function pickWorkspaceFolder() {
    if (!canChangeInput()) return
    setFolderBusy(true)
    setLocalError(null)
    try {
      const res = await client.pickWorkspace()
      if (res.path) {
        applyWorkspace(res.path)
      } else if (res.error) {
        setLocalError('Native folder picker unavailable. Enter the folder path below.')
      }
    } catch {
      setLocalError('Could not open folder picker. Enter the folder path below.')
    } finally {
      setFolderBusy(false)
    }
  }

  async function submitWorkspacePath(event: React.FormEvent) {
    event.preventDefault()
    if (!canChangeInput()) return
    const trimmed = pathInput.trim()
    if (!trimmed) return
    setFolderBusy(true)
    setLocalError(null)
    try {
      const res = await client.setWorkspace(trimmed)
      if (res.path) applyWorkspace(res.path)
    } catch {
      setLocalError('Workspace path could not be opened. Check that the directory exists.')
    } finally {
      setFolderBusy(false)
    }
  }

  function configure(event: React.FormEvent) {
    event.preventDefault()
    if (!canChangeInput()) return
    try {
      setClient(new DurableReviewClient(serviceUrl, apiKey))
      setLocalError(null)
    } catch {
      setLocalError('Enter a valid HTTP service address and API key.')
    }
  }

  function openJob(event: React.FormEvent) {
    event.preventDefault()
    if (!canChangeInput()) return
    setLocalError(null)
    void session.attach(jobId.trim())
  }

  const openFile = useCallback(
    async (filePath: string, range?: { startLine: number; endLine: number }) => {
      setActivePath(filePath)
      setMobilePane('source')
      setHighlightRange(range ? { path: filePath, ...range } : null)

      const existing = tabs.find(t => t.path === filePath)
      if (existing && (existing.file || existing.loading)) {
        return
      }

      setTabs(prev => {
        if (prev.some(t => t.path === filePath)) {
          return prev.map(t => (t.path === filePath ? { ...t, loading: true, error: null } : t))
        }
        return [...prev, { path: filePath, loading: true, error: null, file: null }]
      })

      try {
        const file = await client.readFile(filePath)
        setTabs(prev =>
          prev.map(t => (t.path === filePath ? { ...t, loading: false, error: null, file } : t)),
        )
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to read file'
        setTabs(prev =>
          prev.map(t => (t.path === filePath ? { ...t, loading: false, error: message } : t)),
        )
      }
    },
    [client, tabs],
  )

  const closeTab = useCallback(
    (filePath: string) => {
      setTabs(prev => {
        const idx = prev.findIndex(t => t.path === filePath)
        const next = prev.filter(t => t.path !== filePath)
        if (activePath === filePath) {
          const fallback = next[Math.min(idx, next.length - 1)]?.path ?? null
          setActivePath(fallback)
        }
        return next
      })
    },
    [activePath],
  )

  function openFinding(finding: ReportFinding) {
    void openFile(finding.location.file_path, {
      startLine: finding.location.start_line,
      endLine: finding.location.end_line,
    })
  }

  async function openEvidence(reference: string) {
    if (!state.job) return
    evidenceRequest.current?.abort()
    const request = new AbortController()
    evidenceRequest.current = request
    setEvidence('Loading tool evidence…')
    try {
      const value = await client.evidence(state.job.job_id, state.job.snapshot_id, reference, request.signal)
      if (!request.signal.aborted) setEvidence(JSON.stringify(value, null, 2))
    } catch {
      if (!request.signal.aborted) setEvidence('Tool evidence unavailable. Reconnect and retry.')
    }
  }

  async function exportReport(format: 'json' | 'markdown' | 'pdf') {
    if (!state.job || !state.report) return
    try {
      const data = format === 'json' ? JSON.stringify(state.report, null, 2) + '\n'
        : format === 'markdown' ? await client.markdown(state.job.job_id) : await client.pdf(state.job.job_id)
      const mime = { json: 'application/json', markdown: 'text/markdown', pdf: 'application/pdf' }[format]
      const extension = { json: 'json', markdown: 'md', pdf: 'pdf' }[format]
      const url = URL.createObjectURL(new Blob([data], { type: mime }))
      const link = document.createElement('a')
      link.href = url
      link.download = `devwatch-${state.job.job_id}.${extension}`
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch {
      setLocalError('Report download failed. Reconnect and try again.')
    }
  }

  return <div className="workspace">
    <a className="skip-link" href="#review-results" onClick={event => {
      event.preventDefault(); setMobilePane('review')
      requestAnimationFrame(() => document.getElementById('review-results')?.focus())
    }}>Skip to review results</a>
    <header className="titlebar">
      <div className="brand">DevWatch</div>
      <div className="crumb">
        <strong>{state.job ? `Job ${state.job.job_id}` : workspacePath || 'Open a local workspace folder'}</strong>
      </div>
      <button
        className="review-button"
        disabled={busy || active || !workspacePath || Boolean(state.intent && !state.job)}
        onClick={() => { if (workspacePath) void session.start(workspacePath) }}
      >
        Run review
      </button>
    </header>
    <section className="source-bar" aria-label="Review connection and workspace">
      <details><summary>Service connection</summary><form className="connection-controls" onSubmit={configure}>
        <label>Service URL<input type="url" value={serviceUrl} autoComplete="off" onChange={event => setServiceUrl(event.target.value)} required /></label>
        <label>API key<input type="password" value={apiKey} autoComplete="off" onChange={event => setApiKey(event.target.value)} /></label>
        <button className="header-button" disabled={inputLocked}>Connect</button>
        <p>Credentials stay in this view. Jobs keep running when this view closes.</p>
      </form></details>
      <button className="header-button" type="button" disabled={inputLocked} onClick={() => { void pickWorkspaceFolder() }}>
        Open local folder
      </button>
      <form className="job-controls" onSubmit={event => { void submitWorkspacePath(event) }}>
        <label>Folder path<input value={pathInput} placeholder="e.g. E:\\my-repo" autoComplete="off" onChange={event => setPathInput(event.target.value)} required /></label>
        <button className="header-button" disabled={inputLocked}>Set workspace</button>
      </form>
      <form className="job-controls" onSubmit={openJob}>
        <label>Job ID<input value={jobId} autoComplete="off" onChange={event => setJobId(event.target.value)} required /></label>
        <button className="header-button" disabled={inputLocked}>Open job</button>
      </form>
    </section>
    <section className="job-bar" aria-label="Durable job controls">
      {state.job && <>
        <code>Job ID: {state.job.job_id}</code>
        <button className="header-button" disabled={busy} onClick={() => { void session.reconnect() }}>Reconnect</button>
        {state.job.status === 'interrupted' && <button className="header-button" disabled={busy} onClick={() => { void session.resume() }}>Resume review</button>}
        {(active || state.job.status === 'interrupted') && <button className="header-button" disabled={busy} onClick={() => { void session.cancel() }}>Cancel review</button>}
        {state.report && <><button className="header-button" onClick={() => { void exportReport('json') }}>Download JSON</button>
          <button className="header-button" onClick={() => { void exportReport('markdown') }}>Download Markdown</button>
          <button className="header-button" onClick={() => { void exportReport('pdf') }}>Download PDF</button></>}
      </>}
      {state.intent && !state.job && <div className="submission-intent">
        <p>Submission intent: workspace <code>{state.intent.workspace_path ?? state.intent.snapshot_id}</code>; key <code>{state.intent.idempotency_key}</code>.</p>
        <p>If the connection failed, retry this same submission to recover its job identity.</p>
        <button className="header-button" disabled={busy} onClick={() => { void session.retrySubmission() }}>Retry same submission</button>
      </div>}
      {(localError || state.error) && <div className="review-error" role="alert">{localError || state.error}</div>}
      {busy && <p role="status">{folderBusy ? 'Opening workspace…' : 'Contacting review service…'}</p>}
    </section>
    <nav className="mobile-sections" aria-label="Workspace sections">
      {([['review', 'Review', 'review-results'], ['files', 'Files', 'source-files'], ['source', 'Source', 'source-pane']] as const).map(([pane, label, target]) =>
        <button key={pane} type="button" aria-controls={target} aria-pressed={mobilePane === pane} onClick={() => setMobilePane(pane)}>{label}</button>)}
    </nav>
    <div className="body" data-mobile-pane={mobilePane}>
      <aside id="source-files" className="explorer-pane" aria-label="File explorer">
        <FileExplorer
          workspacePath={workspacePath}
          selectedFile={activePath}
          onSelectFile={filePath => { void openFile(filePath) }}
          loadDir={loadDir}
        />
      </aside>
      <main id="source-pane" className="editor-pane" tabIndex={-1} aria-label="Code editor">
        <CodeEditor
          tabs={tabs}
          activePath={activePath}
          highlightRange={highlightRange}
          onSelectTab={setActivePath}
          onCloseTab={closeTab}
        />
      </main>
      <div className="review-column">
        <JobActivity job={state.job} events={state.events} steps={state.steps} connection={state.connection} onEvidence={reference => { void openEvidence(reference) }} />
        {evidence != null && <section className="tool-evidence" aria-label="Tool evidence"><h2>Tool evidence</h2>
          <button type="button" className="header-button" onClick={() => { evidenceRequest.current?.abort(); setEvidence(null) }}>Close evidence</button>
          <pre>{evidence}</pre></section>}
        <ReportPanel report={state.report} onSource={openFinding} />
      </div>
    </div>
    <footer className="statusbar">
      <span>{workspacePath ? `Workspace: ${workspacePath}` : 'No workspace open'}</span>
      <span className="status-spacer" />
      <span>{state.job?.status ?? 'No job submitted'}</span>
    </footer>
  </div>
}
