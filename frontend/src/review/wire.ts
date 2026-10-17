/** Public service values only. No private state, source mutation or publication action. */
import schema from './wire-schema.json'

export type AgentId = 'planner' | 'bug_reliability' | 'logic_correctness' | 'quality_testability'
  | 'architecture_security' | 'performance_scalability' | 'synthesizer_verifier'
export type JobStatus = 'queued' | 'running' | 'interrupted' | 'completed' | 'failed' | 'cancelled'
export interface Coverage {
  inspected_files: string[]; inspected_symbols: string[]; skipped: Record<string, string>
  failed: Record<string, string>; limitations: string[]
}
export type CaptureCoverage = Pick<Coverage, 'skipped' | 'failed' | 'limitations'>
export interface SnapshotManifest {
  snapshot_id: string; owner: string; content_hash: string; capture_hash: string
  entries: Record<string, { content_hash: string; byte_count: number; line_count: number }>
  capture_coverage: CaptureCoverage
  git_hash: string
  git_metadata: { diffs: Record<string, { staged: string; unstaged: string }>; history: Record<string, string[]>; limitations: string[] }
}
export interface JobView {
  job_id: string; snapshot_id: string; status: JobStatus; workflow_version: 'seven-agent-v1'
  created_at: number; updated_at: number
  limits: Record<string, number>
  ledger: { review_round: number; agent_usage: Partial<Record<AgentId, { prompt_tokens: number; completion_tokens: number }>>
    inflight: Record<string, { agent_id: AgentId; tokens: number }>; elapsed_seconds: number
    task_iterations: Record<string, number>; task_tools: Record<string, number>
    task_schema_repairs: Record<string, number>; operation_retries: Record<string, number> }
}
export interface ReportFinding {
  finding_id: string; category: string; kind: 'defect' | 'high_impact_candidate' | 'advisory'
  title: string; description: string; impact: string; confidence: number; remediation: string
  location: { snapshot_id: string; file_path: string; start_line: number; end_line: number }
  evidence_refs: string[]; verification_rationale: string
}
export interface ReportDraft {
  snapshot_id: string; summary: string; confirmed_defects: ReportFinding[]
  uncertain_high_impact_candidates: ReportFinding[]; advisories: ReportFinding[]
  coverage: Coverage; limitations: string[]
}
export interface PersistedEvent {
  event_id: string; job_id: string; sequence: number; kind: string; timestamp: number
  payload: { status: JobStatus | null; agent_id: AgentId | null; task_id: string | null
    tool: string | null; evidence_ref: string | null; error_code: string | null
    duration_seconds: number | null; total_tokens: number | null
    phase?: string | null; iteration?: number | null; attempt?: number | null
    run_id?: string | null; operation_id?: string | null; outcome?: string | null
    stop_reason?: string | null; finish_reason?: string | null; count?: number | null
    finding_id?: string | null; verdict?: string | null; offset?: number | null; end_offset?: number | null }
}
export interface SourceExcerpt {
  snapshot_id: string; snapshot_hash: string; source_scope: string[]; tool: 'read_source'
  file_path: string; start_line: number; end_line: number; content_hash: string; data: string
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

/** Validates only the JSON Schema keywords exported by these non-recursive models. */
type Schema = Record<string, any>
function matchesPattern(pattern: string, value: string): boolean {
  // Pydantic's Rust regex uses Unicode word characters; JS \w is ASCII-only.
  if (pattern === '^[\\w.-]+$') return /^[\p{Alphabetic}\p{M}\p{Nd}\p{Pc}\u200c\u200d.-]+$/u.test(value)
  return new RegExp(pattern, 'u').test(value)
}
export function validateWire<T>(name: string, data: unknown): T {
  const definitions = schema.$defs as Record<string, Schema>
  let nodes = 0
  function check(rule: Schema, value: unknown, depth = 0): boolean {
    if (++nodes > 100000 || depth > 32) throw new ProtocolError('Response structure limit exceeded')
    if (rule.$ref) return check(definitions[rule.$ref.split('/').pop()], value, depth + 1)
    if (rule.anyOf) return rule.anyOf.some((choice: Schema) => check(choice, value, depth + 1))
    if (rule.enum && !rule.enum.includes(value)) return false
    if ('const' in rule && value !== rule.const) return false
    switch (rule.type) {
      case 'null': return value === null
      case 'boolean': return typeof value === 'boolean'
      case 'string': return typeof value === 'string' && Array.from(value).length >= (rule.minLength ?? 0)
        && Array.from(value).length <= (rule.maxLength ?? Infinity) && (!rule.pattern || matchesPattern(rule.pattern, value))
      case 'integer': case 'number': return typeof value === 'number' && Number.isFinite(value)
        && (rule.type !== 'integer' || Number.isSafeInteger(value)) && value >= (rule.minimum ?? -Infinity)
        && value <= (rule.maximum ?? Infinity)
      case 'array': return Array.isArray(value) && value.length >= (rule.minItems ?? 0)
        && value.length <= (rule.maxItems ?? Infinity) && value.every(item => check(rule.items, item, depth + 1))
      case 'object': {
        if (value === null || typeof value !== 'object' || Array.isArray(value)) return false
        const object = value as Record<string, unknown>, properties = rule.properties ?? {}
        const keys = Object.keys(object)
        const has = (object: object, key: string) => Object.prototype.hasOwnProperty.call(object, key)
        if (keys.length > (rule.maxProperties ?? Infinity) || (rule.required ?? []).some((key: string) => !has(object, key))) return false
        return keys.every(key => (!rule.propertyNames || check(rule.propertyNames, key, depth + 1)) && (has(properties, key) ? check(properties[key], object[key], depth + 1)
          : rule.additionalProperties === false ? false
          : typeof rule.additionalProperties === 'object' ? check(rule.additionalProperties, object[key], depth + 1) : true))
      }
      default: throw new ProtocolError('Unsupported wire schema')
    }
  }
  if (!definitions[name] || !check(definitions[name], data)) throw new ProtocolError()
  return data as T
}

export function parseJob(data: unknown, expected?: string): JobView {
  const job = validateWire<JobView>('JobView', data)
  if (expected && job.job_id !== expected) throw new ProtocolError()
  for (const counters of [job.ledger.task_tools, job.ledger.task_iterations, job.ledger.task_schema_repairs, job.ledger.operation_retries]) {
    if (Object.values(counters).some(value => value < 0)) throw new ProtocolError()
  }
  return job
}

export function parseReport(data: unknown, snapshotId: string): ReportDraft {
  const report = validateWire<ReportDraft>('ReportDraft', data)
  if (report.snapshot_id !== snapshotId) throw new ProtocolError()
  const seen = new Set<string>()
  for (const [findings, kind] of [[report.confirmed_defects, 'defect'], [report.uncertain_high_impact_candidates, 'high_impact_candidate'],
    [report.advisories, 'advisory']] as const) {
    for (const finding of findings) {
      const location = finding.location
      sourcePath(location.file_path)
      if (location.snapshot_id !== snapshotId || location.end_line < location.start_line || finding.kind !== kind
        || (kind === 'defect' && finding.confidence < .8) || seen.has(finding.finding_id)
        || finding.evidence_refs.some(ref => !/^evidence-[0-9a-f]{64}$/.test(ref))) throw new ProtocolError()
      seen.add(finding.finding_id)
    }
  }
  for (const path of [...report.coverage.inspected_files, ...Object.keys(report.coverage.skipped)]) sourcePath(path)
  // failed keys contain both capture paths and task IDs, not navigation targets.
  return report
}

export function parseSource(data: unknown, snapshotId: string, path: string, start: number, end: number): SourceExcerpt {
  if (!data || typeof data !== 'object' || Array.isArray(data)) throw new ProtocolError()
  const excerpt = data as SourceExcerpt
  if (Object.keys(excerpt).sort().join(',') !== 'content_hash,data,end_line,file_path,snapshot_hash,snapshot_id,source_scope,start_line,tool'
    || excerpt.snapshot_id !== snapshotId || excerpt.file_path !== path || excerpt.start_line !== start || excerpt.end_line !== end
    || excerpt.tool !== 'read_source' || !Array.isArray(excerpt.source_scope) || excerpt.source_scope.length !== 1 || excerpt.source_scope[0] !== path
    || typeof excerpt.data !== 'string' || new TextEncoder().encode(excerpt.data).length > 6000
    || !/^[0-9a-f]{64}$/.test(excerpt.content_hash) || !/^[0-9a-f]{64}$/.test(excerpt.snapshot_hash)) throw new ProtocolError()
  return excerpt
}
