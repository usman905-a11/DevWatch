import { useEffect, useRef } from 'react'
import type { FileNode } from './FileExplorer'

interface Props {
  file: FileNode | null
  openFiles: FileNode[]
  onSelectFile: (f: FileNode) => void
  onCloseFile: (id: string) => void
  highlightLine: number | null
}

const token = (s: string) =>
  s
    .split(
      /(\/\/.*|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`[^`]*`|\b(?:import|export|from|const|let|var|return|async|await|function|def|class|if|else|elif|interface|type|new|throw|try|catch|except|finally|true|false|null|undefined|None|True|False)\b|\b\d+\b)/g
    )
    .map((p, i) => {
      const c = p.startsWith('//') || p.startsWith('#')
        ? 'comment'
        : /^['"`]/.test(p)
        ? 'string'
        : /^(import|export|from|const|let|var|return|async|await|function|def|class|if|else|elif|interface|type|new|throw|try|catch|except|finally|true|false|null|undefined|None|True|False)$/.test(
            p
          )
        ? 'keyword'
        : /^\d+$/.test(p)
        ? 'number'
        : ''
      return (
        <span key={i} className={c}>
          {p}
        </span>
      )
    })

export default function CodeEditor({
  file,
  openFiles,
  onSelectFile,
  onCloseFile,
  highlightLine,
}: Props) {
  const lineRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    lineRef.current?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [highlightLine])

  const lines = (file?.content ?? '').split('\n')

  return (
    <main className="editor">
      <div className="tabs">
        {openFiles.map((f) => (
          <div
            key={f.id}
            className={`tab ${f.id === file?.id ? 'active' : ''}`}
            onClick={() => onSelectFile(f)}
          >
            <span className="tab-dot" />
            {f.name}
            <button
              onClick={(e) => {
                e.stopPropagation()
                onCloseFile(f.id)
              }}
            >
              ×
            </button>
          </div>
        ))}
      </div>

      {file ? (
        <>
          <div className="editor-meta">
            <span>{file.id}</span>
            <span>UTF-8 &nbsp;&nbsp; • &nbsp;&nbsp; DevWatch Code Auditor</span>
          </div>

          <div className="code" role="region" aria-label="Code editor">
            {lines.map((l, i) => (
              <div
                ref={highlightLine === i + 1 ? lineRef : undefined}
                key={i}
                className={`line ${highlightLine === i + 1 ? 'flagged' : ''}`}
              >
                <span className="line-number">{i + 1}</span>
                <code>{token(l)}</code>
              </div>
            ))}
          </div>
        </>
      ) : (
        <div className="empty-editor">
          <div className="empty-orbit" aria-hidden="true">
            <svg className="detective-mark" viewBox="0 0 72 72" fill="none">
              <path
                d="M18 26.5h36l-3.1-7.1c-.5-1.1-1.6-1.9-2.8-1.9H24c-1.2 0-2.3.8-2.8 1.9L18 26.5Z"
                fill="currentColor"
                opacity=".96"
              />
              <path d="M15.5 28.5h41" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" />
              <path
                d="M25 30.5v5.1c0 7.2 4.6 12.9 11 12.9s11-5.7 11-12.9v-5.1"
                stroke="currentColor"
                strokeWidth="2.6"
                strokeLinecap="round"
              />
              <path d="M29.7 38.1h.1M42.2 38.1h.1" stroke="currentColor" strokeWidth="3.3" strokeLinecap="round" />
              <path d="M31.5 44.2c2.6 1.7 6.4 1.7 9 0" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" />
              <path
                d="M19.3 58.5c2.5-6.7 8.5-10.3 16.7-10.3s14.2 3.6 16.7 10.3"
                stroke="currentColor"
                strokeWidth="2.8"
                strokeLinecap="round"
              />
              <circle cx="50.5" cy="49.5" r="6.1" stroke="currentColor" strokeWidth="2.4" />
              <path d="m55 54 5 5" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
            </svg>
          </div>
          <span className="empty-kicker">Review workspace</span>
          <h2>
            Make every change
            <br />
            intentional.
          </h2>
          <p>Open a source file to inspect it, or run a review to surface the work that matters.</p>
          <div className="empty-actions">
            <span>
              <kbd>⌘</kbd>
              <kbd>O</kbd> Open folder
            </span>
            <span>
              <kbd>⌘</kbd>
              <kbd>↵</kbd> Run review
            </span>
          </div>
        </div>
      )}
    </main>
  )
}
