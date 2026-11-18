import React from 'react'
import { Clock, RefreshCw } from 'lucide-react'
import type { JobView } from '../review/wire'

interface HistoryPanelProps {
  jobs: JobView[]
  activeJobId?: string | null
  busy?: boolean
  onSelectJob: (jobId: string) => void
  onRefresh: () => void
}

function sumTokens(job: JobView): number {
  const usageMap = job.ledger?.agent_usage ?? {}
  return Object.values(usageMap).reduce(
    (sum, u) => sum + (u?.prompt_tokens ?? 0) + (u?.completion_tokens ?? 0),
    0,
  )
}

function workspaceBasename(path?: string | null): string {
  if (!path) return 'Snapshot job'
  const clean = path.replace(/[\\/]+$/, '')
  const parts = clean.split(/[\\/]/)
  return parts[parts.length - 1] || path
}

export const HistoryPanel: React.FC<HistoryPanelProps> = ({
  jobs,
  activeJobId,
  busy = false,
  onSelectJob,
  onRefresh,
}) => {
  return (
    <div className="sidebar-panel">
      <div className="sidebar-panel-header">
        <span className="sidebar-panel-title">Review History</span>
        <button
          type="button"
          className="icon-btn"
          aria-label="Refresh job history"
          title="Refresh job history"
          disabled={busy}
          onClick={onRefresh}
        >
          <RefreshCw className={`icon-xs ${busy ? 'spin' : ''}`} />
        </button>
      </div>
      {jobs.length === 0 ? (
        <div className="sidebar-empty">No past review jobs recorded yet.</div>
      ) : (
        <ul className="history-list" aria-label="Past review jobs">
          {jobs.map(item => {
            const active = item.job_id === activeJobId
            const tokens = sumTokens(item)
            return (
              <li key={item.job_id}>
                <button
                  type="button"
                  className={`history-card ${active ? 'active' : ''}`}
                  onClick={() => onSelectJob(item.job_id)}
                >
                  <div className="history-card-top">
                    <span className="history-workspace" title={item.workspace_path ?? item.job_id}>
                      {workspaceBasename(item.workspace_path)}
                    </span>
                    <span className={`status-pill status-${item.status}`}>{item.status}</span>
                  </div>
                  <div className="history-card-meta">
                    <code title={item.job_id}>{item.job_id}</code>
                  </div>
                  <div className="history-card-stats">
                    <span>
                      <Clock className="icon-xs" /> {(item.ledger?.elapsed_seconds ?? 0).toFixed(1)}s
                    </span>
                    <span>{tokens.toLocaleString()} tok</span>
                  </div>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

