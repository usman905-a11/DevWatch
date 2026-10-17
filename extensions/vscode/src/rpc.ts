import { spawn } from 'node:child_process'
import { Rpc } from './session'

/** The executable is operator-configured, argv is fixed, credentials use stdin. */
export function bridge(python: string, cwd: string, serviceUrl: string, apiKey: string, signal: AbortSignal): Rpc {
  return request => new Promise((resolve, reject) => {
    const environment: NodeJS.ProcessEnv = {}
    for (const [name, value] of Object.entries(process.env)) if (['PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP'].includes(name.toUpperCase())) environment[name] = value
    environment.PYTHONUTF8 = '1'
    const child = spawn(python, ['-I', '-m', 'devwatch.ide_bridge'], { cwd, env: environment, windowsHide: true, stdio: ['pipe', 'pipe', 'ignore'] })
    const chunks: Buffer[] = []
    let size = 0, settled = false
    const finish = (error?: Error, result?: unknown) => {
      if (settled) return
      settled = true; clearTimeout(timer); signal.removeEventListener('abort', abort)
      if (error && child.exitCode === null) child.kill()
      error ? reject(error) : resolve(result)
    }
    const abort = () => { child.kill(); finish(Error('View detached; submitted jobs keep running')) }
    const timer = setTimeout(() => { child.kill(); finish(Error('Bridge timeout; recover an unresolved submission with its original intent')) }, 30000)
    signal.addEventListener('abort', abort, { once: true })
    child.on('error', () => finish(Error('Install DevWatch into the configured trusted Python interpreter')))
    child.stdout.on('data', (chunk: Buffer) => {
      size += chunk.length
      if (size > 15000000) { child.kill(); finish(Error('Bridge response limit exceeded')) } else chunks.push(chunk)
    })
    child.stdin.on('error', () => finish(Error('Bridge input failed')))
    child.on('close', code => {
      if (code !== 0) return finish(Error('Service operation failed; check configuration or recover the original intent'))
      try {
        const reply = JSON.parse(Buffer.concat(chunks).toString('utf8'))
        if (reply.version !== 1 || reply.ok !== true || !reply.result || typeof reply.result !== 'object') throw Error()
        finish(undefined, reply.result)
      } catch { finish(Error('Invalid bridge response')) }
    })
    child.stdin.end(JSON.stringify({ version: 1, ...request, service_url: serviceUrl, api_key: apiKey || null }))
    if (signal.aborted) abort()
  })
}
