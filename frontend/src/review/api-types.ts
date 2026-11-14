/* eslint-disable */
// Auto-generated from FastAPI OpenAPI / Pydantic schemas by scripts/generate_api_types.py

export type AgentId = 'planner' | 'bug_reliability' | 'logic_correctness' | 'quality_testability' | 'architecture_security' | 'performance_scalability' | 'synthesizer_verifier'

export interface ArithmeticCheck {
  status: 'supported' | 'contradicted' | 'unknown'
  checked_assignments: number
  counterexample?: Record<string, number> | null
  reason: string
}

export interface ArithmeticClaim {
  field: 'title' | 'description' | 'impact' | 'remediation'
  expression: string
  variables: Record<string, IntegerRange>
}

export interface ArithmeticCounterexample {
  claim_index: number
  point: Record<string, number>
}

export interface ArithmeticReceipt {
  candidate_digest: string
  claim_index: number
  field: 'title' | 'description' | 'impact' | 'remediation'
  statement: string
  result: ArithmeticCheck
}

export interface BalancedLimits {
  review_seconds: number
  job_tokens: number
  planner_output_tokens: number
  concurrent_model_calls: number
  iterations_per_task: number
  tool_calls_per_task: number
  review_rounds: number
  transient_retries: number
  schema_repairs_per_task: number
  provider_timeout_seconds: number
  command_timeout_seconds: number
  model_context_tokens: number
}

export interface BudgetLedger {
  review_round: number
  agent_usage: Record<string, TokenUsage>
  inflight: Record<string, ModelReservation>
  task_iterations: Record<string, number>
  task_tools: Record<string, number>
  task_schema_repairs: Record<string, number>
  operation_retries: Record<string, number>
  elapsed_seconds: number
}

export interface CaptureCoverage {
  skipped: Record<string, string>
  failed: Record<string, string>
  limitations: string[]
}

export interface CausalReview {
  candidate_digest: string
  causal_basis: string
  assessments: ClaimAssessment[]
}

export interface ClaimAssessment {
  field: 'title' | 'description' | 'impact' | 'remediation'
  status: 'supported' | 'unsupported' | 'uncertain'
  explanation: string
  evidence_refs: string[]
}

export interface Coverage {
  inspected_files: string[]
  inspected_symbols: string[]
  skipped: Record<string, string>
  failed: Record<string, string>
  limitations: string[]
}

export interface Disagreement {
  finding_ids: string[]
  rationale: string
  evidence_refs: string[]
  resolution: 'resolved' | 'unresolved'
}

export interface DuplicateReview {
  finding_ids: string[]
  rationale: string
  evidence_refs: string[]
}

export interface EventsResponse {
  events: JobEvent[]
  next_cursor: number
}

export interface FollowupRequest {
  task_id: string
  question: string
  evidence_needed: string
}

export interface FsEntryModel {
  name: string
  path: string
  type: 'file' | 'dir'
  size: number
  isSymlink: boolean
  ignored: boolean
}

export interface FsListResponse {
  root: string
  path: string
  entries: FsEntryModel[]
}

export interface FsReadResponse {
  path: string
  size: number
  binary: boolean
  tooLarge: boolean
  maxBytes: number
  lineCount?: number | null
  content?: string | null
}

export interface GitMetadata {
  diffs: Record<string, Record<string, string>>
  history: Record<string, string[]>
  limitations: string[]
}

export interface HTTPValidationError {
  detail: ValidationError[]
}

export interface HealthResponse {
  status: string
  workflow_version: "seven-agent-v1"
}

export interface IntegerRange {
  start: number
  stop: number
  step: number
}

export interface JobEvent {
  job_id: string
  seq: number
  type: string
  payload: Record<string, unknown>
  timestamp: number
}

export interface JobRequest {
  snapshot_id?: string | null
  workspace_path?: string | null
  changed_files?: string[] | null
  context_files?: string[] | null
}

export type JobStatus = 'queued' | 'running' | 'interrupted' | 'completed' | 'failed' | 'cancelled'

