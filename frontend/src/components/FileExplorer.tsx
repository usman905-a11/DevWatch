import { useState } from 'react'

export interface FileNode {
  id: string
  name: string
  type: 'file' | 'folder'
  ext?: string
  children?: FileNode[]
}

interface Props {
  selectedFileId: string | null
  onSelectFile: (file: FileNode) => void
  tree?: FileNode[]
  projectName?: string
  onOpenFolder?: () => void
}

const colors: Record<string, string> = {
  ts: '#72a7ff', tsx: '#58c7d9', js: '#f3c858', jsx: '#f3c858',
  json: '#f3c858', css: '#bc9cff', md: '#a9b1bd', html: '#f99b7c',
  py: '#72d09c', env: '#f1c24e', sh: '#48b085', toml: '#e5c07b',
}

function FileGlyph({ ext }: { ext?: string }) {
  return (
    <span className="file-glyph" aria-hidden="true" style={{ color: colors[ext ?? ''] ?? '#8e8e93' }}>
      {ext === 'tsx' ? 'TX' : ext === 'py' ? 'PY' : ext === 'ts' ? 'TS' : ext === 'json' ? '{}' : '.'}
    </span>
  )
}

function Tree({ node, depth, selectedFileId, onSelectFile }: {
  node: FileNode
  depth: number
  selectedFileId: string | null
  onSelectFile: (file: FileNode) => void
}) {
  const [open, setOpen] = useState(depth < 1)
  if (node.type === 'folder') {
    const childrenId = `folder-${encodeURIComponent(node.id)}`
    return (
      <li>
        <button
          type="button"
          className="tree-row"
          style={{ paddingLeft: 12 + depth * 14 }}
          aria-expanded={open}
          aria-controls={childrenId}
          onClick={() => setOpen((current) => !current)}
        >
          <span className="chev" aria-hidden="true">{open ? 'v' : '>'}</span>
          <span className="folder" aria-hidden="true">{open ? '[-]' : '[+]'}</span>
          <span>{node.name}</span>
        </button>
        <ul id={childrenId} className="tree-list" hidden={!open}>
          {open && node.children?.map((child) => (
            <Tree key={child.id} node={child} depth={depth + 1} selectedFileId={selectedFileId} onSelectFile={onSelectFile} />
          ))}
        </ul>
      </li>
    )
  }

  const selected = selectedFileId === node.id
  return (
    <li>
      <button
        type="button"
        className={`tree-row ${selected ? 'selected' : ''}`}
        style={{ paddingLeft: 28 + depth * 14 }}
        aria-label={`Open ${node.id}`}
        aria-current={selected ? 'true' : undefined}
        onClick={() => onSelectFile(node)}
      >
        <FileGlyph ext={node.ext} />
        <span>{node.name}</span>
      </button>
    </li>
  )
}

export default function FileExplorer({
  selectedFileId, onSelectFile, tree = [], projectName = 'project', onOpenFolder,
}: Props) {
  return (
    <aside id="source-files" className="explorer" aria-label="Source files" tabIndex={-1}>
      <div className="pane-title">
        <span>Files</span>
        <button type="button" title="Open local folder" aria-label="Open local folder" onClick={onOpenFolder} disabled={!onOpenFolder}>+</button>
      </div>
      <div className="project-heading"><span>{projectName}</span></div>
      <nav className="tree" aria-label="Source file navigation">
        <ul className="tree-list">
          {tree.map((node) => (
            <Tree key={node.id} node={node} depth={0} selectedFileId={selectedFileId} onSelectFile={onSelectFile} />
          ))}
        </ul>
      </nav>
      <button type="button" className="open-project" onClick={onOpenFolder} disabled={!onOpenFolder}>Open local folder</button>
    </aside>
  )
}
