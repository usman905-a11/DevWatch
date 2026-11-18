import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ActivityBar, ActivityView } from '../components/ActivityBar'
import { BottomDrawer, BottomDrawerTab } from '../components/BottomDrawer'
import { CodeEditor, LineRange, OpenTab } from '../components/CodeEditor'
import { FileExplorer } from '../components/FileExplorer'
import { FolderPickerModal } from '../components/FolderPickerModal'
import { HistoryPanel } from '../components/HistoryPanel'
import { ExecutionMode, SettingsPanel } from '../components/SettingsPanel'
import { WorkspaceSearchPanel } from '../components/WorkspaceSearchPanel'
import { DurableReviewClient, ServiceError, WorkspaceBrowseResponse } from './durable-client'
import { isRangeCoveredByTab, mergeSourceExcerpt } from './source-buffer'
import { JobActivity } from './JobActivity'
import { ReportPanel } from './ReportPanel'
import { useReviewSession } from './useReviewSession'
import { ReportFinding } from './wire'

function readReviewUrlParam(): string | null {
  if (typeof window === 'undefined') return null
  const value = new URLSearchParams(window.location.search).get('review')
  return value && /^[0-9a-f]{32}$/.test(value) ? value : null
}

function syncReviewUrlParam(jobId: string | null): void {
  if (typeof window === 'undefined' || !window.history?.replaceState) return
  const url = new URL(window.location.href)
  if (jobId) {
    url.searchParams.set('review', jobId)
  } else {
    url.searchParams.delete('review')
  }
  const next = url.pathname + url.search + url.hash
  if (next !== window.location.pathname + window.location.search + window.location.hash) {
    window.history.replaceState(null, '', next)
  }
}

