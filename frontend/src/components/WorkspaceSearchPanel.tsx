import React, { useMemo, useState } from 'react'
import { FileCode2, Search } from 'lucide-react'
import type { OpenTab } from './CodeEditor'

interface SearchHit {
  path: string
  line: number
  preview: string
}

interface WorkspaceSearchPanelProps {
  tabs: OpenTab[]
  initialQuery?: string
  onJumpToLine: (path: string, line: number) => void
}

export const WorkspaceSearchPanel: React.FC<WorkspaceSearchPanelProps> = ({
  tabs,
  initialQuery = '',
  onJumpToLine,
}) => {
  const [query, setQuery] = useState(initialQuery)

  const hits = useMemo<SearchHit[]>(() => {
    const q = query.trim().toLowerCase()
    if (!q) return []
    const out: SearchHit[] = []
    for (const tab of tabs) {
      if (tab.path.toLowerCase().includes(q) && (!tab.file?.content || out.length < 80)) {
        out.push({ path: tab.path, line: 1, preview: `File match: ${tab.path}` })
      }
      const content = tab.file?.content
      if (!content) continue
      const lines = content.split('\n')
      for (let i = 0; i < lines.length && out.length < 120; i++) {
        if (lines[i].toLowerCase().includes(q)) {
          out.push({ path: tab.path, line: i + 1, preview: lines[i].trim() })
        }
      }
    }
    return out
  }, [tabs, query])

  return (
    <div className="sidebar-panel">
      <div className="sidebar-panel-header">
        <span className="sidebar-panel-title">Search Open Files</span>
      </div>
      <div className="sidebar-search-box">
        <Search className="icon-xs icon-muted" />
        <input
          type="search"
          aria-label="Search loaded source buffers"
          placeholder="Search opened files..."
          value={query}
          onChange={e => setQuery(e.target.value)}
        />
      </div>
      {tabs.length === 0 ? (
        <div className="sidebar-empty">Open files from the Explorer to search their source lines.</div>
      ) : !query.trim() ? (
        <div className="sidebar-empty">Enter text to search across {tabs.length} opened file(s).</div>
      ) : hits.length === 0 ? (
        <div className="sidebar-empty">No matches in opened buffers.</div>
      ) : (
        <ul className="search-hit-list" aria-label="Source search matches">
          {hits.map((hit, idx) => (
            <li key={`${hit.path}:${hit.line}:${idx}`}>
              <button
                type="button"
                className="search-hit-btn"
                onClick={() => onJumpToLine(hit.path, hit.line)}
              >
                <span className="search-hit-file">
                  <FileCode2 className="icon-xs" /> {hit.path}:{hit.line}
                </span>
                <code className="search-hit-preview">{hit.preview}</code>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

