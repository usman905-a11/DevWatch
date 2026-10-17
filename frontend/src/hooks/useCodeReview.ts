import { useState, useCallback, useEffect, useRef, MutableRefObject } from 'react'
import {
  fetchFileContent,
  runUploadedFilesReview,
  subscribeToReviewStream,
} from '../services/api'
import { FileNode } from '../components/FileExplorer'
import { AgentId, Finding, Severity } from '../components/AgentPanel'
import { AgentStepUpdate, CodeIssue, ReviewReport } from '../types'

// Helper: Extract file extension from filename
function extOf(name: string): string | undefined {
  const parts = name.split('.')
  return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : undefined
}

function findFile(nodes: FileNode[], id: string): FileNode | undefined {
  for (const node of nodes) {
    if (node.type === 'file' && node.id === id) return node
    const nested = node.children && findFile(node.children, id)
    if (nested) return nested
  }
  return undefined
}

/**
 * Build FileNode tree from Web API FileList (webkitdirectory native folder upload).
 * Handles Windows backslashes, creates folder hierarchy, and reads file content.
 */
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

/**
 * Map DevWatch backend CodeIssue array to frontend Finding array.
 * Handles categorization, severity mapping, and finding ID generation.
 */
export function mapIssuesToFindings(issues: CodeIssue[]): Finding[] {
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
      id: iss.finding_id || `finding-${index}-${iss.file_path}-${iss.line_number || 1}`,
      agent,
      severity: sev,
      title: iss.title,
      description: iss.description,
      fileId: iss.file_path,
      fileName,
      line: iss.line_number || 1,
      suggestion: iss.suggestion,
      replacement_code: iss.replacement_code,
      finding_id: iss.finding_id,
      verification_status: iss.verification_status,
      cwe_id: iss.cwe_id,
      confidence_score: iss.confidence_score,
    }
  })
}

export function mapReviewReport(report: ReviewReport) {
  return {
    findings: mapIssuesToFindings(report.issues || []),
    manualReviewCandidates: mapIssuesToFindings(report.manual_review_candidates || []),
    partial: report.metrics?.partial === true,
  }
}

export function appendProgressStep(
  steps: AgentStepUpdate[],
  step: AgentStepUpdate
): AgentStepUpdate[] {
  return [...steps, step].slice(-20)
}

/**
 * useCodeReview — custom hook encapsulating code review state and business logic.
 *
 * Manages:
 * - File tree state (project files and folder structure)
 * - Analysis state (running, complete, findings)
 * - UI state (selected file, open files, highlight line, active agent)
 *
 * Exposes methods:
 * - handleSelectFile, handleCloseFile
 * - handleRunAnalysis (with WebSocket subscription)
 * - handleFindingClick (navigate to finding location)
 * - handleOpenFolder, handleFolderInputChange (load folders from user's device)
 *
 * Design principle: All review-related state and logic is in one place.
 * Components only render; they call hook methods when user interacts.
 */
export function useCodeReview() {
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
  const [manualReviewCandidates, setManualReviewCandidates] = useState<Finding[]>([])
  const [progressSteps, setProgressSteps] = useState<AgentStepUpdate[]>([])
  const [reviewError, setReviewError] = useState<string | null>(null)
  const [partial, setPartial] = useState(false)
  const [folderLoading, setFolderLoading] = useState(false)

  const folderInputRef = useRef<HTMLInputElement>(null)
  const streamCleanupRef = useRef<(() => void) | null>(null)

  useEffect(() => () => streamCleanupRef.current?.(), [])

  const applyReport = useCallback((report: ReviewReport) => {
    const view = mapReviewReport(report)
    setFindings(view.findings)
    setManualReviewCandidates(view.manualReviewCandidates)
    setPartial(view.partial)
    setAnalysisComplete(true)
    setAnalysisRunning(false)
  }, [])

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
    streamCleanupRef.current?.()
    streamCleanupRef.current = null
    setAnalysisComplete(false)
    setAnalysisRunning(true)
    setFindings([])
    setManualReviewCandidates([])
    setProgressSteps([])
    setReviewError(null)
    setPartial(false)

    const failReview = (error: Error) => {
      setReviewError(error.message)
      setAnalysisRunning(false)
      setAnalysisComplete(false)
      streamCleanupRef.current?.()
      streamCleanupRef.current = null
    }

    try {
      const collectFiles = (nodes: FileNode[]): Array<{ file_path: string; content: string }> => {
        const collected: Array<{ file_path: string; content: string }> = []
        for (const node of nodes) {
          if (node.type === 'file' && node.content?.trim()) {
            collected.push({ file_path: node.id, content: node.content })
          } else if (node.type === 'folder' && node.children) {
            collected.push(...collectFiles(node.children))
          }
        }
        return collected
      }

      const uploadedFiles = collectFiles(tree)
      if (uploadedFiles.length > 0) {
        setProgressSteps([{
          agent_name: 'Review',
          status: 'RUNNING',
          message: 'Reviewing uploaded files',
        }])
        const response = await runUploadedFilesReview(uploadedFiles)
        applyReport(response.report)
      } else {
        streamCleanupRef.current = subscribeToReviewStream(
          targetPath || '.',
          (step) => setProgressSteps((previous) => appendProgressStep(previous, step)),
          (data) => {
            applyReport(data.report)
            streamCleanupRef.current?.()
            streamCleanupRef.current = null
          },
          failReview,
        )
      }
    } catch (error) {
      failReview(error instanceof Error ? error : new Error('Review failed'))
    }
  }, [analysisRunning, tree, targetPath, applyReport])

  const handleFindingClick = useCallback(
    async (finding: Finding) => {
      try {
        const localFile = findFile(tree, finding.fileId)
        const content = localFile?.content ?? (
          await fetchFileContent(finding.fileId, targetPath || '.')
        ).content
        const targetNode: FileNode = {
          id: finding.fileId,
          name: finding.fileName,
          type: 'file',
          ext: extOf(finding.fileName),
          content,
        }
        await handleSelectFile(targetNode)
        setTimeout(() => setHighlightLine(finding.line), 50)
      } catch (err) {
        console.error('Failed to open file for finding:', err)
      }
    },
    [targetPath, tree, handleSelectFile]
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
      streamCleanupRef.current?.()
      streamCleanupRef.current = null
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
        setFindings([])
        setManualReviewCandidates([])
        setProgressSteps([])
        setReviewError(null)
        setPartial(false)

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

  return {
    // State
    targetPath,
    projectName,
    tree,
    selectedFile,
    openFiles,
    analysisRunning,
    analysisComplete,
    findings,
    manualReviewCandidates,
    progressSteps,
    reviewError,
    partial,
    folderLoading,
    highlightLine,
    activeAgent,

    // Methods
    handleSelectFile,
    handleCloseFile,
    handleRunAnalysis,
    handleFindingClick,
    handleOpenFolder,
    handleFolderInputChange,
    setHighlightLine,
    folderInputRef,
  }
}
