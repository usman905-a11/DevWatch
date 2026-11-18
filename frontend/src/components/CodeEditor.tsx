import React, { useEffect, useMemo, useRef, useState } from 'react'
import Editor, { OnMount } from '@monaco-editor/react'
import type { editor as MonacoEditor } from 'monaco-editor'
import { AlertTriangle, FileCode2, FileWarning, Lock, Loader2, X } from 'lucide-react'
import { FsReadResponse } from '../review/durable-client'
import type { ExcerptBuffer } from '../review/source-buffer'
import type { ReportFinding } from '../review/wire'
import { DEWATCH_MONACO_THEME, ensureLocalMonaco, registerDeWatchMonacoTheme } from './monacoSetup'

export interface OpenTab {
  path: string
  loading: boolean
  error?: string | null
  file?: FsReadResponse | null
  excerptBuffer?: ExcerptBuffer | null
}

export interface LineRange {
  path: string
  startLine: number
  endLine: number
}

interface CodeEditorProps {
  tabs: OpenTab[]
  activePath: string | null
  highlightRange: LineRange | null
  findings?: ReportFinding[]
  onSelectTab: (path: string) => void
  onCloseTab: (path: string) => void
}

const EXTENSION_LANGUAGES: Record<string, string> = {
  ts: 'typescript',
  tsx: 'typescript',
  js: 'javascript',
  jsx: 'javascript',
  mjs: 'javascript',
  cjs: 'javascript',
  py: 'python',
  json: 'json',
  md: 'markdown',
  markdown: 'markdown',
  css: 'css',
  scss: 'scss',
  html: 'html',
  htm: 'html',
  xml: 'xml',
  svg: 'xml',
  yaml: 'yaml',
  yml: 'yaml',
  toml: 'ini',
  ini: 'ini',
  sh: 'shell',
  bash: 'shell',
  ps1: 'powershell',
  sql: 'sql',
  rs: 'rust',
  go: 'go',
  java: 'java',
  kt: 'kotlin',
  c: 'c',
  h: 'c',
  cpp: 'cpp',
  hpp: 'cpp',
  cs: 'csharp',
  rb: 'ruby',
  php: 'php',
  dockerfile: 'dockerfile',
}

