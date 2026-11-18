import React, { useMemo, useState } from 'react'
import { Clock, MessageSquarePlus, RefreshCw, Search } from 'lucide-react'
import type { JobView } from '../review/wire'

interface HistoryPanelProps {
  jobs: JobView[]
  activeJobId?: string | null
  activeWorkspacePath?: string | null
  busy?: boolean
  onSelectJob: (jobId: string) => void
  onNewReview?: () => void
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
  if (!path) return 'Snapshot review'
  const clean = path.replace(/[\\/]+$/, '')
  const parts = clean.split(/[\\/]/)
  return parts[parts.length - 1] || path
}

function normalizePathKey(path?: string | null): string {
  return (path ?? '').replace(/[\\/]+$/, '').toLowerCase()
}

function formatRelativeTime(createdAtSeconds: number): string {
  const diffSeconds = Math.max(0, Math.floor(Date.now() / 1000 - createdAtSeconds))
  if (diffSeconds < 60) return 'Just now'
  if (diffSeconds < 3600) return `${Math.floor(diffSeconds / 60)}m ago`
  if (diffSeconds < 86400) return `${Math.floor(diffSeconds / 3600)}h ago`
  if (diffSeconds < 172800) return 'Yesterday'
  return new Date(createdAtSeconds * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function groupBucket(createdAtSeconds: number): 'Today' | 'Yesterday' | 'Earlier' {
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000
  if (createdAtSeconds >= startOfToday) return 'Today'
  if (createdAtSeconds >= startOfToday - 86400) return 'Yesterday'
  return 'Earlier'
}

function formatFindingsBadge(job: JobView): string | null {
  const counts = job.finding_counts
  if (!counts) return null
  const parts: string[] = []
  if (counts.defects > 0) parts.push(`${counts.defects} defect${counts.defects === 1 ? '' : 's'}`)
  if (counts.uncertain > 0) parts.push(`${counts.uncertain} candidate${counts.uncertain === 1 ? '' : 's'}`)
  if (counts.advisories > 0) parts.push(`${counts.advisories} advisory`)
  return parts.length > 0 ? parts.join(' · ') : 'Clean'
}

export const HistoryPanel: React.FC<HistoryPanelProps> = ({
  jobs,
  activeJobId,
  activeWorkspacePath = null,
  busy = false,
  onSelectJob,
  onNewReview,
  onRefresh,
}) => {
  const [query, setQuery] = useState('')
  const [workspaceOnly, setWorkspaceOnly] = useState(false)

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    const targetWs = normalizePathKey(activeWorkspacePath)
    return jobs.filter(item => {
      if (workspaceOnly && targetWs && normalizePathKey(item.workspace_path) !== targetWs) {
        return false
      }
      if (!q) return true
      return (
        workspaceBasename(item.workspace_path).toLowerCase().includes(q)
        || (item.workspace_path ?? '').toLowerCase().includes(q)
        || (item.summary_preview ?? '').toLowerCase().includes(q)
        || item.status.toLowerCase().includes(q)
        || item.job_id.toLowerCase().includes(q)
      )
    })
  }, [jobs, query, workspaceOnly, activeWorkspacePath])

  const grouped = useMemo(() => {
    const buckets: Record<'Today' | 'Yesterday' | 'Earlier', JobView[]> = {
      Today: [],
      Yesterday: [],
      Earlier: [],
    }
    for (const job of filtered) {
      buckets[groupBucket(job.created_at)].push(job)
    }
    return (['Today', 'Yesterday', 'Earlier'] as const).filter(label => buckets[label].length > 0).map(label => ({
      label,
      items: buckets[label],
    }))
  }, [filtered])

  return (
    <div className="sidebar-panel">
      <div className="sidebar-panel-header">
        <span className="sidebar-panel-title">Review History</span>
        <div className="history-header-actions">
          {onNewReview && (
            <button
              type="button"
              className="header-button history-new-btn"
              disabled={busy}
              onClick={onNewReview}
            >
              <MessageSquarePlus className="icon-xs" /> New review
            </button>
          )}
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
      </div>

      <div className="sidebar-search-box">
        <Search className="icon-xs icon-muted" />
        <input
          type="search"
          aria-label="Filter review history"
          placeholder="Search review history..."
          value={query}
          onChange={e => setQuery(e.target.value)}
        />
      </div>

      {activeWorkspacePath && (
        <div className="history-scope-row" role="group" aria-label="History scope">
          <button
            type="button"
            className={`filter-chip ${!workspaceOnly ? 'active' : ''}`}
            aria-pressed={!workspaceOnly}
            onClick={() => setWorkspaceOnly(false)}
          >
            All folders
          </button>
          <button
            type="button"
            className={`filter-chip ${workspaceOnly ? 'active' : ''}`}
            aria-pressed={workspaceOnly}
            onClick={() => setWorkspaceOnly(true)}
          >
            Current folder
          </button>
        </div>
      )}

      {jobs.length === 0 ? (
        <div className="sidebar-empty">No past reviews yet. Run a review to start your history.</div>
      ) : grouped.length === 0 ? (
        <div className="sidebar-empty">No matching reviews in history.</div>
      ) : (
        <div className="history-groups" aria-label="Past review jobs">
          {grouped.map(group => (
            <section key={group.label} className="history-group">
              <h3 className="history-group-heading">{group.label}</h3>
              <ul className="history-list">
                {group.items.map(item => {
                  const active = item.job_id === activeJobId
                  const tokens = sumTokens(item)
                  const findingsText = formatFindingsBadge(item)
                  return (
                    <li key={item.job_id}>
                      <button
                        type="button"
                        data-job-id={item.job_id}
                        className={`history-card ${active ? 'active' : ''}`}
                        onClick={() => onSelectJob(item.job_id)}
                      >
                        <div className="history-card-top">
                          <span className="history-workspace" title={item.workspace_path ?? item.job_id}>
                            {workspaceBasename(item.workspace_path)}
                          </span>
                          <span className={`status-pill status-${item.status}`}>{item.status}</span>
                        </div>
                        {item.summary_preview && (
                          <p className="history-summary">{item.summary_preview}</p>
                        )}
                        <div className="history-card-stats">
                          <span>
                            <Clock className="icon-xs" /> {formatRelativeTime(item.created_at)}
                          </span>
                          {findingsText ? (
                            <span className="history-findings-pill">{findingsText}</span>
                          ) : (
                            <span>{tokens.toLocaleString()} tok</span>
                          )}
                        </div>
                      </button>
                    </li>
                  )
                })}
              </ul>
            </section>
          ))}
        </div>
      )}
    </div>
  )
}
