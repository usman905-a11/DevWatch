import * as vscode from 'vscode'
import { createHash, randomBytes } from 'node:crypto'
import { writeFile } from 'node:fs/promises'
import { bridge } from './rpc'
import { ReviewController, SavedState } from './session'

export async function activate(context: vscode.ExtensionContext) {
  const documents = new Map<string, string>()
  context.subscriptions.push(vscode.workspace.registerTextDocumentContentProvider('devwatch-snapshot', {
    provideTextDocumentContent: uri => documents.get(uri.toString()) ?? 'Immutable excerpt unavailable',
  }))
  async function open(mode: 'review' | 'open' | 'recover', requestedJob?: string) {
    if (!vscode.workspace.isTrusted) throw Error('Open a trusted workspace to use DevWatch')
    const config = vscode.workspace.getConfiguration('devwatch')
    const serviceUrl = config.get<string>('serviceUrl')!, python = config.get<string>('pythonPath')!
    const apiKey = await context.secrets.get('devwatch.apiKey') ?? ''
    const namespace = 'review.' + createHash('sha256').update(serviceUrl + '\0' + apiKey).digest('hex')
    const lifetime = new AbortController()
    const rpc = bridge(python, context.extensionPath, serviceUrl, apiKey, lifetime.signal)
    const controller = new ReviewController(rpc, () => context.workspaceState.get<SavedState>(namespace) ?? { cursor: 0 },
      state => Promise.resolve(context.workspaceState.update(namespace, structuredClone(state))))
    const panel = vscode.window.createWebviewPanel('devwatch', 'DevWatch review', vscode.ViewColumn.Beside, { enableScripts: true, localResourceRoots: [] })
    const nonce = randomBytes(18).toString('base64')
    panel.webview.html = html(nonce)
    let disposed = false, busy = false, failedReads = 0, rendered = ''
    const post = (kind: string, data: unknown) => { if (!disposed) void panel.webview.postMessage({ kind, data }) }
    const error = (value: unknown) => post('error', value instanceof Error ? value.message : 'Review operation failed')
    async function observe() {
      if (disposed || busy || !controller.load().jobId) return
      busy = true
      try {
        const job = await controller.observe(async event => { post('event', event) })
        post('job', job); failedReads = 0
        if (job.status === 'completed' && rendered !== job.job_id) {
          const result = await rpc({ action: 'report', job_id: job.job_id, format: 'json' })
          post('report', JSON.parse(result.text)); rendered = job.job_id
        }
      } catch (value) { if (++failedReads >= 3) { clearInterval(timer); error(value) } }
      finally { busy = false }
    }
    async function action(work: () => Promise<unknown>) {
      if (busy) return
      busy = true
      try { await work(); post('state', controller.load()) } catch (value) { error(value) }
      finally { busy = false; void observe() }
    }
    let timer = setInterval(() => { void observe() }, 2000)
    panel.onDidDispose(() => { disposed = true; clearInterval(timer); lifetime.abort() }, undefined, context.subscriptions)
    panel.webview.onDidReceiveMessage(async (message: unknown) => {
      if (!message || typeof message !== 'object' || !('kind' in message)) return
      const data = message as Record<string, unknown>
      if (data.kind === 'ready') { post('state', controller.load()); void observe(); return }
      if (data.kind === 'reconnect') {
        failedReads = 0; clearInterval(timer); timer = setInterval(() => { void observe() }, 2000)
        await action(async () => {}); return
      }
      if (data.kind === 'cancel' || data.kind === 'resume') { await action(() => controller.control(data.kind as 'cancel' | 'resume')); return }
      if (data.kind === 'source' && typeof data.path === 'string') await action(async () => {
        const jobId = controller.load().jobId
        if (!jobId || !Number.isSafeInteger(data.start) || !Number.isSafeInteger(data.end)) throw Error('Invalid source location')
        const excerpt = await rpc({ action: 'source', job_id: jobId, file_path: data.path, start_line: data.start, end_line: data.end })
        const uri = vscode.Uri.from({ scheme: 'devwatch-snapshot', path: `/${jobId}/${data.path}`, query: `lines=${data.start}-${data.end}` })
        documents.set(uri.toString(), excerpt.data)
        while (documents.size > 50) documents.delete(documents.keys().next().value!)
        await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(uri), { preview: true })
      })
      if (data.kind === 'export' && ['json', 'markdown', 'pdf'].includes(String(data.format))) await action(async () => {
        const jobId = controller.load().jobId
        if (!jobId) throw Error('Open a finalized job first')
        const format = String(data.format), extension = format === 'markdown' ? 'md' : format
        const destination = await vscode.window.showSaveDialog({ saveLabel: 'Export report artifact',
          defaultUri: vscode.Uri.file(`devwatch-${jobId}.${extension}`), filters: { 'Review report': [extension] } })
        if (!destination) return
        if (destination.scheme !== 'file' || !destination.fsPath.toLowerCase().endsWith('.' + extension)) throw Error('Choose a new report artifact file')
        const result = await rpc({ action: 'report', job_id: jobId, format })
        const bytes = result.base64 ? Buffer.from(result.base64, 'base64') : Buffer.from(result.text, 'utf8')
        await writeFile(destination.fsPath, bytes, { flag: 'wx' })
      })
    }, undefined, context.subscriptions)
    if (mode === 'review') await action(async () => {
      const folders = vscode.workspace.workspaceFolders
      if (!folders?.length || folders[0].uri.scheme !== 'file') throw Error('Open a local workspace folder first')
      await controller.review(folders[0].uri.fsPath)
    })
    else if (mode === 'recover') await action(() => controller.recover())
    else {
      const identity = requestedJob ?? await vscode.window.showInputBox({ prompt: 'Owned DevWatch job ID', ignoreFocusOut: true })
      if (identity) await action(() => controller.attach(identity.trim()))
    }
    return controller.load()
  }
  for (const [command, mode] of [['review', 'review'], ['open', 'open'], ['recover', 'recover']] as const) {
    context.subscriptions.push(vscode.commands.registerCommand(`devwatch.${command}`, (jobId?: string) => open(mode, jobId).catch(value => vscode.window.showErrorMessage(value.message))))
  }
  context.subscriptions.push(vscode.commands.registerCommand('devwatch.configure', async () => {
    const key = await vscode.window.showInputBox({ prompt: 'Local review service API key (stored in IDE SecretStorage)', password: true, ignoreFocusOut: true })
    if (key !== undefined) await context.secrets.store('devwatch.apiKey', key)
  }))
}