export function detectMonacoLanguage(path: string): string {
  const base = path.split('/').pop()?.toLowerCase() ?? ''
  if (base === 'dockerfile') return 'dockerfile'
  const dot = base.lastIndexOf('.')
  if (dot < 0) return 'plaintext'
  const ext = base.slice(dot + 1)
  return EXTENSION_LANGUAGES[ext] ?? 'plaintext'
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

export const CodeEditor: React.FC<CodeEditorProps> = ({
  tabs,
  activePath,
  highlightRange,
  findings = [],
  onSelectTab,
  onCloseTab,
}) => {
  const editorRef = useRef<MonacoEditor.IStandaloneCodeEditor | null>(null)
  const monacoRef = useRef<typeof import('monaco-editor') | null>(null)
  const decorationsRef = useRef<string[]>([])
  const [monacoReady, setMonacoReady] = useState(false)

  useEffect(() => {
    let cancelled = false
    void ensureLocalMonaco()
      .then(() => { if (!cancelled) setMonacoReady(true) })
      .catch(() => { if (!cancelled) setMonacoReady(true) })
    return () => { cancelled = true }
  }, [])

  const activeTab = tabs.find(tab => tab.path === activePath) ?? null

  const findingCountByPath = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const f of findings) {
      counts[f.location.file_path] = (counts[f.location.file_path] ?? 0) + 1
    }
    return counts
  }, [findings])

  const activeFileFindings = useMemo(
    () => (activeTab ? findings.filter(f => f.location.file_path === activeTab.path) : []),
    [activeTab, findings],
  )

  const applyDecorations = (range: LineRange | null) => {
    const ed = editorRef.current
    const monaco = monacoRef.current
    if (!ed || !monaco) return
    if (!activeTab || !activeTab.file?.content) {
      decorationsRef.current = ed.deltaDecorations(decorationsRef.current, [])
      return
    }
    const nextDecorations: MonacoEditor.IModelDeltaDecoration[] = activeFileFindings.map(finding => {
      const start = Math.max(1, finding.location.start_line)
      const end = Math.max(start, finding.location.end_line)
      return {
        range: new monaco.Range(start, 1, end, 1),
        options: {
          isWholeLine: true,
          className: `editor-finding-inline editor-finding-${finding.severity}`,
          linesDecorationsClassName: `editor-finding-gutter editor-finding-gutter-${finding.severity}`,
          hoverMessage: [{ value: `**[${finding.severity.toUpperCase()}]** ${finding.title}` }],
        },
      }
    })
    if (range && range.path === activeTab.path) {
      const start = Math.max(1, range.startLine)
      const end = Math.max(start, range.endLine)
      ed.revealLineInCenter(start)
      ed.setPosition({ lineNumber: start, column: 1 })
      nextDecorations.push({
        range: new monaco.Range(start, 1, end, 1),
        options: {
          isWholeLine: true,
          className: 'editor-finding-highlight',
          linesDecorationsClassName: 'editor-finding-gutter',
        },
      })
    }
    decorationsRef.current = ed.deltaDecorations(decorationsRef.current, nextDecorations)
  }

  useEffect(() => {
    applyDecorations(highlightRange)
  }, [highlightRange, activeTab?.path, activeTab?.file?.content, activeFileFindings])

  const handleMount: OnMount = (ed, monaco) => {
    editorRef.current = ed
    monacoRef.current = monaco
    registerDeWatchMonacoTheme(monaco)
    monaco.editor.setTheme(DEWATCH_MONACO_THEME)
    applyDecorations(highlightRange)
  }

  return (
    <div className="code-editor">
      <div className="editor-tabbar" role="tablist" aria-label="Open source files">
        {tabs.length === 0 ? (
          <div className="editor-tabbar-empty">No open files</div>
        ) : (
          tabs.map(tab => {
            const isActive = tab.path === activePath
            const name = tab.path.split('/').pop() ?? tab.path
            const tabFindings = findingCountByPath[tab.path] ?? 0
            return (
              <div
                key={tab.path}
                role="tab"
                aria-selected={isActive}
                onClick={() => onSelectTab(tab.path)}
                title={tab.path}
                className={`editor-tab ${isActive ? 'active' : ''}`}
              >
                <FileCode2 className="icon-xs icon-file" />
                <span className="editor-tab-name">{name}</span>
                {tabFindings > 0 && <span className="editor-tab-badge">{tabFindings}</span>}
                <button
                  type="button"
                  aria-label={`Close ${name}`}
                  onClick={e => {
                    e.stopPropagation()
                    onCloseTab(tab.path)
                  }}
                  className="editor-tab-close"
                >
                  <X className="icon-xs" />
                </button>
              </div>
            )
          })
        )}
      </div>

      {activeTab && (
        <div className="editor-breadcrumb">
          <span className="breadcrumb-path">{activeTab.path}</span>
          {highlightRange && highlightRange.path === activeTab.path && (
            <span className="breadcrumb-range">
              Line {highlightRange.startLine}
              {highlightRange.endLine > highlightRange.startLine ? `–${highlightRange.endLine}` : ''}
            </span>
          )}
          <span className="breadcrumb-spacer" />
          {activeFileFindings.length > 0 && (
            <span className="breadcrumb-findings">{activeFileFindings.length} finding(s) in file</span>
          )}
          <span className="breadcrumb-lang">{detectMonacoLanguage(activeTab.path)}</span>
          <span className="breadcrumb-readonly">
            <Lock className="icon-xs" /> Read-Only
          </span>
        </div>
      )}

      <div className="editor-body">
        {!activeTab ? (
          <div className="editor-state">
            <FileCode2 className="icon-lg icon-muted" />
            <p>Select a file from the explorer or click a finding to inspect it.</p>
          </div>
        ) : activeTab.loading ? (
          <div className="editor-state editor-state-inline">
            <Loader2 className="icon-sm spin" /> Loading {activeTab.path}...
          </div>
        ) : activeTab.error ? (
          <div className="editor-state editor-state-error">
            <AlertTriangle className="icon-lg" />
            <p className="editor-state-title">Unable to open {activeTab.path}</p>
            <p className="editor-state-detail">{activeTab.error}</p>
          </div>
        ) : activeTab.file?.tooLarge ? (
          <div className="editor-state editor-state-warn">
            <FileWarning className="icon-lg" />
            <p className="editor-state-title">File is too large to display in the editor</p>
            <p className="editor-state-detail">
              {activeTab.path} is {formatBytes(activeTab.file.size)} (limit: {formatBytes(activeTab.file.maxBytes)}).
            </p>
          </div>
        ) : activeTab.file?.binary ? (
          <div className="editor-state editor-state-warn">
            <FileWarning className="icon-lg" />
            <p className="editor-state-title">Binary file cannot be displayed</p>
            <p className="editor-state-detail">
              {activeTab.path} ({formatBytes(activeTab.file.size)}) appears to be binary.
            </p>
          </div>
        ) : !monacoReady ? (
          <div className="editor-state editor-state-inline">
            <Loader2 className="icon-sm spin" /> Loading editor...
          </div>
        ) : (
          <Editor
            height="100%"
            theme={DEWATCH_MONACO_THEME}
            path={activeTab.path}
            language={detectMonacoLanguage(activeTab.path)}
            value={activeTab.file?.content ?? ''}
            onMount={handleMount}
            options={{
              readOnly: true,
              minimap: { enabled: true },
              scrollBeyondLastLine: false,
              automaticLayout: true,
              fontSize: 13,
              lineNumbers: 'on',
              renderWhitespace: 'selection',
              wordWrap: 'off',
            }}
          />
        )}
      </div>
    </div>
  )
}

