/** Run only by a disposable VS Code extension host against the local fixture service. */
import * as vscode from 'vscode'
import { strict as assert } from 'node:assert'

export async function run() {
  const config = vscode.workspace.getConfiguration('devwatch')
  await config.update('serviceUrl', 'http://127.0.0.1:8998', vscode.ConfigurationTarget.Global)
  await config.update('pythonPath', process.env.DEVWATCH_TEST_PYTHON, vscode.ConfigurationTarget.Global)
  const extension = vscode.extensions.getExtension('devwatch-local.devwatch')
  assert.ok(extension)
  await extension.activate()
  const state = await vscode.commands.executeCommand<{ jobId: string }>('devwatch.review')
  assert.ok(state && /^[0-9a-f]{32}$/.test(state.jobId))
  const deadline = Date.now() + 30000
  let job: any
  while (Date.now() < deadline) {
    job = await (await fetch(`http://127.0.0.1:8998/api/jobs/${state.jobId}`)).json()
    if (job.status === 'completed') break
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  assert.equal(job.status, 'completed')
  const reopened = await vscode.commands.executeCommand<{ jobId: string }>('devwatch.open', state.jobId)
  assert.equal(reopened?.jobId, state.jobId)
  const document = await vscode.workspace.openTextDocument(vscode.Uri.parse(`devwatch-snapshot:/${state.jobId}/subject.py`))
  assert.equal(document.uri.scheme, 'devwatch-snapshot')
  assert.equal(document.isUntitled, false)
  assert.equal(document.isDirty, false)
  console.log(JSON.stringify({ ide: 'VS Code', version: vscode.version, canonical_job: true, reopen: true, virtual_source_provider: true }))
}