function html(nonce: string) {
  return `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'nonce-${nonce}'; style-src 'nonce-${nonce}';">
<style nonce="${nonce}">body{font:var(--vscode-font-size) var(--vscode-font-family);color:var(--vscode-foreground);padding:16px}button{margin:4px;padding:6px}pre{white-space:pre-wrap;overflow-wrap:anywhere}section{border-top:1px solid var(--vscode-panel-border);padding-top:12px}li{margin:8px 0}</style>
<h1>DevWatch review</h1><p id="status" role="status">Connecting to durable review service…</p>
<button data-action="reconnect">Reconnect</button><button data-action="cancel">Cancel review</button><button data-action="resume">Resume interrupted review</button>
<button data-format="json">Export JSON</button><button data-format="markdown">Export Markdown</button><button data-format="pdf">Export PDF</button>
<p id="error" role="alert"></p><pre id="intent"></pre><h2>Agent activity</h2><ol id="events"></ol><div id="report"></div>
<script nonce="${nonce}">const host=acquireVsCodeApi();const byId=id=>document.getElementById(id);
document.querySelectorAll('[data-action]').forEach(button=>button.onclick=()=>host.postMessage({kind:button.dataset.action}));
document.querySelectorAll('[data-format]').forEach(button=>button.onclick=()=>host.postMessage({kind:'export',format:button.dataset.format}));
window.addEventListener('message',({data:message})=>{const value=message.data;
if(message.kind==='error')byId('error').textContent=value;
if(message.kind==='state')byId('intent').textContent=JSON.stringify(value,null,2);
if(message.kind==='job'){let tokens=Object.values(value.ledger.agent_usage).reduce((n,u)=>n+u.prompt_tokens+u.completion_tokens,0);byId('status').textContent='Job '+value.job_id+' · '+value.status+' · '+tokens+' tokens · '+value.ledger.elapsed_seconds.toFixed(1)+'s';}
if(message.kind==='event'){let item=document.createElement('li');item.textContent=[value.kind,value.payload.agent_id,value.payload.task_id,value.payload.tool].filter(Boolean).join(' · ');byId('events').append(item);while(byId('events').children.length>200)byId('events').firstChild.remove();}
if(message.kind==='report'){let report=byId('report');report.replaceChildren();for(const [key,label]of [['confirmed_defects','Confirmed defects'],['uncertain_high_impact_candidates','Uncertain high-impact candidates'],['advisories','Advisories']]){let section=document.createElement('section'),heading=document.createElement('h2');heading.textContent=label;section.append(heading);for(const finding of value[key]){let title=document.createElement('h3'),text=document.createElement('p'),source=document.createElement('button');title.textContent=finding.title;text.textContent=finding.description+' Impact: '+finding.impact;source.textContent='Open immutable source';source.onclick=()=>host.postMessage({kind:'source',path:finding.location.file_path,start:finding.location.start_line,end:finding.location.end_line});section.append(title,text,source);}report.append(section);}let coverage=document.createElement('pre');coverage.textContent='Coverage\n'+JSON.stringify(value.coverage,null,2)+'\nLimitations\n'+JSON.stringify(value.limitations);report.append(coverage);}});host.postMessage({kind:'ready'});</script></html>`
}
