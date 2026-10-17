import { AgentStepUpdate } from '../types'

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
  replacement_code?: string
  finding_id?: string
  verification_status?: string
  cwe_id?: string
  confidence_score?: number
}

interface Props {
  analysisRunning: boolean
  analysisComplete: boolean
  onFindingClick: (f: Finding) => void
  findings: Finding[]
  manualReviewCandidates: Finding[]
  progressSteps: AgentStepUpdate[]
  reviewError: string | null
  partial: boolean
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
  needsReview = false,
}: {
  finding: Finding
  onClick: () => void
  needsReview?: boolean
}) {
  return (
    <button
      type="button"
      className={`finding ${severityMap[finding.severity]}`}
      onClick={onClick}
    >
      <span className="finding-top">
        <span className="severity-pill">{finding.severity}</span>
        <span className="location">{finding.fileName}:{finding.line}</span>
      </span>
      {needsReview && <span className="review-label">Needs manual review</span>}
      <span className="finding-title">{finding.title}</span>
      <span className="finding-description">{finding.description}</span>
      {finding.suggestion && (
        <span className="finding-recommendation">Recommendation: {finding.suggestion}</span>
      )}
    </button>
  )
}

export default function AgentPanel({
  analysisRunning,
  analysisComplete,
  onFindingClick,
  findings = [],
  manualReviewCandidates = [],
  progressSteps = [],
  reviewError,
  partial,
}: Props) {
  const recentSteps = progressSteps.slice(-3)

  return (
    <aside className="agents" aria-label="Code review results">
      <div className="agent-head">
        <div>
          <span className="eyebrow">Code review</span>
          <h1>Confirmed findings ({findings.length})</h1>
        </div>
        <span className={`scan-status ${analysisRunning ? 'scanning' : analysisComplete ? 'complete' : ''}`}>
          {analysisRunning ? 'Reviewing' : reviewError ? 'Failed' : partial ? 'Partial' : analysisComplete ? 'Complete' : 'Ready'}
        </span>
      </div>

      {analysisRunning && (
        <div className="review-progress" role="status" aria-live="polite">
          <strong>Review in progress</strong>
          {recentSteps.length === 0 && <p>Preparing review...</p>}
          {recentSteps.map((step, index) => (
            <p key={`${step.agent_name}-${index}`}>
              <span>{step.agent_name}{step.specialist ? ` - ${step.specialist}` : ''}</span>
              <span>{step.message}</span>
              {step.elapsed_ms != null && (
                <small>{(step.elapsed_ms / 1000).toFixed(1)}s elapsed</small>
              )}
            </p>
          ))}
        </div>
      )}

      {reviewError && <div className="review-error" role="alert">Review failed: {reviewError}</div>}
      {analysisComplete && partial && (
        <div className="review-partial" role="status">
          Partial review: some analysis stages failed. Confirmed findings below passed verification.
        </div>
      )}

      <div className="finding-list">
        {!analysisComplete && !analysisRunning && !reviewError && (
          <div className="review-blank">
            <strong>Review findings</strong>
            <p>Run a review to inspect confirmed findings and manual review candidates.</p>
          </div>
        )}

        {analysisRunning && recentSteps.length === 0 && (
          <div className="skeleton" aria-hidden="true" />
        )}

        {analysisComplete && findings.length === 0 && manualReviewCandidates.length === 0 && (
          <div className="review-blank">
            <strong>No confirmed findings</strong>
            <p>The review did not confirm any issues in the selected source.</p>
          </div>
        )}

        {analysisComplete && findings.map((finding) => (
          <Card key={finding.id} finding={finding} onClick={() => onFindingClick(finding)} />
        ))}

        {analysisComplete && manualReviewCandidates.length > 0 && (
          <section className="manual-review" aria-label="Manual review candidates">
            <h2>Manual review ({manualReviewCandidates.length})</h2>
            <p>These candidates need a person to check the evidence.</p>
            {manualReviewCandidates.map((finding) => (
              <Card
                key={finding.id}
                finding={finding}
                needsReview
                onClick={() => onFindingClick(finding)}
              />
            ))}
          </section>
        )}
      </div>

      {analysisComplete && (
        <div className="summary">
          {(['critical', 'high', 'medium', 'low'] as Severity[]).map((severity) => {
            const count = findings.filter((finding) => finding.severity === severity).length
            return count ? (
              <span key={severity} className={severity}>
                <i />
                {count} {severity}
              </span>
            ) : null
          })}
          {manualReviewCandidates.length > 0 && (
            <span>{manualReviewCandidates.length} to review</span>
          )}
        </div>
      )}
    </aside>
  )
}
