import { CaptureCoverage, sourcePath } from './wire'

export interface FolderCapture { name: string; files: Record<string, string>; coverage: CaptureCoverage; omitted: number }
const extensions = new Set(['py', 'js', 'jsx', 'ts', 'tsx', 'java', 'go', 'rs', 'rb', 'php', 'cs', 'cpp', 'c', 'h', 'sql', 'json', 'toml', 'yaml', 'yml', 'html', 'css', 'md'])
const excluded = new Set(['.git', '.devwatch', '.venv', 'venv', 'node_modules', '__pycache__', 'dist', 'build', 'coverage'])

/** File selection is local; only bounded source and omission metadata are uploaded. */
export async function captureFolder(selection: ArrayLike<File>, options: { maxFiles?: number } = {}): Promise<FolderCapture> {
  const maxFiles = Math.min(100, Math.max(1, options.maxFiles ?? 100))
  const files: Record<string, string> = Object.create(null)
  const coverage: CaptureCoverage = { skipped: Object.create(null), failed: Object.create(null), limitations: ['Browser folder capture reviews whole uploaded files without Git history.'] }
  const first = selection[0]?.webkitRelativePath || ''
  const name = first.split('/')[0] || 'workspace'
  let total = 0, count = 0, omitted = 0
  const omit = (path: string, reason: string, failed = false) => {
    omitted++
    if (Object.keys(coverage.skipped).length + Object.keys(coverage.failed).length < 1000) (failed ? coverage.failed : coverage.skipped)[path] = reason
  }
  const entries = Math.min(selection.length, 10000)
  for (let index = 0; index < entries; index++) {
    const file = selection[index]
    const relative = file.webkitRelativePath || file.name
    const path = file.webkitRelativePath ? relative.slice(relative.indexOf('/') + 1) : relative
    try { sourcePath(path) } catch { omitted++; continue }
    const parts = path.toLowerCase().split('/')
    if ((file.webkitRelativePath && !relative.startsWith(name + '/')) || parts.some(part => excluded.has(part)
      || part.startsWith('.env') || /\.(pem|key|p12|pfx|crt|cer|jks|keystore)$/.test(part)
      || ['credentials', 'credentials.json', 'secrets.json', 'secrets.yaml', 'service_account.json', 'id_rsa', 'id_rsa.pub', 'id_ed25519', 'id_ed25519.pub'].includes(part))) { omit(path, 'excluded_source'); continue }
    if (!extensions.has(parts[parts.length - 1].split('.').pop()!) || /\.(min\.(js|css)|map|lock)$/.test(path)) { omit(path, 'unsupported_source'); continue }
    if (count >= maxFiles) { omit(path, 'file_count_limit'); continue }
    if (file.size > 500000) { omit(path, 'file_byte_limit'); continue }
    if (total + file.size > 10000000) { omit(path, 'total_byte_limit'); continue }
    try {
      const bytes = await file.arrayBuffer()
      if (bytes.byteLength > 500000 || total + bytes.byteLength > 10000000) { omit(path, 'file_byte_limit'); continue }
      const content = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes)
      if (content.includes('\0')) { omit(path, 'binary_source'); continue }
      if (Object.prototype.hasOwnProperty.call(files, path)) { omit(path, 'duplicate_source'); continue }
      files[path] = content; total += bytes.byteLength; count++
    } catch { omit(path, 'unreadable_source', true) }
  }
  if (selection.length > entries) { omitted += selection.length - entries; coverage.limitations.push('Folder catalog truncated at 10,000 entries.') }
  if (omitted > Object.keys(coverage.skipped).length + Object.keys(coverage.failed).length) coverage.limitations.push('Some omissions have no individual entry because their paths were invalid or the omission catalog reached its limit.')
  return { name, files, coverage, omitted }
}
