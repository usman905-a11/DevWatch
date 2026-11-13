import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Tree, NodeRendererProps, TreeApi } from 'react-arborist'
import { ChevronDown, ChevronRight, FileCode2, Folder, FolderOpen, Loader2 } from 'lucide-react'
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
  onSelectFile: (path: string) => void
  loadDir: (path: string) => Promise<FsEntry[]>
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
  onSelectFile,
  loadDir,
}) => {
  const [data, setData] = useState<TreeNodeData[]>([])
  const [rootLoading, setRootLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [height, setHeight] = useState(500)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const treeRef = useRef<TreeApi<TreeNodeData> | null>(null)

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
  }, [workspacePath, loadDir])

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
      if (!target || target.type !== 'dir' || target.loaded || target.loading) return

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
      }
    },
    [data, loadDir],
  )

  const renderNode = ({ node, style }: NodeRendererProps<TreeNodeData>) => {
    const isDir = node.data.type === 'dir'
    const isSelected = !isDir && selectedFile === node.data.path
    return (
      <div
        style={style}
        role="treeitem"
        aria-selected={isSelected}
        onClick={() => {
          if (isDir) {
            void handleToggle(node.data.id)
            node.toggle()
          } else {
            onSelectFile(node.data.path)
          }
        }}
        className={`flex items-center gap-1.5 px-2 py-0.5 text-[13px] cursor-pointer select-none truncate ${
          isSelected
            ? 'bg-sky-500/20 text-sky-200'
            : 'text-zinc-200 hover:bg-zinc-800/70'
        } ${node.data.ignored ? 'opacity-45' : ''}`}
        title={node.data.path}
      >
        <span className="w-3.5 h-3.5 flex items-center justify-center shrink-0 text-zinc-400">
          {isDir ? (
            node.data.loading ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : node.isOpen ? (
              <ChevronDown className="w-3.5 h-3.5" />
            ) : (
              <ChevronRight className="w-3.5 h-3.5" />
            )
          ) : null}
        </span>
        {isDir ? (
          node.isOpen ? (
            <FolderOpen className="w-4 h-4 text-amber-400/90 shrink-0" />
          ) : (
            <Folder className="w-4 h-4 text-amber-400/80 shrink-0" />
          )
        ) : (
          <FileCode2 className="w-4 h-4 text-sky-400/80 shrink-0" />
        )}
        <span className="truncate">{node.data.name}</span>
      </div>
    )
  }

  return (
    <div ref={containerRef} className="h-full w-full flex flex-col overflow-hidden bg-zinc-950/60">
      {error && (
        <div className="px-3 py-1.5 text-xs text-red-400 bg-red-950/40 border-b border-red-900/40">
          {error}
        </div>
      )}
      {!workspacePath ? (
        <div className="p-4 text-xs text-zinc-500">Open a local folder to browse files.</div>
      ) : rootLoading ? (
        <div className="p-4 text-xs text-zinc-400 flex items-center gap-2">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading workspace...
        </div>
      ) : data.length === 0 ? (
        <div className="p-4 text-xs text-zinc-500">Folder is empty.</div>
      ) : (
        <Tree<TreeNodeData>
          ref={treeRef}
          data={data}
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
  )
}
