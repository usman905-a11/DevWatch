import { useState } from 'react'

export type AgentId = 'bugs' | 'quality' | 'security'
export type Severity = 'critical' | 'high' | 'medium' | 'low'

export interface Finding {
  id: string
  agent: AgentId
  severity: Severity
  title: string
  description: string
  fileId: string
  fileName: string
  line: number
  suggestion?: string
}

interface Props {
  analysisRunning: boolean
  analysisComplete: boolean
  onFindingClick: (f: Finding) => void
  onApplyFix?: (f: Finding) => void
  findings: Finding[]
}

const severityMap: Record<Severity, string> = {
  critical: 'critical',
  high: 'high',
  medium: 'medium',
  low: 'low',
}

function Card({
  finding,
  onClick,
  onApplyFix,
}: {
  finding: Finding
  onClick: () => void
  onApplyFix?: (f: Finding) => void
}) {
  const [open, setOpen] = useState(false)
  const [fixing, setFixing] = useState(false)

  const handleFixClick = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!onApplyFix) return
    setFixing(true)
    try {
      await onApplyFix(finding)
    } finally {
      setFixing(false)
    }
  }

  return (
    <article className={`finding ${severityMap[finding.severity]}`} onClick={onClick}>
      <div className="finding-top">
        <span className="severity-pill">{finding.severity}</span>
        <span className="location">
          {finding.fileName}:{finding.line}
        </span>
      </div>
      <h3>{finding.title}</h3>
      <p>{finding.description}</p>
      
      <button
        className="fix-toggle"
        onClick={(e) => {
          e.stopPropagation()
          setOpen(!open)
        }}
      >
        {open ? '− Hide suggestion' : '+ Suggested fix'}
      </button>
      
      {open && (
        <>
          <pre>{finding.suggestion || 'Apply recommended refactoring fix.'}</pre>
          {onApplyFix && (
            <button className="apply-fix-btn" onClick={handleFixClick} disabled={fixing}>
              {fixing ? 'Applying...' : '⚡ Apply Quick Fix'}
            </button>
          )}
        </>
      )}
    </article>
  )
}

export default function AgentPanel({
  analysisRunning,
  analysisComplete,
  onFindingClick,
  onApplyFix,
  findings = [],
}: Props) {
  return (
    <aside className="agents">
      <div className="agent-head">
        <div>
          <span className="eyebrow">Code review</span>
          <h1>Findings ({findings.length})</h1>
        </div>
        <span className={`scan-status ${analysisRunning ? 'scanning' : analysisComplete ? 'complete' : ''}`}>
          {analysisRunning ? 'Scanning' : analysisComplete ? 'Complete' : 'Ready'}
        </span>
      </div>

      <div className="finding-list">
        {!analysisComplete && !analysisRunning && (
          <div className="review-blank">
            <span>⚡</span>
            <strong>Review Findings</strong>
            <p>Run a review to surface signals that deserve your attention.</p>
          </div>
        )}
        
        {analysisRunning &&
          [1, 2, 3].map((i) => (
            <div key={i} className="skeleton" style={{ animationDelay: `${i * 80}ms` }} />
          ))}

        {analysisComplete && findings.length === 0 && (
          <div className="review-blank">
            <span>✓</span>
            <strong>No Issues Found</strong>
            <p>Your codebase passed all multi-agent auditing checks!</p>
          </div>
        )}

        {analysisComplete &&
          findings.map((f) => (
            <Card key={f.id} finding={f} onClick={() => onFindingClick(f)} onApplyFix={onApplyFix} />
          ))}
      </div>

      {analysisComplete && (
        <div className="summary">
          {(['critical', 'high', 'medium', 'low'] as Severity[]).map((s) => {
            const n = findings.filter((f) => f.severity === s).length
            return n ? (
              <span key={s} className={s}>
                <i />
                {n} {s}
              </span>
            ) : null
          })}
        </div>
      )}
    </aside>
  )
}
