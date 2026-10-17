import { useEffect, useRef, useState } from 'react'
import FileExplorer from '../components/FileExplorer'
import { DurableReviewClient } from './durable-client'
import { captureFolder, FolderCapture } from './folder-capture'
import { JobActivity } from './JobActivity'
import { ReportPanel } from './ReportPanel'
import { SnapshotSource } from './SnapshotSource'
import { useReviewSession } from './useReviewSession'
import { ReportFinding } from './wire'

export function DurableApp() {
  const [client, setClient] = useState(() => new DurableReviewClient())
  const { session, state } = useReviewSession(client)
  const [serviceUrl, setServiceUrl] = useState(client.serviceUrl), [apiKey, setApiKey] = useState('')
  const [jobId, setJobId] = useState(''), [folder, setFolder] = useState<FolderCapture | null>(null)
  const [folderBusy, setFolderBusy] = useState(false), [localError, setLocalError] = useState<string | null>(null)
  const [path, setPath] = useState(''), [mobilePane, setMobilePane] = useState('review')
  const [evidence, setEvidence] = useState<string | null>(null), evidenceRequest = useRef<AbortController | null>(null)
  const folderInput = useRef<HTMLInputElement>(null), selection = useRef(0)
  const busy = state.busy || folderBusy
  const inputLocked = busy || session.hasPendingSubmission()
  const canChangeInput = () => !folderBusy && !session.getSnapshot().busy && !session.hasPendingSubmission()
  const active = state.job?.status === 'queued' || state.job?.status === 'running'
  const files = Object.keys(state.manifest?.entries ?? folder?.files ?? {})
  useEffect(() => { setPath('') }, [state.manifest?.snapshot_id])
  useEffect(() => { evidenceRequest.current?.abort(); setEvidence(null)
    return () => { evidenceRequest.current?.abort() }
  }, [state.job?.job_id])
  useEffect(() => () => { selection.current++ }, [])
  useEffect(() => {
    if (path && mobilePane === 'source' && window.matchMedia('(max-width: 900px)').matches) document.getElementById('source-pane')?.focus()
  }, [path, mobilePane])
  const openFolder = () => { if (canChangeInput()) folderInput.current?.click() }
  async function chooseFolder(event: React.ChangeEvent<HTMLInputElement>) {
    if (!canChangeInput()) { event.target.value = ''; return }
    const chosen = event.target.files
    if (!chosen?.length) return
    const current = ++selection.current
    session.reset(); setFolder(null); setLocalError(null); setFolderBusy(true); setPath('')
    try {
      const captured = await captureFolder(chosen)
      if (current === selection.current) setFolder(captured)
    } catch { if (current === selection.current) setLocalError('Could not read the selected folder.') }
    finally { if (current === selection.current) setFolderBusy(false); event.target.value = '' }
  }
  function configure(event: React.FormEvent) {
    event.preventDefault()
    if (!canChangeInput()) return
    try { setClient(new DurableReviewClient(serviceUrl, apiKey)); setLocalError(null) }
    catch { setLocalError('Enter a valid HTTP service address and API key.') }
  }
  function openJob(event: React.FormEvent) {
    event.preventDefault()
    if (!canChangeInput()) return
    selection.current++; setFolder(null); setPath(''); setLocalError(null)
    void session.attach(jobId.trim())
  }
  function openSource(filePath: string, start = 1, end?: number) {
    setPath(filePath); setMobilePane('source')
    const lines = state.manifest?.entries[filePath]?.line_count ?? 0
    if (lines === 0) return
    void session.openSource(filePath, start, Math.min(end ?? start + 19, start + 199, lines))
  }
  function openFinding(finding: ReportFinding) { openSource(finding.location.file_path, finding.location.start_line, finding.location.end_line) }
  async function openEvidence(reference: string) {
    if (!state.job) return
    evidenceRequest.current?.abort()
    const request = new AbortController(); evidenceRequest.current = request
    setEvidence('Loading tool evidence…')
    try {
      const value = await client.evidence(state.job.job_id, state.job.snapshot_id, reference, request.signal)
      if (!request.signal.aborted) setEvidence(JSON.stringify(value, null, 2))
    } catch { if (!request.signal.aborted) setEvidence('Tool evidence unavailable. Reconnect and retry.') }
  }
  async function exportReport(format: 'json' | 'markdown' | 'pdf') {
    if (!state.job || !state.report) return
    try {
      const data = format === 'json' ? JSON.stringify(state.report, null, 2) + '\n'
        : format === 'markdown' ? await client.markdown(state.job.job_id) : await client.pdf(state.job.job_id)
      const mime = { json: 'application/json', markdown: 'text/markdown', pdf: 'application/pdf' }[format]
      const extension = { json: 'json', markdown: 'md', pdf: 'pdf' }[format]
      const url = URL.createObjectURL(new Blob([data], { type: mime }))
      const link = document.createElement('a'); link.href = url; link.download = `devwatch-${state.job.job_id}.${extension}`
      link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch { setLocalError('Report download failed. Reconnect and try again.') }
  }
  return <div className="workspace">
    <a className="skip-link" href="#review-results" onClick={event => {
      event.preventDefault(); setMobilePane('review')
      requestAnimationFrame(() => document.getElementById('review-results')?.focus())
    }}>Skip to review results</a>
    <header className="titlebar"><div className="brand">DevWatch</div><div className="crumb"><strong>{state.job ? `Job ${state.job.job_id}` : folder?.name || 'Choose source or open a job'}</strong></div>
      <button className="review-button" disabled={busy || active || files.length === 0 || !folder || Boolean(state.intent && !state.job)}
        onClick={() => { if (folder) void session.start(folder.files, folder.coverage) }}>Run review</button>
    </header>
    <section className="source-bar" aria-label="Review connection and source">
      <details><summary>Service connection</summary><form className="connection-controls" onSubmit={configure}>
        <label>Service URL<input type="url" value={serviceUrl} autoComplete="off" onChange={event => setServiceUrl(event.target.value)} required /></label>
        <label>API key<input type="password" value={apiKey} autoComplete="off" onChange={event => setApiKey(event.target.value)} /></label>
        <button className="header-button" disabled={inputLocked}>Connect</button>
        <p>Credentials stay in this view. Jobs keep running when this view closes.</p>
      </form></details>
      <button className="header-button" type="button" disabled={inputLocked} onClick={openFolder}>Open local folder</button>
      <form className="job-controls" onSubmit={openJob}>
        <label>Job ID<input value={jobId} autoComplete="off" onChange={event => setJobId(event.target.value)} required /></label>
        <button className="header-button" disabled={inputLocked}>Open job</button>
      </form>
      {folder && !state.job && <p>{Object.keys(folder.files).length} files selected; {folder.omitted} omitted. Whole uploaded files are reviewed without Git history.</p>}
      <p>For Git changes, start a repository review with the CLI and open its job ID here.</p>
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
        <p>Submission intent: snapshot <code>{state.intent.snapshot_id}</code>; key <code>{state.intent.idempotency_key}</code>; entire snapshot scope.</p>
        <p>If the connection failed, retry this same submission to recover its job identity.</p>
        <button className="header-button" disabled={busy} onClick={() => { void session.retrySubmission() }}>Retry same submission</button>
      </div>}
      {(localError || state.error) && <div className="review-error" role="alert">{localError || state.error}</div>}
      {busy && <p role="status">{folderBusy ? 'Reading selected folder…' : 'Contacting review service…'}</p>}
    </section>
    <nav className="mobile-sections" aria-label="Workspace sections">
      {([['review', 'Review', 'review-results'], ['files', 'Files', 'source-files'], ['source', 'Source', 'source-pane']] as const).map(([pane, label, target]) =>
        <button key={pane} type="button" aria-controls={target} aria-pressed={mobilePane === pane} onClick={() => setMobilePane(pane)}>{label}</button>)}
    </nav>
    <div className="body" data-mobile-pane={mobilePane}>
      <FileExplorer tree={files.map(id => ({ id, name: id, type: 'file', ext: id.split('.').pop() }))} selectedFileId={path || null}
        projectName={state.manifest ? 'Review snapshot' : folder?.name || 'No source selected'} onSelectFile={file => openSource(file.id)} onOpenFolder={inputLocked ? undefined : openFolder} />
      <SnapshotSource source={state.source?.file_path === path ? state.source : null} error={state.sourceError} path={path}
        onRead={(start, end) => { if (state.job) void session.openSource(path, start, end) }} />
      <div className="review-column">
        <JobActivity job={state.job} events={state.events} connection={state.connection} onEvidence={reference => { void openEvidence(reference) }} />
        {evidence != null && <section className="tool-evidence" aria-label="Tool evidence"><h2>Tool evidence</h2>
          <button type="button" className="header-button" onClick={() => { evidenceRequest.current?.abort(); setEvidence(null) }}>Close evidence</button>
          <pre>{evidence}</pre></section>}
        <ReportPanel report={state.report} onSource={openFinding} />
      </div>
    </div>
    <footer className="statusbar"><span>{state.manifest ? 'Immutable snapshot' : 'Local source selection'}</span><span className="status-spacer" /><span>{state.job?.status ?? 'No job submitted'}</span></footer>
    <input ref={folderInput} type="file" multiple className="hidden-input" onChange={event => { void chooseFolder(event) }}
      {...({ webkitdirectory: '', directory: '' } as React.InputHTMLAttributes<HTMLInputElement>)} />
  </div>
}
