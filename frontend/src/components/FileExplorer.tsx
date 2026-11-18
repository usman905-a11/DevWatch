import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Tree, NodeRendererProps, TreeApi } from 'react-arborist'
import { ChevronDown, ChevronRight, FileCode2, Folder, FolderOpen, Loader2, RefreshCw, Search } from 'lucide-react'
import { FsEntry } from '../review/durable-client'

export interface TreeNodeData {
  id: string
  name: string
  path: string
  type: 'file' | 'dir'
  size: number
  isSymlink: boolean
  ignored: boolean
  loaded?: boolean
  loading?: boolean
  children?: TreeNodeData[]
}

interface FileExplorerProps {
  workspacePath: string | null
  selectedFile: string | null
  findingCounts?: Record<string, number>
  onSelectFile: (path: string) => void
  loadDir: (path: string) => Promise<FsEntry[]>
}

function filterTree(nodes: TreeNodeData[], query: string): TreeNodeData[] {
  const q = query.trim().toLowerCase()
  if (!q) return nodes
  const out: TreeNodeData[] = []
  for (const node of nodes) {
    if (node.type === 'file') {
      if (node.name.toLowerCase().includes(q) || node.path.toLowerCase().includes(q)) {
        out.push(node)
      }
      continue
    }
    const filteredChildren = node.children ? filterTree(node.children, q) : []
    if (node.name.toLowerCase().includes(q) || filteredChildren.length > 0) {
      out.push({ ...node, children: filteredChildren })
    }
  }
  return out
}

function toTreeNode(entry: FsEntry): TreeNodeData {
  return {
    id: entry.path,
    name: entry.name,
    path: entry.path,
    type: entry.type,
    size: entry.size,
    isSymlink: entry.isSymlink,
    ignored: entry.ignored,
    loaded: entry.type === 'file',
    children: entry.type === 'dir' ? [] : undefined,
  }
}

function updateNodeInTree(
  nodes: TreeNodeData[],
  targetId: string,
  updater: (node: TreeNodeData) => TreeNodeData,
): TreeNodeData[] {
  return nodes.map(node => {
    if (node.id === targetId) return updater(node)
    if (node.children && node.children.length > 0 && targetId.startsWith(node.id + '/')) {
      return { ...node, children: updateNodeInTree(node.children, targetId, updater) }
    }
    return node
  })
}

