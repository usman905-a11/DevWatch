import { DurableReviewClient, SubmissionIntent } from './durable-client'
import {
  AgentRunStatus,
  applyStepUpdate,
  deriveAgentStatuses,
  deriveReviewStage,
  observeJob,
  Observation,
  pruneTrajectorySteps,
  reconcileTerminalJobSteps,
  ReviewStage,
  TrajectoryStep,
} from './durable-events'
import { AgentId, JobView, ReportDraft, SnapshotManifest, SourceExcerpt, StepRenderInfo, StepStatus, StepType, StreamEvent } from './wire'

export interface SessionState {
  job: JobView | null; manifest: SnapshotManifest | null; report: ReportDraft | null
  source: SourceExcerpt | null; sourceError: string | null; events: StreamEvent[]
  steps: TrajectoryStep[]
  stage: ReviewStage
  agentStatuses: Record<AgentId, AgentRunStatus>
  history: JobView[]
  intent: SubmissionIntent | null; busy: boolean; error: string | null; connection: string
}
const empty = (): SessionState => ({ job: null, manifest: null, report: null, source: null, sourceError: null,
  events: [], steps: [], stage: 'idle', agentStatuses: deriveAgentStatuses([], [], null), history: [],
  intent: null, busy: false, error: null, connection: 'disconnected' })

export interface StartReviewOptions {
  changedFiles?: readonly string[]
  contextFiles?: readonly string[]
  executionMode?: 'parallel' | 'balanced' | 'sequential'
  jobTokens?: number
}

