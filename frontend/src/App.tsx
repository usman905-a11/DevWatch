import { useState, useCallback, useRef } from 'react'
import FileExplorer, { FileNode } from './components/FileExplorer'
import CodeEditor from './components/CodeEditor'
import AgentPanel, { AgentId, Finding, Severity } from './components/AgentPanel'
import {
  fetchFileContent,
  runCodeReview,
  runUploadedFilesReview,
  applyQuickFix,
} from './services/api'
import { CodeIssue } from './types'

function extOf(name: string): string | undefined {
  const parts = name.split('.')
  return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : undefined
}

// Build FileNode tree from Web API FileList (webkitdirectory native folder upload)
async function buildTreeFromFileList(files: FileList): Promise<{ tree: FileNode[]; name: string }> {
  const fileArray = Array.from(files)
  if (fileArray.length === 0) return { tree: [], name: 'workspace' }

  // Get project name from webkitRelativePath or first file name (normalizing Windows backslashes)
  const samplePath = ((fileArray[0] as any).webkitRelativePath || fileArray[0].name).replace(/\\/g, '/')
  const pathParts = samplePath.split('/')
  const rootName = pathParts.length > 1 ? pathParts[0] : 'workspace'

  const rootNodes: FileNode[] = []
  const folderMap = new Map<string, FileNode>()

  // Helper to ensure a folder node exists in folderMap and parent folder
  const getOrCreateFolder = (folderPath: string, folderName: string): FileNode => {
    if (folderMap.has(folderPath)) {
      return folderMap.get(folderPath)!
    }
    const folderNode: FileNode = {
      id: folderPath,
      name: folderName,
      type: 'folder',
      children: [],
    }
    folderMap.set(folderPath, folderNode)

    const lastSlash = folderPath.lastIndexOf('/')
    if (lastSlash !== -1) {
      const parentPath = folderPath.slice(0, lastSlash)
      const parentName = parentPath.slice(parentPath.lastIndexOf('/') + 1)
      const parentNode = getOrCreateFolder(parentPath, parentName)
      if (!parentNode.children!.some((c) => c.id === folderPath)) {
        parentNode.children!.push(folderNode)
      }
    } else {
      if (!rootNodes.some((c) => c.id === folderPath)) {
        rootNodes.push(folderNode)
      }
    }

    return folderNode
  }

  // Sort files for consistent tree order
  fileArray.sort((a, b) => {
    const pa = ((a as any).webkitRelativePath || a.name).replace(/\\/g, '/')
    const pb = ((b as any).webkitRelativePath || b.name).replace(/\\/g, '/')
    return pa.localeCompare(pb)
  })

  for (const file of fileArray) {
    const rawRel = ((file as any).webkitRelativePath || file.name).replace(/\\/g, '/')
    const parts = rawRel.split('/')
    // If path has root folder prefix (e.g. "myfolder/src/index.js"), strip "myfolder"
    const relParts = parts.length > 1 ? parts.slice(1) : parts

    const fileName = relParts[relParts.length - 1]
    const ext = extOf(fileName)
    const fileId = relParts.join('/')

    let content: string | undefined
    if (file.size < 2_000_000) {
      try {
        content = await file.text()
      } catch {
        content = '// Unreadable or binary content'
      }
    } else {
      content = '// Large file (>2MB) omitted'
    }

    const fileNode: FileNode = {
      id: fileId,
      name: fileName,
      type: 'file',
      ext,
      content,
    }

    if (relParts.length === 1) {
      rootNodes.push(fileNode)
    } else {
      const folderParts = relParts.slice(0, -1)
      const folderPath = folderParts.join('/')
      const folderName = folderParts[folderParts.length - 1]
      const parentFolder = getOrCreateFolder(folderPath, folderName)
      parentFolder.children!.push(fileNode)
    }
  }

  // Sort top-level entries: folders first, then files alphabetically
  rootNodes.sort((a, b) => {
    const af = a.type === 'folder' ? 0 : 1
    const bf = b.type === 'folder' ? 0 : 1
    return af - bf || a.name.localeCompare(b.name)
  })

  return { tree: rootNodes, name: rootName }
}

