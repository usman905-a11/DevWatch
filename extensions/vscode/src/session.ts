/** Durable client state. No model execution or source writing happens in the IDE. */
export interface Intent { snapshot_id: string; changed_files?: string[] | null; idempotency_key: string }
export interface SavedState { intent?: Intent; jobId?: string; cursor: number }
export type Request = { action: string; [key: string]: unknown }
export type Rpc = (request: Request) => Promise<any>
const identity = (value: unknown): string => {
  if (typeof value !== 'string' || !/^[0-9a-f]{32}$/.test(value)) throw Error('Invalid job identity')
  return value
}

export class ReviewController {
  constructor(readonly rpc: Rpc, readonly load: () => SavedState, readonly save: (state: SavedState) => Promise<void>) {}
  private current(): SavedState {
    const state = structuredClone(this.load())
    if (!Number.isSafeInteger(state.cursor) || state.cursor < 0) throw Error('Invalid saved replay cursor')
    if (state.jobId) identity(state.jobId)
    return state
  }
  private pending(state: SavedState) { return state.intent && !state.jobId }
  async review(root: string) {
    const before = this.current()
    if (this.pending(before)) throw Error('Recover the original submission before starting another review')
    if (before.jobId) {
      const existing = await this.rpc({ action: 'status', job_id: before.jobId })
      if (['queued', 'running', 'interrupted'].includes(existing.status)) throw Error('Finish or explicitly cancel the current review first')
    }
    const captured = await this.rpc({ action: 'capture', root })
    identity(captured.intent.snapshot_id)
    await this.save({ intent: structuredClone(captured.intent), cursor: 0 })
    return this.recover()
  }
  async recover() {
    const state = this.current()
    if (!state.intent || state.jobId) throw Error('No unresolved submission to recover')
    const job = await this.rpc({ action: 'submit', intent: structuredClone(state.intent) })
    const jobId = identity(job.job_id)
    await this.save({ ...state, jobId })
    return job
  }
  async attach(jobId: string) {
    if (this.pending(this.current())) throw Error('Recover the original submission first')
    const job = await this.rpc({ action: 'status', job_id: identity(jobId) })
    if (job.job_id !== jobId) throw Error('Wrong job identity')
    await this.save({ jobId, cursor: 0 })
    return job
  }
  async observe(consume: (event: any) => Promise<void>) {
    const state = this.current()
    if (!state.jobId) throw Error('Open a job first')
    const page = await this.rpc({ action: 'events', job_id: state.jobId, after: state.cursor })
    for (const event of page.events) {
      const sequence = event.sequence
      if (!Number.isSafeInteger(sequence) || sequence <= state.cursor) throw Error('Invalid event sequence')
      await consume(structuredClone(event))
      state.cursor = sequence
      await this.save(state)
    }
    if (page.next_cursor !== state.cursor) throw Error('Invalid event cursor')
    return this.rpc({ action: 'status', job_id: state.jobId })
  }
  async control(action: 'cancel' | 'resume') {
    const jobId = this.current().jobId
    if (!jobId) throw Error('Open a job first')
    return this.rpc({ action, job_id: jobId })
  }
}
