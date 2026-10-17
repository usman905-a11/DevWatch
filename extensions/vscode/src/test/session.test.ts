import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import { ReviewController, SavedState } from '../session'

test('unknown submission preserves original intent and refuses replacement until explicit recovery', async () => {
  const snapshot = 'a'.repeat(32), identity = 'b'.repeat(32)
  let saved: SavedState = { cursor: 0 }, fail = true
  const payloads: any[] = []
  const controller = new ReviewController(async request => {
    payloads.push(request)
    if (request.action === 'capture') return { intent: { snapshot_id: snapshot, changed_files: ['service.py'], idempotency_key: 'original' } }
    if (fail) throw Error('connection lost')
    return { job_id: identity }
  }, () => saved, async state => { saved = structuredClone(state) })
  await assert.rejects(controller.review('workspace'))
  assert.equal(saved.intent?.idempotency_key, 'original')
  await assert.rejects(controller.review('different'))
  await assert.rejects(controller.attach('c'.repeat(32)))
  fail = false
  await controller.recover()
  assert.equal(saved.jobId, identity)
  assert.deepEqual(payloads.filter(value => value.action === 'submit').map(value => value.intent), [saved.intent, saved.intent])
})

test('replay advances only after consumer acceptance and never resumes or cancels implicitly', async () => {
  let saved: SavedState = { jobId: 'a'.repeat(32), cursor: 0 }
  const actions: string[] = []
  const controller = new ReviewController(async request => {
    actions.push(request.action)
    if (request.action === 'events') return { events: [{ sequence: 1, kind: 'tool_called' }], next_cursor: 1 }
    return { job_id: saved.jobId, status: 'running' }
  }, () => saved, async state => { saved = structuredClone(state) })
  await assert.rejects(controller.observe(async () => { throw Error('viewer detached') }))
  assert.equal(saved.cursor, 0)
  await controller.observe(async () => {})
  assert.equal(saved.cursor, 1)
  assert.ok(actions.every(action => ['events', 'status'].includes(action)))
})
