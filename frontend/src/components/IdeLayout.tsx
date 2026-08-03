import React, { useState, useEffect } from 'react';
import { ActivityBar, ActivityView } from './ActivityBar';
import { FileExplorer } from './FileExplorer';
import { CodeEditor } from './CodeEditor';
import { AgentChatCenter, AgentState } from './AgentChatCenter';
import { BottomPanel } from './BottomPanel';
import { ReviewReport, CodeIssue } from '../types';
import { runCodeReview } from '../services/api';
import { ShieldCheck, Play, Sparkles } from 'lucide-react';

export const IdeLayout: React.FC = () => {
  const [activeView, setActiveView] = useState<ActivityView>('explorer');
  const [targetPath, setTargetPath] = useState<string>('.');
  const [loading, setLoading] = useState<boolean>(false);
  const [report, setReport] = useState<ReviewReport | null>(null);

  // File explorer & editor state
  const [filesToReview, setFilesToReview] = useState<string[]>([
    'devwatch/agents/planner.py',
    'devwatch/agents/security.py',
    'devwatch/agents/quality.py',
    'devwatch/agents/synthesizer.py',
  ]);
  const [openFiles, setOpenFiles] = useState<string[]>(['devwatch/agents/security.py']);
  const [activeFile, setActiveFile] = useState<string | null>('devwatch/agents/security.py');
  const [selectedIssueLine, setSelectedIssueLine] = useState<number | null>(null);
  const [isBottomPanelOpen, setIsBottomPanelOpen] = useState<boolean>(true);

  // Agents status
  const [agents, setAgents] = useState<AgentState[]>([
    { name: 'Planner Agent', role: 'Senior Code Review Architect', status: 'IDLE' },
    { name: 'Security Auditor', role: 'Cybersecurity Vulnerability Auditor', status: 'IDLE' },
    { name: 'Quality Auditor', role: 'Principal Code Quality Analyst', status: 'IDLE' },
    { name: 'Synthesizer Agent', role: 'Technical Review Editor', status: 'IDLE' },
  ]);

  // Mock file contents dictionary for fallback/offline display
  const fileContentsMap: Record<string, string> = {
    'devwatch/agents/planner.py': `import json\nfrom devwatch.scanner import CodebaseScanner\nfrom devwatch.models import ReviewScope\n\nclass PlannerAgent:\n    def __init__(self):\n        self.role = "Senior Code Review Architect"\n\n    def plan_review(self, target_path: str) -> ReviewScope:\n        scanner = CodebaseScanner(target_path)\n        return ReviewScope(target_path=target_path, files_to_review=scanner.get_files())`,
    'devwatch/agents/security.py': `import json\nfrom devwatch.tools import SecurityPatternTool\nfrom devwatch.agents import llm\n\nclass SecurityAuditorAgent:\n    def __init__(self):\n        self.tool = SecurityPatternTool()\n\n    def analyze(self, file_path: str, code_content: str):\n        # Scans for OWASP Top 10 vulnerabilities & secret leaks\n        issues = self.tool._run(file_path=file_path, code_content=code_content)\n        return issues`,
    'devwatch/agents/quality.py': `from devwatch.tools import LogicAnalyzerTool\n\nclass QualityAuditorAgent:\n    def __init__(self):\n        self.tool = LogicAnalyzerTool()\n\n    def analyze(self, file_path: str, code_content: str):\n        return self.tool._run(file_path=file_path, code_content=code_content)`,
    'devwatch/agents/synthesizer.py': `from devwatch.models import ReviewReport\n\nclass ReportSynthesizerAgent:\n    def render_markdown(self, report: ReviewReport) -> str:\n        return f"# DevWatch Report\\nTotal issues: {report.total_issues}"`,
  };

  const handleRunReview = async () => {
    setLoading(true);
    setReport(null);

    setAgents((prev) =>
      prev.map((a) => ({ ...a, status: 'RUNNING', lastMessage: 'Auditing files...' }))
    );

    try {
      const response = await runCodeReview(targetPath);
      setReport(response.report);

      if (response.report.files_to_review && response.report.files_to_review.length > 0) {
        setFilesToReview(response.report.files_to_review);
      }

      setAgents((prev) =>
        prev.map((a) => ({ ...a, status: 'COMPLETED', lastMessage: 'Analysis complete.' }))
      );
    } catch (err: any) {
      alert(`Review Failed: ${err.message}`);
      setAgents((prev) =>
        prev.map((a) => ({ ...a, status: 'FAILED', lastMessage: err.message }))
      );
    } finally {
      setLoading(false);
    }
  };

  const handleSelectFile = (filePath: string) => {
    if (!openFiles.includes(filePath)) {
      setOpenFiles((prev) => [...prev, filePath]);
    }
    setActiveFile(filePath);
    setSelectedIssueLine(null);
  };

  const handleCloseTab = (filePath: string) => {
    const nextOpen = openFiles.filter((f) => f !== filePath);
    setOpenFiles(nextOpen);
    if (activeFile === filePath) {
      setActiveFile(nextOpen.length > 0 ? nextOpen[nextOpen.length - 1] : null);
    }
  };

  const handleSelectIssue = (issue: CodeIssue) => {
    handleSelectFile(issue.file_path);
    setSelectedIssueLine(issue.line_number || null);

    if (issue.line_number) {
      setTimeout(() => {
        const el = document.getElementById(`line-${issue.line_number}`);
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }, 100);
    }
  };

  const issuesForActiveFile = (report?.issues || []).filter(
    (i) => i.file_path === activeFile
  );

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        width: '100vw',
        overflow: 'hidden',
        backgroundColor: 'var(--vscode-bg-activity)',
      }}
    >
      {/* Top VS Code Chrome Titlebar */}
      <div
        style={{
          height: '34px',
          backgroundColor: 'var(--vscode-bg-activity)',
          borderBottom: '1px solid var(--vscode-border)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 14px',
          fontSize: '0.75rem',
          color: 'var(--vscode-text-muted)',
          userSelect: 'none',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <div style={{ display: 'flex', gap: '6px' }}>
            <div style={{ width: '10px', height: '10px', borderRadius: '50%', background: '#ff5f56' }} />
            <div style={{ width: '10px', height: '10px', borderRadius: '50%', background: '#ffbd2e' }} />
            <div style={{ width: '10px', height: '10px', borderRadius: '50%', background: '#27c93f' }} />
          </div>
          <span style={{ fontWeight: 600, color: 'var(--vscode-text-main)', marginLeft: '6px' }}>
            DevWatch Studio — {targetPath === '.' ? 'workspace' : targetPath}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <button
            onClick={handleRunReview}
            disabled={loading}
            className="btn-primary"
            style={{ padding: '3px 10px', fontSize: '0.75rem' }}
          >
            {loading ? <Sparkles size={12} /> : <Play size={12} fill="white" />}
            {loading ? 'Auditing...' : 'Run Review'}
          </button>
        </div>
      </div>

      {/* Main IDE Tri-Pane Workspace */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Far-Left Activity Bar */}
        <ActivityBar
          activeView={activeView}
          setActiveView={setActiveView}
          onRunReview={handleRunReview}
          loading={loading}
          totalIssuesCount={report?.total_issues || 0}
        />

        {/* Left Collapsible File Explorer */}
        {activeView === 'explorer' && (
          <FileExplorer
            targetPath={targetPath}
            setTargetPath={setTargetPath}
            filesToReview={filesToReview}
            issues={report?.issues || []}
            selectedFile={activeFile}
            onSelectFile={handleSelectFile}
          />
        )}

        {/* Center Code Editor Area */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <CodeEditor
            openFiles={openFiles}
            activeFile={activeFile}
            onSelectTab={handleSelectFile}
            onCloseTab={handleCloseTab}
            fileContent={activeFile ? fileContentsMap[activeFile] || `// Code file: ${activeFile}\n// Content loaded directly from repository scanner.` : null}
            issuesForFile={issuesForActiveFile}
            selectedIssueLine={selectedIssueLine}
          />

          {/* Bottom Diagnostics / Problems Drawer */}
          <BottomPanel
            report={report}
            onSelectIssue={handleSelectIssue}
            isOpen={isBottomPanelOpen}
            onToggleOpen={() => setIsBottomPanelOpen(!isBottomPanelOpen)}
          />
        </div>

        {/* Right Side Agent Crew & Chat Center */}
        <AgentChatCenter
          agents={agents}
          report={report}
          loading={loading}
          onRunReview={handleRunReview}
        />
      </div>

      {/* VS Code Status Bar */}
      <div
        style={{
          height: '22px',
          backgroundColor: 'var(--vscode-blue)',
          color: '#ffffff',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 12px',
          fontSize: '0.7rem',
          userSelect: 'none',
        }}
      >
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <span>DevWatch CrewAI Engine</span>
          <span>{report ? `${report.total_issues} Issues Found` : 'Ready'}</span>
        </div>
        <div>UTF-8 | Python 3.11 | DevWatch OS</div>
      </div>
    </div>
  );
};
