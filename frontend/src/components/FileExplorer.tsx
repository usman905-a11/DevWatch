import { useState } from 'react'

export interface FileNode {
  id: string
  name: string
  type: 'file' | 'folder'
  ext?: string
  content?: string
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
  ts: '#72a7ff',
  tsx: '#58c7d9',
  js: '#f3c858',
  jsx: '#f3c858',
  json: '#f3c858',
  css: '#bc9cff',
  md: '#a9b1bd',
  html: '#f99b7c',
  py: '#72d09c',
  env: '#f1c24e',
  sh: '#48b085',
  toml: '#e5c07b',
}

function FileGlyph({ ext }: { ext?: string }) {
  return (
    <span
      style={{
        color: colors[ext ?? ''] ?? '#8e8e93',
        width: 14,
        textAlign: 'center',
        fontFamily: 'JetBrains Mono, monospace',
        fontSize: 10,
        fontWeight: 600,
      }}
    >
      {ext === 'tsx' ? '⚛' : ext === 'py' ? '🐍' : ext === 'ts' ? 'TS' : ext === 'json' ? '{}' : '·'}
    </span>
  )
}

function Tree({
  node,
  depth,
  selectedFileId,
  onSelectFile,
}: {
  node: FileNode
  depth: number
  selectedFileId: string | null
  onSelectFile: (file: FileNode) => void
}) {
  const [open, setOpen] = useState(depth < 1)
  if (node.type === 'folder') {
    return (
      <>
        <button
          onClick={() => setOpen(!open)}
          className="tree-row"
          style={{ paddingLeft: 12 + depth * 14 }}
        >
          <span className="chev">{open ? '⌄' : '›'}</span>
          <span className="folder">{open ? '▾' : '▸'}</span>
          {node.name}
        </button>
        {open &&
          node.children?.map((n) => (
            <Tree
              key={n.id}
              node={n}
              depth={depth + 1}
              selectedFileId={selectedFileId}
              onSelectFile={onSelectFile}
            />
          ))}
      </>
    )
  }

  return (
    <button
      onClick={() => onSelectFile(node)}
      className={`tree-row ${selectedFileId === node.id ? 'selected' : ''}`}
      style={{ paddingLeft: 28 + depth * 14 }}
    >
      <FileGlyph ext={node.ext} />
      <span>{node.name}</span>
    </button>
  )
}

export default function FileExplorer({
  selectedFileId,
  onSelectFile,
  tree = [],
  projectName = 'project',
  onOpenFolder,
}: Props) {
  return (
    <aside className="explorer">
      <div className="pane-title">
        <span>Project</span>
        <button title="Open folder" onClick={onOpenFolder}>
          ＋
        </button>
      </div>

      <div className="project-heading">
        <span className="status-dot" />
        <span>{projectName}</span>
      </div>

      <div className="tree">
        {tree.map((n) => (
          <Tree
            key={n.id}
            node={n}
            depth={0}
            selectedFileId={selectedFileId}
            onSelectFile={onSelectFile}
          />
        ))}
      </div>

      <button className="open-project" onClick={onOpenFolder}>
        ⌘ &nbsp; Open local folder
      </button>
    </aside>
  )
}
