import { describe, expect, it } from 'vitest'
import { captureFolder } from '../review/folder-capture'

const file = (path: string, content: string, size?: number) => ({ name: path.split('/').pop()!, webkitRelativePath: path,
  size: size ?? new TextEncoder().encode(content).length, arrayBuffer: async () => new TextEncoder().encode(content).buffer }) as File

describe('browser bounded source capture', () => {
  it('preserves source bytes and records omissions without reading sensitive/generated files', async () => {
    const files = [file('project/service.py', 'pass\r\n'), file('project/.env', 'secret'), file('project/service_account.json', 'secret'),
      file('project/dist/app.js', 'generated'), file('project/large.py', '', 500001), file('project/empty.py', '')]
    const result = await captureFolder(files)
    expect(result.files).toEqual({ 'service.py': 'pass\r\n', 'empty.py': '' })
    expect(result.coverage.skipped['dist/app.js']).toBe('excluded_source')
    expect(result.coverage.skipped['.env']).toBe('excluded_source')
    expect(result.coverage.skipped['service_account.json']).toBe('excluded_source')
    expect(result.coverage.skipped['large.py']).toBe('file_byte_limit')
    expect(result.name).toBe('project')
  })
  it('limits selection and reports unreadable/invalid UTF-8 source', async () => {
    const bad = { ...file('project/bad.py', ''), arrayBuffer: async () => new Uint8Array([255]).buffer } as File
    const denied = { ...file('project/denied.py', ''), arrayBuffer: async () => { throw new Error('private OS details') } } as File
    const result = await captureFolder([file('project/a.py', 'pass'), bad, denied, file('project/b.py', 'pass')], { maxFiles: 1 })
    expect(result.files).toEqual({ 'a.py': 'pass' })
    expect(Object.values(result.coverage.skipped)).toContain('file_count_limit')
    const failures = await captureFolder([bad, denied])
    expect(failures.coverage.failed).toEqual({ 'bad.py': 'unreadable_source', 'denied.py': 'unreadable_source' })
    expect(JSON.stringify(failures)).not.toContain('private OS details')
  })
})
