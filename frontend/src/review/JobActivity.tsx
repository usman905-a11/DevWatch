import { AgentId, JobView, PersistedEvent } from './wire'

export const agentNames: Record<AgentId, string> = {
  planner: 'Planner', bug_reliability: 'Bug & Reliability', logic_correctness: 'Logic & Correctness',
  quality_testability: 'Code Quality & Testability', architecture_security: 'Architecture & Security',
  performance_scalability: 'Performance & Scalability', synthesizer_verifier: 'Synthesizer / Verifier',
}
export function JobActivity({ events, job, connection, onEvidence }: { events: PersistedEvent[]; job: JobView | null; connection: string;
  onEvidence?: (reference: string) => void }) {
  const latest = events[events.length - 1]
  const tokens = job ? Object.values(job.ledger.agent_usage).reduce((total, usage) => total + (usage?.prompt_tokens ?? 0) + (usage?.completion_tokens ?? 0), 0) : 0
  return <section className="review-progress" aria-label="Agent activity">
    <p role="status" aria-live="polite">Job: {job?.status ?? 'not submitted'} · Connection: {connection}</p>
    {latest && <p>{latest.payload.agent_id ? agentNames[latest.payload.agent_id] : 'Review service'}: {latest.kind}
      {latest.payload.task_id && <> · Task {latest.payload.task_id}</>}{latest.payload.tool && <> · Tool {latest.payload.tool}</>}</p>}
    <details><summary>Seven review agents</summary><ul>{Object.entries(agentNames).map(([id, label]) => {
      const activity = [...events].reverse().find(event => event.payload.agent_id === id)
      return <li key={id}>{label}: {activity?.kind ?? 'No activity recorded in this window'}</li>
    })}</ul></details>
    <p>Total tokens: {tokens.toLocaleString()} / {job?.limits.job_tokens ?? 250000} · Recorded duration: {job?.ledger.elapsed_seconds.toFixed(1) ?? '0.0'}s</p>
    <details><summary>Recent events ({events.length}; up to 200 retained here)</summary><ol>{events.map(event => <li key={event.event_id}>
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
