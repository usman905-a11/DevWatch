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

export function JobActivity({ events, job, connection, onEvidence }: { events: StreamEvent[]; job: JobView | null; connection: string;
  onEvidence?: (reference: string) => void }) {
  const latest = events[events.length - 1]
  const legacy = events.filter((event): event is PersistedEvent => 'kind' in event)
  const activities = visibleActivities(events)
  const tokens = job ? Object.values(job.ledger.agent_usage).reduce((total, usage) => total + (usage?.prompt_tokens ?? 0) + (usage?.completion_tokens ?? 0), 0) : 0
  return <section className="review-progress" aria-label="Agent activity">
    <p role="status" aria-live="polite">Job: {job?.status ?? 'not submitted'} · Connection: {connection}</p>
    {latest && <p>{'type' in latest ? `${latest.activityType.replace(/_/g, ' ')}: ${latest.type}`
      : `${latest.payload.agent_id ? agentNames[latest.payload.agent_id] : 'Review service'}: ${latest.kind}`}</p>}
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