/** Owns viewer resources, never owns job execution. State is React-independent. */
export class ReviewSession {
  private state = empty()
  private stepsByIdx = new Map<number, TrajectoryStep>()
  private listeners = new Set<() => void>()
  private observation?: Observation
  private request = new AbortController()
  private generation = 0
  private navigation = 0
  private viewing = 0
  constructor(readonly client: DurableReviewClient) {}
  getSnapshot = () => this.state
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }
  private update(patch: Partial<SessionState>) {
    const merged = { ...this.state, ...patch }
    const stage = deriveReviewStage(merged.events, merged.job)
    const agentStatuses = deriveAgentStatuses(merged.events, merged.steps, merged.job)
    this.state = { ...merged, stage, agentStatuses }
    this.listeners.forEach(listener => listener())
  }
  hasPendingSubmission = () => Boolean(this.state.intent && !this.state.job)
  dispose() { this.generation++; this.navigation++; this.request.abort(); this.observation?.stop(); this.observation = undefined }
  reset() {
    if (this.hasPendingSubmission()) return
    const preservedHistory = this.state.history
    this.dispose(); this.stepsByIdx = new Map(); this.request = new AbortController(); this.update({ ...empty(), history: preservedHistory })
  }
  async refreshHistory(limit = 30): Promise<JobView[]> {
    try {
      const history = await this.client.listJobs(limit, this.request.signal)
      this.update({ history })
      return history
    } catch {
      // History refresh is non-fatal when offline or unauthenticated.
      return this.state.history
    }
  }
  async switchJob(jobId: string) {
    await this.attach(jobId)
  }
  private async perform(action: (generation: number, signal: AbortSignal) => Promise<void>) {
    const generation = this.generation, signal = this.request.signal
    if (this.state.busy) return
    this.update({ busy: true, error: null })
    try { await action(generation, signal) } catch (error) {
      if (generation === this.generation) this.update({ error: error instanceof Error ? error.message : 'Service operation failed' })
    } finally { if (generation === this.generation) this.update({ busy: false }) }
  }
  async start(workspacePath: string, changedOrOptions?: readonly string[] | StartReviewOptions) {
    if (this.state.busy || this.hasPendingSubmission()) return
    this.reset()
    const opts: StartReviewOptions = Array.isArray(changedOrOptions)
      ? { changedFiles: changedOrOptions }
      : (changedOrOptions as StartReviewOptions | undefined) ?? {}
    await this.perform(async (generation, signal) => {
      const intent: SubmissionIntent = {
        workspace_path: workspacePath,
        ...(opts.changedFiles ? { changed_files: opts.changedFiles } : {}),
        ...(opts.contextFiles?.length ? { context_files: opts.contextFiles } : {}),
        ...(opts.executionMode ? { execution_mode: opts.executionMode } : {}),
        ...(opts.jobTokens != null ? { job_tokens: opts.jobTokens } : {}),
        idempotency_key: crypto.randomUUID(),
      }
      this.update({ intent }) // Preserve exact intent before POST, including unknown outcome.
      await this.submitIntent(generation, signal)
    })
  }
  private async submitIntent(generation: number, signal: AbortSignal) {
    if (!this.state.intent) return
    const job = await this.client.submit(this.state.intent, signal)
    if (generation !== this.generation) return
    this.update({ job }); this.observe(generation)
  }
  async retrySubmission() {
    if (this.state.job || !this.state.intent) return
    await this.perform((generation, signal) => this.submitIntent(generation, signal))
  }
  async attach(jobId: string) {
    if (this.state.busy || this.hasPendingSubmission()) return
    this.reset()
    await this.perform(async (generation, signal) => {
      const job = await this.client.status(jobId, signal)
      if (generation !== this.generation) return
      this.update({ job }); this.observe(generation)
    })
  }
  private syncSteps(jobStatus = this.state.job?.status): TrajectoryStep[] {
    this.stepsByIdx = pruneTrajectorySteps(this.stepsByIdx, 200)
    this.stepsByIdx = reconcileTerminalJobSteps(this.stepsByIdx, jobStatus)
    return [...this.stepsByIdx.values()].sort((a, b) => a.stepIdx - b.stepIdx)
  }
  private observe(generation: number) {
    const job = this.state.job
    if (!job) return
    const after = this.observation?.cursor ?? 0, viewing = ++this.viewing
    this.observation?.stop()
    const current = () => generation === this.generation && viewing === this.viewing
    this.observation = observeJob(this.client, job.job_id, {
      onEvent: event => {
        if (!current()) return
        if (event.type === 'step_update') {
          const p = event.payload as Record<string, any>
          if (p.step_idx != null && p.step_type) {
            const stepStatus = (p.step_status ?? (p.status as StepStatus | null) ?? 'RUNNING') as StepStatus
            this.stepsByIdx = applyStepUpdate(
              this.stepsByIdx,
              {
                step_idx: p.step_idx as number,
                parent_step_idx: (p.parent_step_idx as number | null) ?? null,
                agent_name: (p.agent_name ?? p.agent_id ?? undefined) as string | undefined,
                step_type: p.step_type as StepType,
                status: stepStatus,
                delta_seq: (p.delta_seq as number | null) ?? 0,
                render_info: (p.render_info ?? {}) as StepRenderInfo,
                error_details: (p.error_details as string | null) ?? null,
              },
              p.agent_id as string | null | undefined,
            )
          }
        }
        this.update({
          events: [...this.state.events, event].slice(-200),
          steps: this.syncSteps(),
        })
      },
      onJob: value => {
        if (current()) this.update({ job: value, steps: this.syncSteps(value.status) })
      },
      onReport: report => { if (current()) this.update({ report }) },
      onConnection: connection => { if (current()) this.update({ connection }) },
      onError: error => { if (current()) this.update({ error: `Observation stopped: ${error.message} Reconnect to check the job.` }) },
    }, { after })
  }
  async reconnect() {
    if (!this.state.job) return
    await this.perform(async (generation, signal) => {
      const job = await this.client.status(this.state.job!.job_id, signal)
      if (generation !== this.generation) return
      this.update({ job, steps: this.syncSteps(job.status) }); this.observe(generation)
    })
  }
  async cancel() { await this.control('cancel') }
  async resume() { await this.control('resume') }
  private async control(kind: 'cancel' | 'resume') {
    if (!this.state.job) return
    await this.perform(async (generation, signal) => {
      const job = await this.client[kind](this.state.job!.job_id, signal)
      if (generation !== this.generation) return
      this.update({ job, steps: this.syncSteps(job.status) }); this.observe(generation)
    })
  }
  async openSource(path: string, start: number, end: number) {
    const job = this.state.job, navigation = ++this.navigation, generation = this.generation
    const snapshotId = job?.snapshot_id ?? this.state.report?.snapshot_id
    if (!job || !snapshotId) return
    this.update({ source: null, sourceError: null })
    try {
      const source = await this.client.source(job.job_id, snapshotId, path, start, end, this.request.signal)
      if (generation === this.generation && navigation === this.navigation) this.update({ source })
    } catch {
      if (generation === this.generation && navigation === this.navigation) this.update({ sourceError: 'Source excerpt unavailable. Select a smaller range and retry.' })
    }
  }
}
