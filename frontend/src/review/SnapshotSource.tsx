import { useEffect, useState } from 'react'
import { SourceExcerpt } from './wire'

export function SnapshotSource({ source, error, path, onRead }: { source: SourceExcerpt | null; error: string | null;
  path: string; onRead: (start: number, end: number) => void }) {
  const [start, setStart] = useState(1), [end, setEnd] = useState(1)
  useEffect(() => { setStart(source?.start_line ?? 1); setEnd(source?.end_line ?? 1) }, [source, path])
  return <main id="source-pane" className="editor" aria-label="Snapshot source preview" tabIndex={-1}>
    <div className="editor-meta"><span>{path || 'Select a snapshot file'}</span><span>Read-only snapshot</span></div>
    {path && <form className="excerpt-controls" onSubmit={event => { event.preventDefault(); onRead(start, end) }}>
      <label>Start line<input type="number" min="1" value={start} onChange={event => setStart(Number(event.target.value))} /></label>
      <label>End line<input type="number" min={start} max={start + 199} value={end} onChange={event => setEnd(Number(event.target.value))} /></label>
      <button className="header-button" type="submit">Load excerpt</button>
    </form>}
    <p className="source-notice">Excerpts contain up to 200 lines and 6 KB. Choose a smaller range if a line is too large.</p>
    {error && <div className="source-error" role="alert">{error}</div>}
    {source ? <div className="code" tabIndex={0} role="region" aria-label="Read-only snapshot excerpt">
      {source.data.split('\n').map((line, index) => <div className="line" key={index}>
        <span className="line-number" aria-hidden="true">{source.start_line + index}</span>
        <code aria-label={`Line ${source.start_line + index}`}>{line}</code>
      </div>)}
    </div> : <div className="empty-editor"><h2>Snapshot source</h2><p>Open a file from a submitted job to inspect its immutable source.</p></div>}
  </main>
}
