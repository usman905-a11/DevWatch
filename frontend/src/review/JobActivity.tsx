import { reduceTrajectorySteps, TrajectoryStep } from './durable-events'
import { AgentId, JobView, StreamEvent } from './wire'

export const agentNames: Record<AgentId, string> = {
  planner: 'Planner', bug_reliability: 'Bug & Reliability', logic_correctness: 'Logic & Correctness',
  quality_testability: 'Code Quality & Testability', architecture_security: 'Architecture & Security',
  performance_scalability: 'Performance & Scalability', synthesizer_verifier: 'Synthesizer / Verifier',
}

function renderTrajectoryStep(
  step: TrajectoryStep,
  childrenByParent: Map<number, TrajectoryStep[]>,
  onEvidence?: (reference: string) => void,
) {
  const agentLabel = step.agentName in agentNames ? agentNames[step.agentName as AgentId] : step.agentName
  const children = childrenByParent.get(step.stepIdx) ?? []
  const isSearchOrFile = ['code_search', 'search', 'repo_map', 'read_file'].includes(step.stepType)
  const isCommand = step.stepType === 'run_command'
  const drawerOpen = step.status === 'RUNNING' || step.status === 'ERROR' || (step.exitCode != null && step.exitCode !== 0)

  return (
    <li key={step.stepIdx} className={`trajectory-step status-${step.status.toLowerCase()}`}>
      <div className="trajectory-step-header">
        <span className="step-status-badge">{step.status}</span>
        {' · '}
        <strong>{step.title}</strong>
        {step.subtitle && <span> ({step.subtitle})</span>}
        {' · '}
        <span>{agentLabel}</span>
        {step.durationMs != null && <span className="step-duration-badge"> · {step.durationMs}ms</span>}
      </div>
      {isSearchOrFile && (
        <div className="step-search-meta">
          {step.query && <code className="step-query-pill">{step.query}</code>}
          {step.matchCount != null && (
            <span className="step-match-badge">
              {' '}Found {step.matchCount} matches across {step.files.length} files
            </span>
          )}
          {step.files.length > 0 && (
            <details>
              <summary>Files ({step.files.length})</summary>
              <ul>
                {step.files.map(file => (
                  <li key={file}><code>{file}</code></li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
      {isCommand && (
        <details className="step-terminal-drawer" open={drawerOpen}>
          <summary>
            <code>$ {step.command ?? step.title}</code>
            {step.exitCode != null && <span> · exit {step.exitCode}</span>}
          </summary>
          {step.stdout && <pre className="activity-output" aria-label="step-stdout">{step.stdout}</pre>}
          {step.stderr && <pre className="activity-output" aria-label="step-stderr">{step.stderr}</pre>}
          {step.truncated && (
            <p className="step-truncated-notice">
              [Output truncated at 64KB — view full artifact]
            </p>
          )}
        </details>
      )}
      {(step.status === 'ERROR' || step.errorDetails) && step.errorDetails && (
        <div className="step-error-box" role="alert">
          {step.errorDetails}
        </div>
      )}
      {step.evidenceRef && (
        <div className="step-evidence-actions">
          <code>{step.evidenceRef}</code>
          {onEvidence && (
            <button type="button" className="header-button" onClick={() => onEvidence(step.evidenceRef!)}>
              View tool evidence
            </button>
          )}
        </div>
      )}
      {children.length > 0 && (
        <ol className="trajectory-substeps">
          {children.map(child => renderTrajectoryStep(child, childrenByParent, onEvidence))}
        </ol>
      )}
    </li>
  )
}

export function JobActivity({
  events,
  steps,
  job,
  connection,
  onEvidence,
}: {
  events: StreamEvent[]
  steps?: TrajectoryStep[]
  job: JobView | null
  connection: string
  onEvidence?: (reference: string) => void
}) {
  const latest = events[events.length - 1]
  const latestPayload = (latest?.payload ?? {}) as Record<string, any>
  const latestAgentId = latestPayload.agent_id as AgentId | undefined
  const trajectorySteps = steps ?? reduceTrajectorySteps(events, job?.status)
  const stepIdxSet = new Set(trajectorySteps.map(s => s.stepIdx))
  const childrenByParent = new Map<number, TrajectoryStep[]>()
  const rootSteps: TrajectoryStep[] = []
  for (const step of trajectorySteps) {
    if (step.parentStepIdx != null && stepIdxSet.has(step.parentStepIdx)) {
      const list = childrenByParent.get(step.parentStepIdx) ?? []
      list.push(step)
      childrenByParent.set(step.parentStepIdx, list)
    } else {
      rootSteps.push(step)
    }
  }
  const usageMap = job?.ledger?.agent_usage ?? {}
  const tokens = Object.values(usageMap).reduce((total, usage) => total + (usage?.prompt_tokens ?? 0) + (usage?.completion_tokens ?? 0), 0)
  return <section className="review-progress" aria-label="Agent activity">
    <p role="status" aria-live="polite">Job: {job?.status ?? 'not submitted'} · Connection: {connection}</p>
    {latest && <p>{`${latestAgentId && latestAgentId in agentNames ? agentNames[latestAgentId] : 'Review service'}: ${latest.type}`}</p>}
    {trajectorySteps.length > 0 && (
      <details open>
        <summary>Trajectory steps ({trajectorySteps.length})</summary>
        <ol className="trajectory-step-list">
          {rootSteps.map(step => renderTrajectoryStep(step, childrenByParent, onEvidence))}
        </ol>
      </details>
    )}
    <details><summary>Seven review agents</summary><ul>{Object.entries(agentNames).map(([id, label]) => {
      const activity = [...events].reverse().find(event => (event.payload as Record<string, any>).agent_id === id)
      return <li key={id}>{label}: {activity?.type ?? 'No activity recorded in this window'}</li>
    })}</ul></details>
    <p>Total tokens: {tokens.toLocaleString()}{job?.limits?.job_tokens != null ? ` / ${job.limits.job_tokens.toLocaleString()}` : ' (uncapped)'} · Recorded duration: {(job?.ledger?.elapsed_seconds ?? 0).toFixed(1)}s</p>
    <details><summary>Recent events ({events.length}; up to 200 retained here)</summary><ol>{events.map(event => {
      const p = event.payload as Record<string, any>
      const agentId = p.agent_id as AgentId | undefined
      return <li key={event.seq}>
        <strong>{agentId && agentId in agentNames ? agentNames[agentId] : 'Review service'}</strong> {event.type}
        {p.task_id && <span> · Task: {String(p.task_id)}</span>}
        {p.node && <span> · Node: {String(p.node)}</span>}
        {p.outcome && <span> · Outcome: {String(p.outcome)}</span>}
        {p.tool && <span> · Tool: {String(p.tool)}</span>}
        {p.error_code && <span> · Error: {String(p.error_code)}</span>}
        {p.duration_seconds != null && <span> · {String(p.duration_seconds)}s</span>}
        {p.total_tokens != null && <span> · {String(p.total_tokens)} tokens</span>}
        {p.evidence_ref && <code> · {String(p.evidence_ref)}</code>}
        {p.evidence_ref && onEvidence && <button type="button" className="header-button"
          onClick={() => onEvidence(String(p.evidence_ref))}>View tool evidence</button>}
      </li>
    })}</ol></details>
  </section>
}
