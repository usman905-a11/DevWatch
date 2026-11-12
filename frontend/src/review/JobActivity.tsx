import { reduceTrajectorySteps, TrajectoryStep } from './durable-events'
import { ActivityEvent, AgentId, JobView, PersistedEvent, StreamEvent } from './wire'

export const agentNames: Record<AgentId, string> = {
  planner: 'Planner', bug_reliability: 'Bug & Reliability', logic_correctness: 'Logic & Correctness',
  quality_testability: 'Code Quality & Testability', architecture_security: 'Architecture & Security',
  performance_scalability: 'Performance & Scalability', synthesizer_verifier: 'Synthesizer / Verifier',
}

type ActivityRow = { last: ActivityEvent; text: string; stdout: string; stderr: string; agentId?: string; final?: ActivityEvent }

function visibleActivities(events: StreamEvent[]): ActivityRow[] {
  const rows = new Map<string, ActivityRow>()
  for (const event of events) {
    if (!('type' in event)) continue
    let row = rows.get(event.activityId)
    if (!row) {
      row = { last: event, text: '', stdout: '', stderr: '', agentId: event.data.agentId }
      rows.set(event.activityId, row)
    }
    if (row.final) continue
    row.last = event
    if (event.type === 'activity.delta') {
      row.text += event.data.text ?? ''
      row.stdout += event.data.stdout ?? ''
      row.stderr += event.data.stderr ?? ''
    } else if (event.type !== 'activity.started') {
      row.final = event
    }
  }
  return [...rows.values()]
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
  const legacy = events.filter((event): event is PersistedEvent => 'kind' in event)
  const activities = visibleActivities(events)
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
  const tokens = job ? Object.values(job.ledger.agent_usage).reduce((total, usage) => total + (usage?.prompt_tokens ?? 0) + (usage?.completion_tokens ?? 0), 0) : 0
  return <section className="review-progress" aria-label="Agent activity">
    <p role="status" aria-live="polite">Job: {job?.status ?? 'not submitted'} · Connection: {connection}</p>
    {latest && <p>{'type' in latest ? `${latest.activityType.replace(/_/g, ' ')}: ${latest.type}`
      : `${latest.payload.agent_id ? agentNames[latest.payload.agent_id] : 'Review service'}: ${latest.kind}`}</p>}
    {trajectorySteps.length > 0 && (
      <details open>
        <summary>Trajectory steps ({trajectorySteps.length})</summary>
        <ol className="trajectory-step-list">
          {rootSteps.map(step => renderTrajectoryStep(step, childrenByParent, onEvidence))}
        </ol>
      </details>
    )}
    <details open={activities.length > 0}><summary>Live activities ({activities.length})</summary><ol>{activities.map(row => {
      const event = row.final ?? row.last
      const data = event.data
      const text = row.final ? data.text ?? row.text : row.text
      const stdout = row.final ? data.stdout ?? row.stdout : row.stdout
      const stderr = row.final ? data.stderr ?? row.stderr : row.stderr
      return <li key={event.activityId}>
        <strong>{event.activityType.replace(/_/g, ' ')}</strong> · {event.type.split('.')[1]} · {row.agentId && row.agentId in agentNames
          ? agentNames[row.agentId as AgentId] : `Agent run ${event.agentRunId}`}
        {data.path && <span> · {data.path}</span>}{data.tool && <span> · {data.tool}</span>}
        {data.errorCode && <span> · Error: {data.errorCode}</span>}
        {text && <pre className="activity-output">{text}</pre>}
        {stdout && <pre className="activity-output" aria-label="stdout">{stdout}</pre>}
        {stderr && <pre className="activity-output" aria-label="stderr">{stderr}</pre>}
        {data.evidenceRef && <code> · {data.evidenceRef}</code>}
        {data.evidenceRef && onEvidence && <button type="button" className="header-button"
          onClick={() => onEvidence(data.evidenceRef!)}>View tool evidence</button>}
      </li>
    })}</ol></details>
    <details><summary>Seven review agents</summary><ul>{Object.entries(agentNames).map(([id, label]) => {
      const activity = [...legacy].reverse().find(event => event.payload.agent_id === id)
      return <li key={id}>{label}: {activity?.kind ?? 'No activity recorded in this window'}</li>
    })}</ul></details>
    <p>Total tokens: {tokens.toLocaleString()} / {job?.limits.job_tokens ?? 250000} · Recorded duration: {job?.ledger.elapsed_seconds.toFixed(1) ?? '0.0'}s</p>
    <details><summary>Recent events ({events.length}; up to 200 retained here)</summary><ol>{legacy.map(event => <li key={event.event_id}>
      <strong>{event.payload.agent_id ? agentNames[event.payload.agent_id] : 'Review service'}</strong> {event.kind}
      {event.payload.task_id && <span> · Task: {event.payload.task_id}</span>}
      {event.payload.node && <span> · Node: {event.payload.node}</span>}
      {event.payload.outcome && <span> · Outcome: {event.payload.outcome}</span>}
      {event.payload.tool && <span> · Tool: {event.payload.tool}</span>}
      {event.payload.error_code && <span> · Error: {event.payload.error_code}</span>}
      {event.payload.duration_seconds != null && <span> · {event.payload.duration_seconds}s</span>}
      {event.payload.total_tokens != null && <span> · {event.payload.total_tokens} tokens</span>}
      {event.payload.evidence_ref && <code> · {event.payload.evidence_ref}</code>}
      {event.payload.evidence_ref && onEvidence && <button type="button" className="header-button"
        onClick={() => onEvidence(event.payload.evidence_ref!)}>View tool evidence</button>}
    </li>)}</ol></details>
  </section>
}