export interface JobView {
  job_id: string
  snapshot_id?: string | null
  workspace_path?: string | null
  status: 'queued' | 'running' | 'interrupted' | 'completed' | 'failed' | 'cancelled'
  workflow_version: "seven-agent-v1"
  ledger: BudgetLedger
  limits: BalancedLimits
  created_at: number
  updated_at: number
}

export interface ModelReservation {
  agent_id: AgentId
  tokens: number
}

export interface ReportDraft {
  snapshot_id: string
  summary: string
  confirmed_defects: ReportFinding[]
  uncertain_high_impact_candidates: ReportFinding[]
  advisories: ReportFinding[]
  coverage: Coverage
  limitations: string[]
  verification_audit?: VerificationAudit | null
}

export interface ReportFinding {
  category: string
  kind: 'defect' | 'high_impact_candidate' | 'advisory'
  title: string
  description: string
  impact: string
  confidence: number
  location: SourceLocation
  evidence_refs: string[]
  remediation: string
  arithmetic_claims: ArithmeticClaim[]
  finding_id: string
  verification_rationale: string
}

export interface ReviewObservation {
  pass_number: 1 | 2
  decision: VerificationDecision
}

export interface SnapshotManifest {
  snapshot_id: string
  owner: string
  content_hash: string
  entries: Record<string, SourceEntry>
  capture_coverage: CaptureCoverage
  capture_hash: string
  git_metadata: GitMetadata
  git_hash: string
}

export interface SnapshotRequest {
  files: Record<string, string>
  capture_coverage: CaptureCoverage
  git_metadata: GitMetadata
}

export interface SourceEntry {
  content_hash: string
  byte_count: number
  line_count: number
}

export interface SourceLocation {
  snapshot_id: string
  file_path: string
  start_line: number
  end_line: number
}

export interface SpecialistProvenance {
  task_id: string
  agent_id: AgentId
}

export interface StepRenderInfo {
  title?: string | null
  subtitle?: string | null
  agent_name?: string | null
  command?: string | null
  args_preview?: Record<string, string | number | boolean | null> | null
  stdout_append?: string | null
  stderr_append?: string | null
  exit_code?: number | null
  truncated?: boolean | null
  output_truncated?: boolean | null
  query?: string | null
  files?: string[] | null
  match_count?: number | null
  evidence_ref?: string | null
  duration_ms?: number | null
}

export type StepStatus = 'RUNNING' | 'DONE' | 'ERROR' | 'CANCELING'

export type StepType = 'agent_run' | 'subagent' | 'planner' | 'run_command' | 'code_search' | 'repo_map' | 'search' | 'read_file' | 'tool' | 'system'

export interface StepUpdatePayload {
  step_idx: number
  parent_step_idx?: number | null
  agent_name?: string | null
  step_type: 'agent_run' | 'subagent' | 'planner' | 'run_command' | 'code_search' | 'repo_map' | 'search' | 'read_file' | 'tool' | 'system'
  status: 'RUNNING' | 'DONE' | 'ERROR' | 'CANCELING'
  delta_seq: number
  render_info: StepRenderInfo
  error_details?: string | null
}

export interface TokenUsage {
  prompt_tokens: number
  completion_tokens: number
}

export interface ValidationError {
  loc: (string | number)[]
  msg: string
  type: string
  input: unknown
  ctx: Record<string, unknown>
}

export interface VerificationAudit {
  decisions: VerificationDecision[]
  duplicate_groups: string[][]
  conflicts: string[]
  followup_requests: FollowupRequest[]
  duplicate_reviews: DuplicateReview[]
  disagreements: Disagreement[]
  review_observations: ReviewObservation[]
  provenance: Record<string, SpecialistProvenance>
  arithmetic_checks: Record<string, ArithmeticReceipt[]>
}

export interface VerificationDecision {
  finding_id: string
  verdict: 'confirmed' | 'uncertain' | 'rejected' | 'advisory'
  confidence: number
  rationale: string
  evidence_refs: string[]
  causal_review?: CausalReview | null
  arithmetic_counterexamples: ArithmeticCounterexample[]
}

export interface WorkspacePickResponse {
  path?: string | null
  cancelled?: boolean | null
  error?: string | null
}

export interface WorkspaceRequest {
  path: string
}

export interface WorkspaceResponse {
  path?: string | null
}
