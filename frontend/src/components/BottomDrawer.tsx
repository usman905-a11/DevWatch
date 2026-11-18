import React from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import type { TrajectoryStep } from '../review/durable-events'
import type { ReportDraft, ReportFinding, StreamEvent } from '../review/wire'

export type BottomDrawerTab = 'problems' | 'coverage' | 'logs'

interface BottomDrawerProps {
  open: boolean
  activeTab: BottomDrawerTab
  report: ReportDraft | null
  events: StreamEvent[]
  steps: TrajectoryStep[]
  onToggleOpen: () => void
  onSelectTab: (tab: BottomDrawerTab) => void
  onOpenFinding: (finding: ReportFinding) => void
}

const SEVERITY_ORDER: Record<ReportFinding['severity'], number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
  info: 4,
}

export const BottomDrawer: React.FC<BottomDrawerProps> = ({
  open,
  activeTab,
  report,
  events,
  steps,
  onToggleOpen,
  onSelectTab,
  onOpenFinding,
}) => {
  const problems = report
    ? [
        ...report.confirmed_defects,
        ...report.uncertain_high_impact_candidates,
        ...report.advisories,
      ].sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9))
    : []

  const metrics = report?.coverage?.metrics ?? null
  const provenance = report?.verification_audit?.provenance ?? {}
  const coveragePct =
    metrics && metrics.eligible > 0 ? ((metrics.inspected / metrics.eligible) * 100).toFixed(1) : '0.0'

  return (
    <section className={`ide-bottom-drawer ${open ? 'open' : 'collapsed'}`} aria-label="Diagnostics and audit drawer">
      <div className="drawer-header">
        <div className="drawer-tabs" role="tablist" aria-label="Bottom panel sections">
          {(
            [
              ['problems', `Problems (${problems.length})`],
              ['coverage', 'Coverage & Audit'],
              ['logs', `Execution Logs (${steps.length || events.length})`],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={open && activeTab === id}
              className={`drawer-tab-btn ${open && activeTab === id ? 'active' : ''}`}
              onClick={() => {
                onSelectTab(id)
                if (!open) onToggleOpen()
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <button
          type="button"
          className="icon-btn"
          aria-label={open ? 'Collapse bottom panel' : 'Expand bottom panel'}
          onClick={onToggleOpen}
        >
          {open ? <ChevronDown className="icon-sm" /> : <ChevronUp className="icon-sm" />}
        </button>
      </div>

      {open && (
        <div className="drawer-body">
          {activeTab === 'problems' && (
            problems.length === 0 ? (
              <div className="drawer-empty">No findings recorded for the current job yet.</div>
            ) : (
              <div className="problems-table-wrap">
                <table className="problems-table">
                  <thead>
                    <tr>
                      <th>Severity</th>
                      <th>Finding</th>
                      <th>Location</th>
                      <th>Agent</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {problems.map(item => (
                      <tr key={item.finding_id}>
                        <td>
                          <span className={`severity-pill severity-${item.severity}`}>{item.severity}</span>
                        </td>
                        <td>{item.title}</td>
                        <td>
                          <code>
                            {item.location.file_path}:{item.location.start_line}
                          </code>
                        </td>
                        <td>
                          <span className="agent-chip">{provenance[item.finding_id]?.agent_id ?? item.category}</span>
                        </td>
                        <td>
                          <button type="button" className="header-button" onClick={() => onOpenFinding(item)}>
                            Open source
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          )}

          {activeTab === 'coverage' && (
            !report ? (
              <div className="drawer-empty">Coverage and verification audit data appear after finalization.</div>
            ) : (
              <div className="coverage-audit-grid">
                {metrics ? (
                  <div className="coverage-stats-row">
                    <div className="metric-card">
                      <span className="metric-label">Discovered</span>
                      <strong>{metrics.total_discovered}</strong>
                    </div>
                    <div className="metric-card">
                      <span className="metric-label">Eligible</span>
                      <strong>{metrics.eligible}</strong>
                    </div>
                    <div className="metric-card">
                      <span className="metric-label">Inspected</span>
                      <strong>{metrics.inspected} ({coveragePct}%)</strong>
                    </div>
                    <div className="metric-card">
                      <span className="metric-label">Excluded</span>
                      <strong>{metrics.excluded}</strong>
                    </div>
                  </div>
                ) : (
                  <p className="drawer-empty">
                    {report.coverage.inspected_files.length} files inspected; {report.coverage.inspected_symbols.length} symbols inspected.
                  </p>
                )}
                {metrics && Object.keys(metrics.excluded_by_reason).length > 0 && (
                  <div className="exclusion-reasons">
                    <span>Excluded reasons:</span>
                    {Object.entries(metrics.excluded_by_reason).map(([reason, count]) => (
                      <span key={reason} className="agent-chip">
                        {reason}: {count}
                      </span>
                    ))}
                  </div>
                )}
                {report.verification_audit && (
                  <div className="exclusion-reasons">
                    <span>Verification decisions: {report.verification_audit.decisions.length}</span>
                    <span>Duplicate groups: {report.verification_audit.duplicate_groups.length}</span>
                    <span>Disagreements: {report.verification_audit.disagreements.length}</span>
                  </div>
                )}
              </div>
            )
          )}

          {activeTab === 'logs' && (
            events.length === 0 && steps.length === 0 ? (
              <div className="drawer-empty">No live stream events recorded yet.</div>
            ) : (
              <ol className="drawer-log-list">
                {events.slice(-40).reverse().map(ev => {
                  const p = ev.payload as Record<string, unknown>
                  return (
                    <li key={ev.seq}>
                      <span className="log-seq">#{ev.seq}</span>
                      <span className="log-type">{ev.type}</span>
                      {p.agent_id != null && <span className="agent-chip">{String(p.agent_id)}</span>}
                      {p.tool != null && <code>{String(p.tool)}</code>}
                    </li>
                  )
                })}
              </ol>
            )
          )}
        </div>
      )}
    </section>
  )
}

