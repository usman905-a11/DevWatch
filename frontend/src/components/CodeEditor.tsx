import React, { useEffect, useRef } from 'react'
import Editor, { OnMount } from '@monaco-editor/react'
import type { editor as MonacoEditor } from 'monaco-editor'
import { AlertTriangle, FileCode2, FileWarning, Loader2, X } from 'lucide-react'
import { FsReadResponse } from '../review/durable-client'

export interface OpenTab {
  path: string
  loading: boolean
  error?: string | null
  file?: FsReadResponse | null
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
  onSelectTab,
  onCloseTab,
}) => {
  const editorRef = useRef<MonacoEditor.IStandaloneCodeEditor | null>(null)
  const monacoRef = useRef<typeof import('monaco-editor') | null>(null)
  const decorationsRef = useRef<string[]>([])

  const activeTab = tabs.find(tab => tab.path === activePath) ?? null

  const applyHighlight = (range: LineRange | null) => {
    const ed = editorRef.current
    const monaco = monacoRef.current
    if (!ed || !monaco) return
    if (!range || !activeTab || range.path !== activeTab.path || !activeTab.file?.content) {
      decorationsRef.current = ed.deltaDecorations(decorationsRef.current, [])
      return
    }
    const start = Math.max(1, range.startLine)
    const end = Math.max(start, range.endLine)
    ed.revealLineInCenter(start)
    ed.setPosition({ lineNumber: start, column: 1 })
    decorationsRef.current = ed.deltaDecorations(decorationsRef.current, [
      {
        range: new monaco.Range(start, 1, end, 1),
        options: {
          isWholeLine: true,
          className: 'bg-amber-500/20 border-l-2 border-amber-400',
        },
      },
    ])
  }

  useEffect(() => {
    applyHighlight(highlightRange)
  }, [highlightRange, activeTab?.path, activeTab?.file?.content])

  const handleMount: OnMount = (ed, monaco) => {
    editorRef.current = ed
    monacoRef.current = monaco
    applyHighlight(highlightRange)
  }

  return (
    <div className="h-full w-full flex flex-col bg-zinc-950 overflow-hidden">
      {/* Tab bar */}
      <div className="flex items-center border-b border-zinc-800 bg-zinc-900/70 overflow-x-auto shrink-0 min-h-[34px]">
        {tabs.length === 0 ? (
          <div className="px-3 text-xs text-zinc-500">No open files</div>
        ) : (
          tabs.map(tab => {
            const isActive = tab.path === activePath
            const name = tab.path.split('/').pop() ?? tab.path
            return (
              <div
                key={tab.path}
                onClick={() => onSelectTab(tab.path)}
                title={tab.path}
                className={`group flex items-center gap-1.5 px-3 py-1.5 text-xs border-r border-zinc-800 cursor-pointer shrink-0 ${
                  isActive
                    ? 'bg-zinc-950 text-zinc-100 border-t-2 border-t-sky-500'
                    : 'text-zinc-400 hover:bg-zinc-800/60 hover:text-zinc-200'
                }`}
              >
                <FileCode2 className="w-3.5 h-3.5 text-sky-400/80 shrink-0" />
                <span className="max-w-[160px] truncate">{name}</span>
                <button
                  type="button"
                  aria-label={`Close ${name}`}
                  onClick={e => {
                    e.stopPropagation()
                    onCloseTab(tab.path)
                  }}
                  className="ml-1 rounded p-0.5 text-zinc-500 hover:text-zinc-200 hover:bg-zinc-700/60"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            )
          })
        )}
      </div>

      {/* Editor body */}
      <div className="flex-1 min-h-0 relative">
        {!activeTab ? (
          <div className="h-full flex flex-col items-center justify-center text-zinc-500 text-sm gap-2">
            <FileCode2 className="w-8 h-8 text-zinc-700" />
            <p>Select a file from the explorer or click a finding to inspect it.</p>
          </div>
        ) : activeTab.loading ? (
          <div className="h-full flex items-center justify-center text-zinc-400 text-sm gap-2">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading {activeTab.path}...
          </div>
        ) : activeTab.error ? (
          <div className="h-full flex flex-col items-center justify-center text-red-400 text-sm gap-2 p-6 text-center">
            <AlertTriangle className="w-7 h-7" />
            <p className="font-medium">Unable to open {activeTab.path}</p>
            <p className="text-xs text-red-300/80">{activeTab.error}</p>
          </div>
        ) : activeTab.file?.tooLarge ? (
          <div className="h-full flex flex-col items-center justify-center text-amber-300 text-sm gap-2 p-6 text-center">
            <FileWarning className="w-8 h-8 text-amber-400" />
            <p className="font-medium">File is too large to display in the editor</p>
            <p className="text-xs text-zinc-400">
              {activeTab.path} is {formatBytes(activeTab.file.size)} (limit: {formatBytes(activeTab.file.maxBytes)}).
            </p>
          </div>
        ) : activeTab.file?.binary ? (
          <div className="h-full flex flex-col items-center justify-center text-zinc-300 text-sm gap-2 p-6 text-center">
            <FileWarning className="w-8 h-8 text-zinc-400" />
            <p className="font-medium">Binary file cannot be displayed</p>
            <p className="text-xs text-zinc-500">
              {activeTab.path} ({formatBytes(activeTab.file.size)}) appears to be binary.
            </p>
          </div>
        ) : (
          <Editor
            height="100%"
            theme="vs-dark"
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

