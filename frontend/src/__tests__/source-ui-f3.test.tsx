import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import FileExplorer, { FileNode } from '../components/FileExplorer'

const authA: FileNode = { id: 'src/a/auth.py', name: 'auth.py', type: 'file', ext: 'py' }
const authB: FileNode = { id: 'src/b/auth.py', name: 'auth.py', type: 'file', ext: 'py' }

describe('F3 source controls', () => {
  it('exposes folder expansion and selected files through native buttons', () => {
    const markup = renderToStaticMarkup(
      <FileExplorer
        tree={[{ id: 'src', name: 'src', type: 'folder', children: [authA] }]}
        projectName="fixture"
        selectedFileId={authA.id}
        onSelectFile={() => {}}
        onOpenFolder={() => {}}
      />,
    )
    expect(markup).toContain('aria-expanded="true"')
    expect(markup).toContain('aria-controls="folder-src"')
    expect(markup).toContain('aria-current="true"')
    expect(markup).toContain('aria-label="Open src/a/auth.py"')
  })

  it('keeps full paths visible for duplicate basenames', () => {
    const markup = renderToStaticMarkup(<FileExplorer tree={[authA, authB]} selectedFileId={authB.id} onSelectFile={() => {}} />)
    expect(markup).toContain('aria-label="Open src/a/auth.py"')
    expect(markup).toContain('aria-label="Open src/b/auth.py"')
  })
})
