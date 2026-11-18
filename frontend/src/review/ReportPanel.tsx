import { useMemo, useState } from 'react'
import { agentNames } from './JobActivity'
import { AgentId, ReportDraft, ReportFinding } from './wire'

const SEVERITIES = ['all', 'critical', 'high', 'medium', 'low'] as const

export function ReportPanel({ report, onSource }: { report: ReportDraft | null; onSource: (finding: ReportFinding) => void }) {
  const [query, setQuery] = useState('')
  const [severityFilter, setSeverityFilter] = useState<(typeof SEVERITIES)[number]>('all')
  const [agentFilter, setAgentFilter] = useState<'all' | AgentId>('all')

  const provenance = report?.verification_audit?.provenance ?? {}

  const filterFindings = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (items: ReportFinding[]) =>
      items.filter(f => {
        if (severityFilter !== 'all' && f.severity !== severityFilter) return false
        const owner = provenance[f.finding_id]?.agent_id
        if (agentFilter !== 'all' && owner !== agentFilter) return false
        if (
          q &&
          !f.title.toLowerCase().includes(q) &&
          !f.description.toLowerCase().includes(q) &&
          !f.location.file_path.toLowerCase().includes(q) &&
          !f.category.toLowerCase().includes(q)
        ) {
          return false
        }
        return true
      })
  }, [agentFilter, provenance, query, severityFilter])

  return <aside id="review-results" className="agents" aria-label="Code review results" tabIndex={-1}>
    <div className="agent-head"><h1>Review results</h1></div>
    {!report ? <p role="status">Open a job or run a review to see its finalized report.</p> : <>
      <section className="report-overview" aria-label="Report overview"><h2>Report overview</h2><p>{report.summary}</p>
        <p><strong>Snapshot:</strong> <code>{report.snapshot_id}</code></p></section>

      <div className="findings-filter-toolbar" aria-label="Findings filters">
        <input
          type="search"
          aria-label="Filter findings"
          placeholder="Filter findings by file, rule, text..."
          value={query}
          onChange={e => setQuery(e.target.value)}
        />
        <div className="severity-filter-row" role="group" aria-label="Severity filter">
          <span>Severity:</span>
          {SEVERITIES.map(sev => (
            <button
              key={sev}
              type="button"
              className={`filter-chip ${severityFilter === sev ? 'active' : ''}`}
              aria-pressed={severityFilter === sev}
              onClick={() => setSeverityFilter(sev)}
            >
              {sev === 'all' ? 'All' : sev}
            </button>
          ))}
        </div>
        <label className="agent-filter-select">
          <span>Agent</span>
          <select value={agentFilter} onChange={e => setAgentFilter(e.target.value as 'all' | AgentId)}>
            <option value="all">All agents</option>
            {(Object.keys(agentNames) as AgentId[]).map(id => (
              <option key={id} value={id}>{agentNames[id]}</option>
            ))}
          </select>
        </label>
      </div>

      {([
        ['Confirmed defects', report.confirmed_defects],
        ['Uncertain high-impact candidates', report.uncertain_high_impact_candidates],
        ['Advisories', report.advisories],
      ] as const).map(([label, findings]) => {
        const filtered = filterFindings(findings)
        return <section key={label} aria-label={label}>
          <h2>{label} ({filtered.length}{filtered.length !== findings.length ? ` of ${findings.length}` : ''})</h2>
          {filtered.length === 0 && <p>No entries in this group.</p>}
          {filtered.map(finding => {
            const ownerAgent = provenance[finding.finding_id]?.agent_id
            return <article className={`finding severity-border-${finding.severity}`} key={finding.finding_id}>
              <div className="finding-meta-row">
                <span className={`severity-pill severity-${finding.severity}`}>{finding.severity}</span>
                <span className="agent-chip">{finding.category}</span>
                {ownerAgent && <span className="agent-chip">{agentNames[ownerAgent] ?? ownerAgent}</span>}
                <span className="confidence-chip">{Math.round(finding.confidence * 100)}%</span>
              </div>
              <span className="location">{finding.location.file_path}:{finding.location.start_line}–{finding.location.end_line}</span>
              <h3>{finding.title}</h3><p>{finding.description}</p>
              <p><strong>Impact:</strong> {finding.impact}</p>
              <button className="header-button" type="button" onClick={() => onSource(finding)}>Open source</button>
              <details><summary>Evidence and guidance</summary><div className="finding-detail">
                <p><strong>Confidence:</strong> {Math.round(finding.confidence * 100)}%</p>
                <p><strong>Verification rationale:</strong> {finding.verification_rationale}</p>
                <ul>{finding.evidence_refs.map(ref => <li key={ref}><code>{ref}</code></li>)}</ul>
                <p><strong>Remediation:</strong> {finding.remediation || 'No remediation supplied.'}</p>
                <p>Guidance only. Reviewed source stays read-only.</p>
              </div></details>
            </article>
          })}
        </section>
      })}
      <section aria-label="Review coverage"><h2>Review coverage</h2>
        <p>{report.coverage.inspected_files.length} files inspected; {report.coverage.inspected_symbols.length} symbols inspected.</p>
        <details><summary>Inspected files and symbols</summary><ul>{report.coverage.inspected_files.map(path => <li key={path}>{path}</li>)}
          {report.coverage.inspected_symbols.map(symbol => <li key={'symbol:' + symbol}>{symbol}</li>)}</ul></details>
        {(['skipped', 'failed'] as const).map(kind => <div key={kind}><h3>{kind === 'skipped' ? 'Skipped' : 'Failed'} ({Object.keys(report.coverage[kind]).length})</h3>
          <ul>{Object.entries(report.coverage[kind]).map(([key, reason]) => <li key={key}>{key}: {reason}</li>)}</ul></div>)}
        <h3>Limitations</h3><ul>{Array.from(new Set([...report.coverage.limitations, ...report.limitations])).map(text => <li key={text}>{text}</li>)}</ul>
      </section>
    </>}
  </aside>
}
