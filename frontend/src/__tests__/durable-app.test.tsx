import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import App from '../App'

describe('durable review workspace', () => {
  it('relies on backend .env authentication, local folder picker and reopening jobs without credential inputs', () => {
    const html = renderToStaticMarkup(<App />)
    expect(html).not.toContain('API key')
    expect(html).not.toContain('Service URL')
    expect(html).not.toContain('Service connection')
    expect(html).toContain('Open job')
    expect(html).toContain('Open local folder')
    expect(html).toContain('Jobs keep running when this view closes')
    expect(html).not.toContain('Repository path')
    expect(html).not.toContain('Apply fix')
  })
})
