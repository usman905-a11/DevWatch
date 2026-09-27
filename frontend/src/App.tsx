import FileExplorer from './components/FileExplorer'
import CodeEditor from './components/CodeEditor'
import AgentPanel from './components/AgentPanel'
import { useCodeReview, mapIssuesToFindings } from './hooks/useCodeReview'

export { mapIssuesToFindings }

export function App() {
  const {
    projectName,
    tree,
    selectedFile,
    openFiles,
    analysisRunning,
    analysisComplete,
    findings,
    folderLoading,
    highlightLine,
    handleSelectFile,
    handleCloseFile,
    handleRunAnalysis,
    handleFindingClick,
    handleOpenFolder,
    handleFolderInputChange,
    setHighlightLine,
    folderInputRef,
  } = useCodeReview()

  return (
    <div className="workspace">
      {/* Apple Workspace Header Titlebar */}
      <header className="titlebar">
        <div className="traffic">
          <i />
          <i />
          <i />
        </div>
        <div className="brand">
          DevWatch<span>Kit</span>
          <em>.app</em>
        </div>
        <div className="crumb">
          <strong>{projectName}</strong>
          {selectedFile && <> &nbsp;/&nbsp; {selectedFile.name}</>}
        </div>
        <button className="header-button" onClick={handleOpenFolder} disabled={folderLoading}>
          {folderLoading ? 'Loading folder…' : 'Open folder'}
        </button>
        <button
          className="review-button"
          onClick={handleRunAnalysis}
          disabled={analysisRunning}
        >
          {analysisRunning ? 'Reviewing…' : 'Run review'}
        </button>
      </header>

      {/* Workspace Tri-Pane Body */}
      <div className="body">
        <FileExplorer
          selectedFileId={selectedFile?.id ?? null}
          onSelectFile={handleSelectFile}
          tree={tree}
          projectName={projectName}
          onOpenFolder={handleOpenFolder}
        />
        <CodeEditor
          file={selectedFile}
          openFiles={openFiles}
          onSelectFile={handleSelectFile}
          onCloseFile={handleCloseFile}
          highlightLine={highlightLine}
        />
        <AgentPanel
          analysisRunning={analysisRunning}
          analysisComplete={analysisComplete}
          onFindingClick={handleFindingClick}
          findings={findings}
        />
      </div>

      {/* Workspace Footer Statusbar */}
      <footer className="statusbar">
        <span className="status-branch">
          <i /> main
        </span>
        <span>⌘K&nbsp; Command palette</span>
        <span className="status-spacer" />
        <span>
          {analysisComplete
            ? `${findings.length} review signals`
            : 'Review workspace ready'}
        </span>
        <span>Ln {highlightLine ?? 1}, Col 1</span>
        <span>Spaces: 2</span>
      </footer>

      {/* Native OS Folder Picker Input */}
      <input
        ref={folderInputRef}
        type="file"
        multiple
        style={{ display: 'none' }}
        onChange={handleFolderInputChange}
        {...({ webkitdirectory: '', directory: '' } as React.InputHTMLAttributes<HTMLInputElement>)}
      />
    </div>
  )
}

export default App
