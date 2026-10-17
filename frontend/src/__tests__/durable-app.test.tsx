import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import App from '../App'

describe('durable review workspace', () => {
  it('offers authenticated connection, local capture and reopening jobs without a server path API', () => {
    const html = renderToStaticMarkup(<App />)
    expect(html).toContain('API key')
    expect(html).toContain('Open job')
    expect(html).toContain('Open local folder')
    expect(html).toContain('Jobs keep running when this view closes')
    expect(html).not.toContain('Repository path')
    expect(html).not.toContain('Apply fix')
  })
})
