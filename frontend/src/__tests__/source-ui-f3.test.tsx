import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { FileExplorer } from '../components/FileExplorer'

describe('FileExplorer lazy workspace UI', () => {
  it('renders empty prompt when no workspace is open', () => {
    const markup = renderToStaticMarkup(
      <FileExplorer
        workspacePath={null}
        selectedFile={null}
        onSelectFile={() => {}}
        loadDir={async () => []}
      />,
    )
    expect(markup).toContain('Open a local folder to browse files.')
  })

  it('renders empty folder state when workspace is set', () => {
    const markup = renderToStaticMarkup(
      <FileExplorer
        workspacePath="E:/repo"
        selectedFile="src/app.py"
        onSelectFile={() => {}}
        loadDir={async () => []}
      />,
    )
    expect(markup).toContain('Folder is empty.')
  })
})
