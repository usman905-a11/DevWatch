/** Public service values only. No private state, source mutation or publication action. */
import type {
  AgentId,
  ArithmeticClaim,
  CaptureCoverage,
  CausalReview,
  Coverage,
  JobEvent,
  JobView,
  ReportDraft,
  ReportFinding,
  SnapshotManifest,
  StepRenderInfo,
  StepStatus,
  StepType,
  StepUpdatePayload,
  VerificationAudit,
  VerificationDecision,
} from './api-types'

export type {
  AgentId,
  ArithmeticClaim,
  CaptureCoverage,
  CausalReview,
  Coverage,
  JobEvent,
  JobView,
  ReportDraft,
  ReportFinding,
  SnapshotManifest,
  StepRenderInfo,
  StepStatus,
  StepType,
  StepUpdatePayload,
  VerificationAudit,
  VerificationDecision,
}

export type JobStatus = JobView['status']
export type StreamEvent = JobEvent
export interface SourceExcerpt {
  snapshot_id: string
  snapshot_hash: string
  source_scope: string[]
  tool: 'read_file'
  file_path: string
  start_line: number
  end_line: number
  content_hash: string
  data: string
}

export class ProtocolError extends Error {
  constructor(message = 'Invalid canonical service response') { super(message) }
}
export function identity(value: string): string {
  if (!/^[0-9a-f]{32}$/.test(value)) throw new ProtocolError('Invalid job or snapshot identity')
  return value
}
export function sourcePath(value: string): string {
  const parts = value.split('/')
  if (!value || value.length > 1024 || /[\\:\x00-\x1f]/.test(value) || parts.some(part => !part || part === '.' || part === '..'
    || /[. ]$/.test(part) || /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(part))) {
    throw new ProtocolError('Invalid relative source path')
  }
  return value
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

export function parseJob(data: unknown, expected?: string): JobView {
  if (!isObject(data)) throw new ProtocolError()
  const job = data as unknown as JobView
  identity(job.job_id)
  if (job.snapshot_id != null) identity(job.snapshot_id)
  if (expected && job.job_id !== expected) throw new ProtocolError()
  if (!['queued', 'running', 'interrupted', 'completed', 'failed', 'cancelled'].includes(job.status)
    || job.workflow_version !== 'seven-agent-v1'
    || typeof job.created_at !== 'number' || !Number.isFinite(job.created_at)
    || typeof job.updated_at !== 'number' || !Number.isFinite(job.updated_at)
    || !isObject(job.limits) || !isObject(job.ledger)) {
    throw new ProtocolError()
  }
  const ledger = job.ledger
  for (const counters of [ledger.task_tools, ledger.task_iterations, ledger.task_schema_repairs, ledger.operation_retries]) {
    if (counters && Object.values(counters).some(value => typeof value !== 'number' || value < 0)) throw new ProtocolError()
  }
  return job
}

export function parseReport(data: unknown, snapshotId: string): ReportDraft {
  if (!isObject(data)) throw new ProtocolError()
  const report = data as unknown as ReportDraft
  if (report.snapshot_id !== snapshotId || typeof report.summary !== 'string'
    || !Array.isArray(report.confirmed_defects) || !Array.isArray(report.uncertain_high_impact_candidates)
    || !Array.isArray(report.advisories) || !isObject(report.coverage) || !Array.isArray(report.limitations)) {
    throw new ProtocolError()
  }
  const seen = new Set<string>()
  for (const [findings, kind] of [[report.confirmed_defects, 'defect'], [report.uncertain_high_impact_candidates, 'high_impact_candidate'],
    [report.advisories, 'advisory']] as const) {
    for (const finding of findings) {
      if (!isObject(finding) || !isObject(finding.location)) throw new ProtocolError()
      const location = finding.location
      sourcePath(location.file_path)
      if (location.snapshot_id !== snapshotId || location.end_line < location.start_line || finding.kind !== kind
        || (kind === 'defect' && finding.confidence < .8) || seen.has(finding.finding_id)
        || !Array.isArray(finding.evidence_refs)
        || finding.evidence_refs.some(ref => !/^evidence-[0-9a-f]{64}$/.test(ref))) throw new ProtocolError()
      seen.add(finding.finding_id)
    }
  }
  for (const path of [...(report.coverage.inspected_files ?? []), ...Object.keys(report.coverage.skipped ?? {})]) sourcePath(path)
  // failed keys contain both capture paths and task IDs, not navigation targets.
  return report
}

export function parseSource(data: unknown, snapshotId: string, path: string, start: number, end: number): SourceExcerpt {
  if (!data || typeof data !== 'object' || Array.isArray(data)) throw new ProtocolError()
  const excerpt = data as SourceExcerpt
  if (Object.keys(excerpt).sort().join(',') !== 'content_hash,data,end_line,file_path,snapshot_hash,snapshot_id,source_scope,start_line,tool'
    || excerpt.snapshot_id !== snapshotId || excerpt.file_path !== path || excerpt.start_line !== start || excerpt.end_line !== end
    || excerpt.tool !== 'read_file' || !Array.isArray(excerpt.source_scope) || excerpt.source_scope.length !== 1 || excerpt.source_scope[0] !== path
    || typeof excerpt.data !== 'string' || new TextEncoder().encode(excerpt.data).length > 6000
    || !/^[0-9a-f]{64}$/.test(excerpt.content_hash) || !/^[0-9a-f]{64}$/.test(excerpt.snapshot_hash)) throw new ProtocolError()
  return excerpt
}