export function DurableApp() {
  const [client] = useState(() => new DurableReviewClient())
  const { session, state } = useReviewSession(client)
  const [workspacePath, setWorkspacePath] = useState<string | null>(null)
  const [folderBusy, setFolderBusy] = useState(false)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [pickerBrowse, setPickerBrowse] = useState<WorkspaceBrowseResponse | null>(null)
  const [pickerError, setPickerError] = useState<string | null>(null)
  const [localError, setLocalError] = useState<string | null>(null)
  const [tabs, setTabs] = useState<OpenTab[]>([])
  const [activePath, setActivePath] = useState<string | null>(null)
  const [highlightRange, setHighlightRange] = useState<LineRange | null>(null)
  const [mobilePane, setMobilePane] = useState('review')
  const [evidence, setEvidence] = useState<string | null>(null)
  const [activeActivity, setActiveActivity] = useState<ActivityView>('explorer')
  const [sidebarWidth, setSidebarWidth] = useState(272)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerTab, setDrawerTab] = useState<BottomDrawerTab>('problems')
  const [executionMode, setExecutionMode] = useState<ExecutionMode>('balanced')
  const [jobTokens, setJobTokens] = useState('')
  const evidenceRequest = useRef<AbortController | null>(null)
  const draggingSidebar = useRef(false)
  const initialRestoreDone = useRef(false)

  const busy = state.busy || folderBusy
  const inputLocked = busy || session.hasPendingSubmission()
  const canChangeInput = () => !folderBusy && !session.getSnapshot().busy && !session.hasPendingSubmission()
  const active = state.job?.status === 'queued' || state.job?.status === 'running'

  const allFindings = useMemo(
    () =>
      state.report
        ? [
            ...state.report.confirmed_defects,
            ...state.report.uncertain_high_impact_candidates,
            ...state.report.advisories,
          ]
        : [],
    [state.report],
  )

  const findingCountsByPath = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const item of allFindings) {
      counts[item.location.file_path] = (counts[item.location.file_path] ?? 0) + 1
    }
    return counts
  }, [allFindings])

  const parsedTokenBudget = useMemo(() => {
    const parsed = Number(jobTokens)
    return Number.isFinite(parsed) && parsed >= 1000 ? Math.floor(parsed) : undefined
  }, [jobTokens])

  useEffect(() => {
    let cancelled = false
    client.getWorkspace()
      .then(async res => {
        if (cancelled) return
        setLocalError(null)
        if (res.path) {
          setWorkspacePath(res.path)
        }
        const urlReviewId = readReviewUrlParam()
        const history = await session.refreshHistory()
        if (cancelled) return
        const activeMatch =
          history.find(item => ['running', 'queued'].includes(item.status) && (!res.path || item.workspace_path === res.path))
          ?? history.find(item => ['running', 'queued'].includes(item.status))
        const restoreId = urlReviewId ?? activeMatch?.job_id ?? null
        initialRestoreDone.current = true
        if (restoreId && canChangeInput()) {
          void session.switchJob(restoreId)
        }
      })
      .catch(err => {
        initialRestoreDone.current = true
        if (!cancelled && err instanceof ServiceError && err.status === 401) {
          setLocalError('Backend authentication failed. Check DEVWATCH_API_KEY in .env and restart the dev server.')
        }
      })
    return () => { cancelled = true }
  }, [client, session])

  useEffect(() => {
    if (initialRestoreDone.current) {
      syncReviewUrlParam(state.job?.job_id ?? null)
    }
  }, [state.job?.job_id])

  useEffect(() => {
    if (state.job?.status && ['completed', 'failed', 'cancelled'].includes(state.job.status)) {
      void session.refreshHistory()
    }
  }, [state.job?.job_id, state.job?.status, session])

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      if (!draggingSidebar.current) return
      const next = Math.min(440, Math.max(200, e.clientX - 48))
      setSidebarWidth(next)
    }
    const onUp = () => { draggingSidebar.current = false }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
  }, [])

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
    setTabs([])
    setActivePath(null)
    setHighlightRange(null)
    setLocalError(null)
  }

  async function browseFolderPath(targetPath?: string) {
    setFolderBusy(true)
    setPickerError(null)
    try {
      const data = await client.browseDirs(targetPath)
      setPickerBrowse(data)
    } catch (err) {
      if (err instanceof ServiceError && err.status === 401) {
        setPickerError('Backend authentication failed. Check DEVWATCH_API_KEY in .env.')
      } else {
        setPickerError('Could not list folders from the backend service.')
      }
    } finally {
      setFolderBusy(false)
    }
  }

  async function pickWorkspaceFolder() {
    if (!canChangeInput()) return
    setLocalError(null)
    setPickerOpen(true)
    await browseFolderPath(workspacePath ?? undefined)
  }

  async function selectPickedFolder(folderPath: string) {
    if (!canChangeInput()) return
    setFolderBusy(true)
    setPickerError(null)
    try {
      const res = await client.setWorkspace(folderPath)
      if (res.path) {
        applyWorkspace(res.path)
        setPickerOpen(false)
      }
    } catch (err) {
      if (err instanceof ServiceError && err.status === 401) {
        setPickerError('Backend authentication failed. Check DEVWATCH_API_KEY in .env.')
      } else {
        setPickerError('Could not open selected folder.')
      }
    } finally {
      setFolderBusy(false)
    }
  }

  function startNewReviewView() {
    if (!canChangeInput()) return
    session.reset()
    syncReviewUrlParam(null)
    setLocalError(null)
  }

  const openFile = useCallback(
    async (filePath: string, range?: { startLine: number; endLine: number }) => {
      setActivePath(filePath)
      setMobilePane('source')
      setHighlightRange(range ? { path: filePath, ...range } : null)

      const existing = tabs.find(t => t.path === filePath)
      if (existing?.file && isRangeCoveredByTab(existing.excerptBuffer, range)) {
        return
      }
      if (existing?.file && !existing.excerptBuffer && !existing.file.tooLarge) {
        return
      }

      setTabs(prev => {
        if (prev.some(t => t.path === filePath)) {
          return prev.map(t => (t.path === filePath ? { ...t, loading: true, error: null } : t))
        }
        return [...prev, { path: filePath, loading: true, error: null, file: null, excerptBuffer: null }]
      })

      const job = state.job
      const snapshotId = job?.snapshot_id ?? state.report?.snapshot_id
      try {
        let file = workspacePath ? await client.readFile(filePath).catch(() => null) : null
        let excerptBuffer = existing?.excerptBuffer ?? null
        if (file && !file.binary && !file.tooLarge && file.content != null) {
          excerptBuffer = mergeSourceExcerpt(null, { startLine: 1, endLine: Math.max(1, file.lineCount ?? 1), data: file.content }, true)
        } else if (!file && job && snapshotId) {
          const reqStart = range && range.endLine > 200 ? Math.max(1, range.startLine - 40) : 1
          const reqEnd = reqStart + 199
          const excerpt = await client.source(job.job_id, snapshotId, filePath, reqStart, reqEnd)
          excerptBuffer = mergeSourceExcerpt(excerptBuffer, {
            startLine: excerpt.start_line,
            endLine: excerpt.end_line,
            data: excerpt.data,
          })
          file = {
            path: filePath,
            size: excerptBuffer.content.length,
            binary: false,
            tooLarge: false,
            maxBytes: 2_000_000,
            lineCount: excerptBuffer.lines.length,
            content: excerptBuffer.content,
          }
        }
        if (!file) {
          file = await client.readFile(filePath)
          if (file.content != null) {
            excerptBuffer = mergeSourceExcerpt(null, { startLine: 1, endLine: Math.max(1, file.lineCount ?? 1), data: file.content }, true)
          }
        }
        setTabs(prev =>
          prev.map(t => (t.path === filePath ? { ...t, loading: false, error: null, file, excerptBuffer } : t)),
        )
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to read file'
        setTabs(prev =>
          prev.map(t => (t.path === filePath ? { ...t, loading: false, error: message } : t)),
        )
      }
    },
    [client, state.job, state.report, tabs, workspacePath],
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
    const snapshotId = state.job?.snapshot_id ?? state.report?.snapshot_id
    if (!state.job || !snapshotId) return
    evidenceRequest.current?.abort()
    const request = new AbortController()
    evidenceRequest.current = request
    setEvidence('Loading tool evidence…')
    try {
      const value = await client.evidence(state.job.job_id, snapshotId, reference, request.signal)
      if (!request.signal.aborted) setEvidence(JSON.stringify(value, null, 2))
    } catch {
      if (!request.signal.aborted) setEvidence('Tool evidence unavailable. Reconnect and retry.')
    }
  }

  async function exportReport(format: 'json' | 'markdown') {
    if (!state.job || !state.report) return
    try {
      const data = format === 'json' ? JSON.stringify(state.report, null, 2) + '\n' : await client.markdown(state.job.job_id)
      const mime = { json: 'application/json', markdown: 'text/markdown' }[format]
      const extension = { json: 'json', markdown: 'md' }[format]
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

  function handleSelectActivity(view: ActivityView) {
    if (view === 'findings') {
      setMobilePane('review')
      setDrawerTab('problems')
      setDrawerOpen(true)
      requestAnimationFrame(() => document.getElementById('review-results')?.focus())
      return
    }
    setActiveActivity(view)
    setMobilePane('files')
    if (view === 'history') void session.refreshHistory()
  }

  return <div className="workspace ide-shell">
    <a className="skip-link" href="#review-results" onClick={event => {
      event.preventDefault(); setMobilePane('review')
      requestAnimationFrame(() => document.getElementById('review-results')?.focus())
    }}>Skip to review results</a>
    <header className="titlebar ide-topbar">
      <div className="brand">DeWatch <span className="brand-badge">Review IDE</span></div>
      <div className="crumb">
        <strong>{state.job ? `Job ${state.job.job_id}` : workspacePath || 'Open a local workspace folder'}</strong>
      </div>
      <div className="topbar-controls">
        <span className={`stage-pill stage-${state.stage}`}>{state.stage}</span>
        <label className="topbar-field">
          <span>Execution mode</span>
          <select
            aria-label="Execution mode"
            disabled={inputLocked}
            value={executionMode}
            onChange={e => setExecutionMode(e.target.value as ExecutionMode)}
          >
            <option value="balanced">balanced</option>
            <option value="parallel">parallel</option>
            <option value="sequential">sequential</option>
          </select>
        </label>
        <label className="topbar-field">
          <span>Token budget</span>
          <input
            type="number"
            aria-label="Token budget"
            min={1000}
            step={1000}
            placeholder="Auto"
            disabled={inputLocked}
            value={jobTokens}
            onChange={e => setJobTokens(e.target.value)}
          />
        </label>
        <button
          className="review-button"
          disabled={busy || active || !workspacePath || Boolean(state.intent && !state.job)}
          onClick={() => {
            if (workspacePath) {
              void session.start(workspacePath, {
                executionMode,
                jobTokens: parsedTokenBudget,
              })
            }
          }}
        >
          Run review
        </button>
      </div>
    </header>
    <section className="source-bar" aria-label="Workspace and review history controls">
      <button className="header-button folder-picker-btn" type="button" disabled={inputLocked} onClick={() => { void pickWorkspaceFolder() }}>
        Open local folder
      </button>
      {workspacePath && (
        <span className="workspace-pill" title={workspacePath}>
          Folder: <code>{workspacePath}</code>
        </span>
      )}
      <button
        className="header-button"
        type="button"
        onClick={() => handleSelectActivity('history')}
      >
        Review history ({state.history.length})
      </button>
      {state.job && (
        <button
          className="header-button"
          type="button"
          disabled={inputLocked}
          onClick={startNewReviewView}
        >
          New review
        </button>
      )}
      <span className="status-note">Jobs keep running when this view closes.</span>
    </section>
    <section className="job-bar" aria-label="Durable job controls">
      {state.job && <>
        <code>Job ID: {state.job.job_id}</code>
        <button className="header-button" disabled={busy} onClick={() => { void session.reconnect() }}>Reconnect</button>
        {state.job.status === 'interrupted' && <button className="header-button" disabled={busy} onClick={() => { void session.resume() }}>Resume review</button>}
        {(active || state.job.status === 'interrupted') && <button className="header-button" disabled={busy} onClick={() => { void session.cancel() }}>Cancel review</button>}
        {state.report && <><button className="header-button" onClick={() => { void exportReport('json') }}>Download JSON</button>
          <button className="header-button" onClick={() => { void exportReport('markdown') }}>Download Markdown</button></>}
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
    <div
      className="body ide-body"
      data-mobile-pane={mobilePane}
      style={{ '--sidebar-width': `${sidebarWidth}px` } as React.CSSProperties}
    >
      <ActivityBar
        activeView={activeActivity}
        findingCount={allFindings.length}
        historyCount={state.history.length}
        onSelectView={handleSelectActivity}
      />
      <aside id="source-files" className="explorer-pane ide-sidebar" aria-label="File explorer">
        <div hidden={activeActivity !== 'explorer'} className="sidebar-pane-slot">
          <FileExplorer
            workspacePath={workspacePath}
            selectedFile={activePath}
            findingCounts={findingCountsByPath}
            pickerBusy={inputLocked}
            onSelectFile={filePath => { void openFile(filePath) }}
            onOpenFolder={() => { void pickWorkspaceFolder() }}
            loadDir={loadDir}
          />
        </div>
        {activeActivity === 'search' && (
          <WorkspaceSearchPanel
            tabs={tabs}
            onJumpToLine={(filePath, line) => { void openFile(filePath, { startLine: line, endLine: line }) }}
          />
        )}
        {activeActivity === 'history' && (
          <HistoryPanel
            jobs={state.history}
            activeJobId={state.job?.job_id}
            activeWorkspacePath={workspacePath}
            busy={busy}
            onSelectJob={selectedId => {
              setMobilePane('review')
              void session.switchJob(selectedId)
            }}
            onNewReview={startNewReviewView}
            onRefresh={() => { void session.refreshHistory() }}
          />
        )}
        {activeActivity === 'settings' && (
          <SettingsPanel
            executionMode={executionMode}
            jobTokens={jobTokens}
            onChangeExecutionMode={setExecutionMode}
            onChangeJobTokens={setJobTokens}
          />
        )}
      </aside>
      <div
        className="ide-resizer"
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize sidebar"
        tabIndex={0}
        onPointerDown={e => {
          e.preventDefault()
          draggingSidebar.current = true
        }}
        onKeyDown={e => {
          if (e.key === 'ArrowLeft') setSidebarWidth(w => Math.max(200, w - 16))
          if (e.key === 'ArrowRight') setSidebarWidth(w => Math.min(440, w + 16))
        }}
      />
      <div className="ide-center-column">
        <main id="source-pane" className="editor-pane" tabIndex={-1} aria-label="Code editor">
          <CodeEditor
            tabs={tabs}
            activePath={activePath}
            highlightRange={highlightRange}
            findings={allFindings}
            onSelectTab={setActivePath}
            onCloseTab={closeTab}
          />
        </main>
        <BottomDrawer
          open={drawerOpen}
          activeTab={drawerTab}
          report={state.report}
          events={state.events}
          steps={state.steps}
          onToggleOpen={() => setDrawerOpen(v => !v)}
          onSelectTab={setDrawerTab}
          onOpenFinding={openFinding}
        />
      </div>
      <div className="review-column ide-right-column">
        <JobActivity job={state.job} events={state.events} steps={state.steps} connection={state.connection} onEvidence={reference => { void openEvidence(reference) }} />
        {evidence != null && <section className="tool-evidence" aria-label="Tool evidence"><h2>Tool evidence</h2>
          <button type="button" className="header-button" onClick={() => { evidenceRequest.current?.abort(); setEvidence(null) }}>Close evidence</button>
          <pre>{evidence}</pre></section>}
        <ReportPanel report={state.report} onSource={openFinding} />
      </div>
    </div>
    <footer className="statusbar ide-statusbar">
      <span>{workspacePath ? `Workspace: ${workspacePath}` : 'No workspace open'}</span>
      <span>Mode: {executionMode}</span>
      <span>{allFindings.length} findings</span>
      <span className="status-spacer" />
      <span>{state.job?.status ?? 'No job submitted'}</span>
    </footer>
    <FolderPickerModal
      open={pickerOpen}
      browseData={pickerBrowse}
      loading={folderBusy}
      error={pickerError}
      onNavigate={path => { void browseFolderPath(path) }}
      onSelectFolder={path => { void selectPickedFolder(path) }}
      onClose={() => setPickerOpen(false)}
    />
  </div>
}
