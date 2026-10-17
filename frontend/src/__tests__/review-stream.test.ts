import { afterEach, describe, expect, it, vi } from 'vitest'
import { subscribeToReviewStream } from '../services/api'

class FakeWebSocket {
  static OPEN = 1
  static CONNECTING = 0
  static latest: FakeWebSocket
  readyState = 0
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: ((error: Error) => void) | null = null
  onclose: ((event: { code: number }) => void) | null = null
  sent: string[] = []

  constructor(public url: string) {
    FakeWebSocket.latest = this
  }

  send(data: string) {
    this.sent.push(data)
  }

  close() {
    this.readyState = 3
    this.onclose?.({ code: 1000 })
  }

  message(data: object) {
    this.onmessage?.({ data: JSON.stringify(data) })
  }
}

afterEach(() => { vi.unstubAllGlobals() })

describe('review WebSocket subscription', () => {
  it('keeps completed progress distinct from final completion', () => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
    const steps: string[] = []
    const completions: string[] = []
    const errors: string[] = []
    const stop = subscribeToReviewStream(
      '.',
      (step) => steps.push(step.message),
      (data) => completions.push(data.type),
      (error) => errors.push(error.message),
    )
    const socket = FakeWebSocket.latest
    socket.onopen?.()
    socket.message({ type: 'agent_update', status: 'COMPLETED', agent_name: 'Planner', message: 'Plan ready' })
    socket.message({ type: 'review_completion', status: 'COMPLETED', report: { issues: [] } })
    stop()
    expect(steps).toEqual(['Plan ready'])
    expect(completions).toEqual(['review_completion'])
    expect(errors).toEqual([])
  })

  it('surfaces a malformed completion instead of leaving review running', () => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
    const errors: string[] = []
    subscribeToReviewStream(
      '.',
      () => {},
      () => { throw new Error('Invalid report payload') },
      (error) => errors.push(error.message),
    )
    FakeWebSocket.latest.message({ type: 'review_completion', report: null })
    expect(errors).toEqual(['Invalid report payload'])
  })

  it('reports an unexpected disconnect instead of leaving review running', () => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
    const errors: string[] = []
    subscribeToReviewStream('.', () => {}, () => {}, (error) => errors.push(error.message))
    FakeWebSocket.latest.onclose?.({ code: 1006 })
    expect(errors).toEqual(['Review connection closed before completion'])
  })
})
