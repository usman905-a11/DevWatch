import { useEffect, useMemo, useSyncExternalStore } from 'react'
import { DurableReviewClient } from './durable-client'
import { ReviewSession } from './review-session'

export function useReviewSession(client: DurableReviewClient) {
  const session = useMemo(() => new ReviewSession(client), [client])
  const state = useSyncExternalStore(session.subscribe, session.getSnapshot, session.getSnapshot)
  useEffect(() => () => session.dispose(), [session])
  return { session, state }
}
