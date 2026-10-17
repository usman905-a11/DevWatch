import { ReportDraft, ReportFinding } from './wire'

export function ReportPanel({ report, onSource }: { report: ReportDraft | null; onSource: (finding: ReportFinding) => void }) {
  return <aside id="review-results" className="agents" aria-label="Code review results" tabIndex={-1}>
    <div className="agent-head"><h1>Review results</h1></div>
    {!report ? <p role="status">Open a job or run a review to see its finalized report.</p> : <>
      <section className="report-overview" aria-label="Report overview"><h2>Report overview</h2><p>{report.summary}</p>
        <p><strong>Snapshot:</strong> <code>{report.snapshot_id}</code></p></section>
      {([
        ['Confirmed defects', report.confirmed_defects],
        ['Uncertain high-impact candidates', report.uncertain_high_impact_candidates],
        ['Advisories', report.advisories],
      ] as const).map(([label, findings]) => <section key={label} aria-label={label}>
        <h2>{label} ({findings.length})</h2>
        {findings.length === 0 && <p>No entries in this group.</p>}
        {findings.map(finding => <article className="finding" key={finding.finding_id}>
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
        </article>)}
      </section>)}
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