// Map DevWatch backend CodeIssue array to ReviewKit Finding array
function mapIssuesToFindings(issues: CodeIssue[]): Finding[] {
  return issues.map((iss, index) => {
    let agent: AgentId = 'quality'
    if (iss.category.toLowerCase().includes('security') || iss.severity === 'CRITICAL' || iss.severity === 'HIGH') {
      agent = 'security'
    } else if (iss.category.toLowerCase().includes('quality') || iss.category.toLowerCase().includes('refactor')) {
      agent = 'quality'
    } else {
      agent = 'bugs'
    }

    let sev: Severity = 'low'
    if (iss.severity === 'CRITICAL') sev = 'critical'
    else if (iss.severity === 'HIGH') sev = 'high'
    else if (iss.severity === 'MEDIUM') sev = 'medium'

    const fileName = iss.file_path.split('/').pop() || iss.file_path

    return {
      id: `finding-${index}-${iss.file_path}-${iss.line_number || 1}`,
      agent,
      severity: sev,
      title: iss.title,
      description: iss.description,
      fileId: iss.file_path,
      fileName,
      line: iss.line_number || 1,
      suggestion: iss.suggestion,
    }
  })
}

export function App() {
  const [targetPath, setTargetPath] = useState('')
  const [projectName, setProjectName] = useState('workspace')
  const [tree, setTree] = useState<FileNode[]>([])
  const [selectedFile, setSelectedFile] = useState<FileNode | null>(null)
  const [openFiles, setOpenFiles] = useState<FileNode[]>([])
  const [activeAgent, setActiveAgent] = useState<AgentId>('security')
  const [analysisRunning, setAnalysisRunning] = useState(false)
  const [analysisComplete, setAnalysisComplete] = useState(false)
  const [highlightLine, setHighlightLine] = useState<number | null>(null)
  const [findings, setFindings] = useState<Finding[]>([])
  const [folderLoading, setFolderLoading] = useState(false)
  
  const folderInputRef = useRef<HTMLInputElement>(null)

  // Select file and fetch content if needed
  const handleSelectFile = useCallback(
    async (file: FileNode) => {
      let content = file.content
      if (content === undefined && file.type === 'file' && targetPath) {
        try {
          const res = await fetchFileContent(file.id, targetPath)
          content = res.content
        } catch (e) {
          content = '// Empty file or read error'
        }
      }

      const fullFile: FileNode = { ...file, content }
      setSelectedFile(fullFile)
      setHighlightLine(null)

      setOpenFiles((prev) => {
        const existing = prev.find((f) => f.id === file.id)
        if (existing) {
          return prev.map((f) => (f.id === file.id ? fullFile : f))
        }
        return [...prev, fullFile]
      })
    },
    [targetPath]
  )

  const handleCloseFile = useCallback(
    (fileId: string) => {
      setOpenFiles((prev) => {
        const next = prev.filter((f) => f.id !== fileId)
        if (selectedFile?.id === fileId) {
          setSelectedFile(next.length > 0 ? next[next.length - 1] : null)
        }
        return next
      })
      setHighlightLine(null)
    },
    [selectedFile]
  )

  const handleRunAnalysis = useCallback(async () => {
    if (analysisRunning) return
    setAnalysisComplete(false)
    setAnalysisRunning(true)

    try {
      const collectFiles = (nodes: FileNode[]): Array<{ file_path: string; content: string }> => {
        let acc: Array<{ file_path: string; content: string }> = []
        for (const n of nodes) {
          if (n.type === 'file' && n.content !== undefined && n.content.trim() !== '') {
            acc.push({ file_path: n.id, content: n.content })
          } else if (n.type === 'folder' && n.children) {
            acc.push(...collectFiles(n.children))
          }
        }
        return acc
      }

      const uploadedFiles = collectFiles(tree)
      let res: any

      if (uploadedFiles.length > 0) {
        res = await runUploadedFilesReview(uploadedFiles)
      } else {
        res = await runCodeReview(targetPath || '.')
      }

      const mapped = mapIssuesToFindings(res.report?.issues || [])
      setFindings(mapped)
      setAnalysisComplete(true)
    } catch (err: any) {
      console.error('Code review failed:', err)
      if (err.message && (err.message.includes('429') || err.message.includes('Rate limit') || err.message.includes('free-models-per-day'))) {
        alert(
          '⚠️ OpenRouter Free Tier Limit Reached (50/50 requests used today)\n\n' +
          'Your OpenRouter account has reached its daily limit of 50 free AI model requests.\n\n' +
          'How to unlock unlimited audits:\n' +
          '1. Add $5-$10 credits on https://openrouter.ai/keys (this instantly upgrades your daily limit from 50 to 1,000 requests/day).\n' +
          '2. Or wait for the daily OpenRouter quota reset.'
        )
      } else {
        alert(`Review failed: ${err.message}`)
      }
    } finally {
      setAnalysisRunning(false)
    }
  }, [analysisRunning, tree, targetPath])

  const handleFindingClick = useCallback(
    async (finding: Finding) => {
      try {
        const res = await fetchFileContent(finding.fileId, targetPath || '.')
        const targetNode: FileNode = {
          id: finding.fileId,
          name: finding.fileName,
          type: 'file',
          ext: extOf(finding.fileName),
          content: res.content,
        }
        handleSelectFile(targetNode)
        setTimeout(() => setHighlightLine(finding.line), 50)
      } catch (err) {
        console.error('Failed to open file for finding:', err)
      }
    },
    [targetPath, handleSelectFile]
  )

  const handleApplyFix = useCallback(
    async (finding: Finding) => {
      if (!finding.suggestion) return
      try {
        await applyQuickFix(finding.fileId, finding.line, '', finding.suggestion, targetPath || '.')
        alert(`Successfully applied fix to ${finding.fileName}:${finding.line}`)
        const res = await fetchFileContent(finding.fileId, targetPath || '.')
        setSelectedFile((prev) => (prev ? { ...prev, content: res.content } : null))
        setOpenFiles((prev) =>
          prev.map((f) => (f.id === finding.fileId ? { ...f, content: res.content } : f))
        )
      } catch (err: any) {
        alert(`Quick fix failed: ${err.message}`)
      }
    },
    [targetPath]
  )

  // Native OS file/folder picker trigger
  const handleOpenFolder = useCallback(() => {
    folderInputRef.current?.click()
  }, [])

  // Handle native folder selection from user's device
  const handleFolderInputChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files
      if (!files || files.length === 0) return
      setFolderLoading(true)
      try {
        const { tree: newTree, name } = await buildTreeFromFileList(files)
        setTree(newTree)
        setProjectName(name)
        setTargetPath(name)
        setSelectedFile(null)
        setOpenFiles([])
        setHighlightLine(null)
        setAnalysisComplete(false)
        setAnalysisRunning(false)
        
        // Find first file in tree to open in editor
        const findFirstFile = (nodes: FileNode[]): FileNode | null => {
          for (const n of nodes) {
            if (n.type === 'file') return n
            if (n.children) {
              const found = findFirstFile(n.children)
              if (found) return found
            }
          }
          return null
        }

        const firstFile = findFirstFile(newTree)
        if (firstFile) {
          setSelectedFile(firstFile)
          setOpenFiles([firstFile])
        }
      } catch (err) {
        console.error('Failed to parse uploaded folder:', err)
      } finally {
        setFolderLoading(false)
        if (folderInputRef.current) folderInputRef.current.value = ''
      }
    },
    []
  )

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
          onApplyFix={handleApplyFix}
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