export const FileExplorer: React.FC<FileExplorerProps> = ({
  workspacePath,
  selectedFile,
  findingCounts = {},
  onSelectFile,
  loadDir,
}) => {
  const [data, setData] = useState<TreeNodeData[]>([])
  const [filterText, setFilterText] = useState('')
  const [rootLoading, setRootLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [height, setHeight] = useState(500)
  const [reloadNonce, setReloadNonce] = useState(0)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const treeRef = useRef<TreeApi<TreeNodeData> | null>(null)
  const inFlightRef = useRef<Set<string>>(new Set())

  const visibleData = useMemo(() => filterTree(data, filterText), [data, filterText])

  useEffect(() => {
    const el = containerRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const update = () => {
      const next = Math.max(200, el.clientHeight)
      setHeight(next)
    }
    update()
    const observer = new ResizeObserver(update)
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (!workspacePath) {
      setData([])
      setError(null)
      return
    }
    let cancelled = false
    setRootLoading(true)
    setError(null)
    loadDir('')
      .then(entries => {
        if (!cancelled) setData(entries.map(toTreeNode))
      })
      .catch(err => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load directory')
      })
      .finally(() => {
        if (!cancelled) setRootLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [workspacePath, loadDir, reloadNonce])

  const handleToggle = useCallback(
    async (id: string) => {
      const findNode = (nodes: TreeNodeData[]): TreeNodeData | undefined => {
        for (const n of nodes) {
          if (n.id === id) return n
          if (n.children) {
            const found = findNode(n.children)
            if (found) return found
          }
        }
        return undefined
      }
      const target = findNode(data)
      if (!target || target.type !== 'dir' || target.loaded || target.loading || inFlightRef.current.has(id)) return

      inFlightRef.current.add(id)
      setData(prev => updateNodeInTree(prev, id, n => ({ ...n, loading: true })))
      try {
        const entries = await loadDir(target.path)
        setData(prev =>
          updateNodeInTree(prev, id, n => ({
            ...n,
            loaded: true,
            loading: false,
            children: entries.map(toTreeNode),
          })),
        )
      } catch (err) {
        setData(prev => updateNodeInTree(prev, id, n => ({ ...n, loading: false })))
        setError(err instanceof Error ? err.message : 'Failed to expand folder')
      } finally {
        inFlightRef.current.delete(id)
      }
    },
    [data, loadDir],
  )

  const renderNode = ({ node, style }: NodeRendererProps<TreeNodeData>) => {
    const isDir = node.data.type === 'dir'
    const isSelected = !isDir && selectedFile === node.data.path
    const count = !isDir ? (findingCounts[node.data.path] ?? 0) : 0
    return (
      <div
        style={style}
        role="treeitem"
        aria-selected={isSelected}
        onClick={() => {
          if (isDir) {
            node.toggle()
          } else {
            onSelectFile(node.data.path)
          }
        }}
        className={`explorer-row ${isSelected ? 'selected' : ''} ${node.data.ignored ? 'ignored' : ''}`}
        title={node.data.path}
      >
        <span className="explorer-chevron">
          {isDir ? (
            node.data.loading ? (
              <Loader2 className="icon-xs spin" />
            ) : node.isOpen ? (
              <ChevronDown className="icon-sm" />
            ) : (
              <ChevronRight className="icon-sm" />
            )
          ) : null}
        </span>
        {isDir ? (
          node.isOpen ? (
            <FolderOpen className="icon-sm icon-folder" />
          ) : (
            <Folder className="icon-sm icon-folder" />
          )
        ) : (
          <FileCode2 className="icon-sm icon-file" />
        )}
        <span className="explorer-label">{node.data.name}</span>
        {count > 0 && <span className="explorer-finding-badge">{count}</span>}
      </div>
    )
  }

  return (
    <div className="explorer-panel">
      <div className="sidebar-panel-header">
        <span className="sidebar-panel-title">Explorer</span>
        <button
          type="button"
          className="icon-btn"
          aria-label="Refresh explorer"
          title="Refresh explorer"
          disabled={!workspacePath || rootLoading}
          onClick={() => setReloadNonce(n => n + 1)}
        >
          <RefreshCw className={`icon-xs ${rootLoading ? 'spin' : ''}`} />
        </button>
      </div>
      <div className="sidebar-search-box">
        <Search className="icon-xs icon-muted" />
        <input
          type="search"
          aria-label="Filter files"
          placeholder="Filter files..."
          value={filterText}
          onChange={e => setFilterText(e.target.value)}
        />
      </div>
      {error && (
        <div className="explorer-error" role="alert">
          {error}
        </div>
      )}
      <div ref={containerRef} className="explorer-tree-host">
        {!workspacePath ? (
          <div className="explorer-empty">Open a local folder to browse files.</div>
        ) : rootLoading ? (
          <div className="explorer-empty explorer-loading">
            <Loader2 className="icon-sm spin" /> Loading workspace...
          </div>
        ) : visibleData.length === 0 ? (
          <div className="explorer-empty">{filterText ? 'No matching files.' : 'Folder is empty.'}</div>
        ) : (
          <Tree<TreeNodeData>
            ref={treeRef}
            data={visibleData}
            openByDefault={false}
            width="100%"
            height={height}
            indent={14}
            rowHeight={24}
            disableDrag
            disableDrop
            disableEdit
            onToggle={id => {
              void handleToggle(id)
            }}
          >
            {renderNode}
          </Tree>
        )}
      </div>
    </div>
  )
}
