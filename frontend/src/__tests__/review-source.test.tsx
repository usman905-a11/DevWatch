import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import App from '../App'

describe('review source entry', () => {
  it('requires an explicit review source before the first run', () => {
    const markup = renderToStaticMarkup(<App />)

    expect(markup).toContain('Open job')
    expect(markup).toContain('Open local folder')
    expect(markup).toMatch(/<button[^>]*disabled=""[^>]*>Run review<\/button>/)
    expect(markup).not.toContain('Command palette')
    expect(markup).not.toContain('>main<')
    expect(markup).not.toContain('<kbd>')
    expect(markup).not.toContain('\u2318')
  })
})
