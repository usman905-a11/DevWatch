import React, { useMemo, useState } from 'react'
import { ArrowUp, ChevronRight, Folder, HardDrive, Loader2, X } from 'lucide-react'
import type { WorkspaceBrowseResponse } from '../review/durable-client'

interface FolderPickerModalProps {
  open: boolean
  browseData: WorkspaceBrowseResponse | null
  loading: boolean
  error: string | null
  onNavigate: (path: string) => void
  onSelectFolder: (path: string) => void
  onClose: () => void
}

export const FolderPickerModal: React.FC<FolderPickerModalProps> = ({
  open,
  browseData,
  loading,
  error,
  onNavigate,
  onSelectFolder,
  onClose,
}) => {
  const [filter, setFilter] = useState('')

  const visibleDirs = useMemo(() => {
    const dirs = browseData?.directories ?? []
    const q = filter.trim().toLowerCase()
    return q ? dirs.filter(d => d.name.toLowerCase().includes(q)) : dirs
  }, [browseData?.directories, filter])

  if (!open) return null

  return (
    <div
      className="folder-modal-backdrop"
      onKeyDown={e => {
        if (e.key === 'Escape') onClose()
      }}
    >
      <div
        className="folder-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Open local folder"
      >
        <div className="folder-modal-header">
          <div className="folder-modal-title">
            <Folder className="icon-sm icon-folder" />
            <h2>Open Local Folder</h2>
          </div>
          <button
            type="button"
            className="icon-btn"
            aria-label="Close folder picker"
            onClick={onClose}
          >
            <X className="icon-sm" />
          </button>
        </div>

        <div className="folder-modal-body">
          <aside className="folder-modal-roots" aria-label="Quick locations">
            <div className="folder-section-label">Locations</div>
            {(browseData?.roots ?? []).map(root => {
              const active = browseData?.current_path === root.path
              return (
                <button
                  key={root.path}
                  type="button"
                  className={`folder-root-btn ${active ? 'active' : ''}`}
                  onClick={() => {
                    setFilter('')
                    onNavigate(root.path)
                  }}
                >
                  <HardDrive className="icon-xs" />
                  <span>{root.name}</span>
                </button>
              )
            })}
          </aside>

          <div className="folder-modal-main">
            <div className="folder-nav-bar">
              <button
                type="button"
                className="header-button"
                disabled={!browseData?.parent_path || loading}
                onClick={() => {
                  if (browseData?.parent_path) {
                    setFilter('')
                    onNavigate(browseData.parent_path)
                  }
                }}
              >
                <ArrowUp className="icon-xs" /> Up
              </button>
              <code className="folder-current-path" title={browseData?.current_path ?? ''}>
                {browseData?.current_path ?? 'Loading...'}
              </code>
            </div>

            <div className="folder-filter-bar">
              <input
                type="search"
                aria-label="Filter folders"
                placeholder="Filter subfolders..."
                value={filter}
                onChange={e => setFilter(e.target.value)}
              />
            </div>

            {error && (
              <div className="review-error" role="alert">
                {error}
              </div>
            )}

            <div className="folder-dir-list" aria-label="Subfolders">
              {loading ? (
                <div className="folder-list-empty">
                  <Loader2 className="icon-sm spin" /> Loading folders...
                </div>
              ) : visibleDirs.length === 0 ? (
                <div className="folder-list-empty">
                  {filter ? 'No matching subfolders.' : 'No subfolders inside this directory.'}
                </div>
              ) : (
                visibleDirs.map(dir => (
                  <button
                    key={dir.path}
                    type="button"
                    className="folder-dir-row"
                    onClick={() => {
                      setFilter('')
                      onNavigate(dir.path)
                    }}
                  >
                    <Folder className="icon-sm icon-folder" />
                    <span className="folder-dir-name">{dir.name}</span>
                    <ChevronRight className="icon-xs icon-muted" />
                  </button>
                ))
              )}
            </div>
          </div>
        </div>

        <div className="folder-modal-footer">
          <button type="button" className="header-button" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="review-button"
            disabled={!browseData?.current_path || loading}
            onClick={() => {
              if (browseData?.current_path) {
                onSelectFolder(browseData.current_path)
              }
            }}
          >
            Open Selected Folder
          </button>
        </div>
      </div>
    </div>
  )
}

