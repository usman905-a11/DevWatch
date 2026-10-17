import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import App from '../App'
import { JobActivity } from '../review/JobActivity'
import fixture from './fixtures/canonical-wire.json'

describe('F4 workspace access', () => {
  it('lets keyboard users skip to results and switch among narrow-screen work areas', () => {
    const markup = renderToStaticMarkup(<App />)
    expect(markup).toContain('href="#review-results"')
    expect(markup).toContain('aria-label="Workspace sections"')
    expect(markup).toContain('aria-controls="review-results"')
    expect(markup).toContain('aria-controls="source-files"')
    expect(markup).toContain('aria-controls="source-pane"')
    expect(markup).toContain('data-mobile-pane="review"')
  })

  it('announces review status changes with a distinct failed state', () => {
    const markup = renderToStaticMarkup(
      <JobActivity job={{ ...fixture.job, status: 'failed' } as any} events={[]} connection="disconnected" />,
    )
    expect(markup).toContain('role="status"')
    expect(markup).toContain('aria-live="polite"')
    expect(markup).toContain('Job: failed')
  })
})
