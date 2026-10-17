import { DurableReviewClient, SubmissionIntent } from './durable-client'
import { observeJob, Observation } from './durable-events'
import { CaptureCoverage, JobView, PersistedEvent, ReportDraft, SnapshotManifest, SourceExcerpt } from './wire'

export interface SessionState {
  job: JobView | null; manifest: SnapshotManifest | null; report: ReportDraft | null
  source: SourceExcerpt | null; sourceError: string | null; events: PersistedEvent[]
  intent: SubmissionIntent | null; busy: boolean; error: string | null; connection: string
}
const empty = (): SessionState => ({ job: null, manifest: null, report: null, source: null, sourceError: null,
  events: [], intent: null, busy: false, error: null, connection: 'disconnected' })

/** Owns viewer resources, never owns job execution. State is React-independent. */
export class ReviewSession {
  private state = empty()
  private listeners = new Set<() => void>()
  private observation?: Observation
  private request = new AbortController()
  private generation = 0
  private navigation = 0
  private viewing = 0
  constructor(readonly client: DurableReviewClient) {}
  getSnapshot = () => this.state
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }
  private update(patch: Partial<SessionState>) { this.state = { ...this.state, ...patch }; this.listeners.forEach(listener => listener()) }
  hasPendingSubmission = () => Boolean(this.state.intent && !this.state.job)
  dispose() { this.generation++; this.navigation++; this.request.abort(); this.observation?.stop(); this.observation = undefined }
  reset() {
    if (this.hasPendingSubmission()) return
    this.dispose(); this.request = new AbortController(); this.update(empty())
  }
  private async perform(action: (generation: number, signal: AbortSignal) => Promise<void>) {
    const generation = this.generation, signal = this.request.signal
    if (this.state.busy) return
    this.update({ busy: true, error: null })
    try { await action(generation, signal) } catch (error) {
      if (generation === this.generation) this.update({ error: error instanceof Error ? error.message : 'Service operation failed' })
    } finally { if (generation === this.generation) this.update({ busy: false }) }
  }
  async start(files: Record<string, string>, coverage: CaptureCoverage) {
    if (this.state.busy || this.hasPendingSubmission()) return
    this.reset()
    await this.perform(async (generation, signal) => {
      const manifest = await this.client.capture(files, coverage, signal)
      if (generation !== this.generation) return
      const intent = { snapshot_id: manifest.snapshot_id, idempotency_key: crypto.randomUUID() }
      this.update({ manifest, intent }) // Preserve exact intent before POST, including unknown outcome.
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
      const manifest = await this.client.snapshot(jobId, job.snapshot_id, signal)
      if (generation !== this.generation) return
      this.update({ job, manifest }); this.observe(generation)
    })
  }
  private observe(generation: number) {
    const job = this.state.job
    if (!job) return
    const after = this.observation?.cursor ?? 0, viewing = ++this.viewing
    this.observation?.stop()
    const current = () => generation === this.generation && viewing === this.viewing
    this.observation = observeJob(this.client, job.job_id, {
      onEvent: event => { if (current()) this.update({ events: [...this.state.events, event].slice(-200) }) },
      onJob: value => { if (current()) this.update({ job: value }) },
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
      this.update({ job }); this.observe(generation)
    })
  }
  async cancel() { await this.control('cancel') }
  async resume() { await this.control('resume') }
  private async control(kind: 'cancel' | 'resume') {
    if (!this.state.job) return
    await this.perform(async (generation, signal) => {
      const job = await this.client[kind](this.state.job!.job_id, signal)
      if (generation !== this.generation) return
      this.update({ job }); this.observe(generation)
    })
  }
  async openSource(path: string, start: number, end: number) {
    const job = this.state.job, navigation = ++this.navigation, generation = this.generation
    if (!job) return
    this.update({ source: null, sourceError: null })
    try {
      const source = await this.client.source(job.job_id, job.snapshot_id, path, start, end, this.request.signal)
      if (generation === this.generation && navigation === this.navigation) this.update({ source })
    } catch {
      if (generation === this.generation && navigation === this.navigation) this.update({ sourceError: 'Source excerpt unavailable. Select a smaller range and retry.' })
    }
  }
}
