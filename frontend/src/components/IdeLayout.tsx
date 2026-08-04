import React, { useState, useEffect } from 'react';
import { ActivityBar, ActivityView } from './ActivityBar';
import { FileExplorer } from './FileExplorer';
import { CodeEditor } from './CodeEditor';
import { AgentChatCenter, AgentState } from './AgentChatCenter';
import { BottomPanel } from './BottomPanel';
import { ReviewReport, CodeIssue } from '../types';
import {
  fetchFileTree,
  fetchFileContent,
  saveFileContent,
  auditSingleFile,
  subscribeToReviewStream,
} from '../services/api';
import { ShieldCheck, Play, Sparkles, Save, FileCheck } from 'lucide-react';

export const IdeLayout: React.FC = () => {
  const [activeView, setActiveView] = useState<ActivityView>('explorer');
  const [targetPath, setTargetPath] = useState<string>('.');
  const [loading, setLoading] = useState<boolean>(false);
  const [report, setReport] = useState<ReviewReport | null>(null);

  // File explorer & editor state
  const [filesToReview, setFilesToReview] = useState<string[]>([]);
  const [openFiles, setOpenFiles] = useState<string[]>([]);
  const [activeFile, setActiveFile] = useState<string | null>(null);
  const [selectedIssueLine, setSelectedIssueLine] = useState<number | null>(null);
  const [isBottomPanelOpen, setIsBottomPanelOpen] = useState<boolean>(true);

  // Dynamic file content cache
  const [fileContentsMap, setFileContentsMap] = useState<Record<string, string>>({});

  // Agents status
  const [agents, setAgents] = useState<AgentState[]>([
    { name: 'Planner Agent', role: 'Senior Code Review Architect', status: 'IDLE' },
    { name: 'Security Auditor', role: 'Cybersecurity Vulnerability Auditor', status: 'IDLE' },
    { name: 'Quality Auditor', role: 'Principal Code Quality Analyst', status: 'IDLE' },
    { name: 'Synthesizer Agent', role: 'Technical Review Editor', status: 'IDLE' },
  ]);

  // Load filesystem tree when targetPath changes
  useEffect(() => {
    let isMounted = true;
    fetchFileTree(targetPath)
      .then((data) => {
        if (!isMounted) return;
        setFilesToReview(data.files || []);
        if (data.files && data.files.length > 0 && openFiles.length === 0) {
          const defaultFile = data.files[0];
          setOpenFiles([defaultFile]);
          setActiveFile(defaultFile);
          loadContent(defaultFile);
        }
      })
      .catch((err) => {
        console.warn('Could not fetch file tree:', err);
      });
    return () => {
      isMounted = false;
    };
  }, [targetPath]);

  const loadContent = async (filePath: string) => {
    if (fileContentsMap[filePath]) return fileContentsMap[filePath];
    try {
      const data = await fetchFileContent(filePath, targetPath);
      setFileContentsMap((prev) => ({ ...prev, [filePath]: data.content }));
      return data.content;
    } catch (err) {
      console.error(`Failed to load ${filePath}:`, err);
      return '';
    }
  };

  const handleRunReview = () => {
    setLoading(true);
    setReport(null);

    setAgents((prev) =>
      prev.map((a) => ({ ...a, status: 'RUNNING', lastMessage: 'Review pipeline initiated...' }))
    );

    const unsubscribe = subscribeToReviewStream(
      targetPath,
      (stepUpdate) => {
        setAgents((prev) =>
          prev.map((a) =>
            a.name === stepUpdate.agent_name
              ? { ...a, status: stepUpdate.status as any, lastMessage: stepUpdate.message }
              : a
          )
        );
      },
      (completeData) => {
        if (completeData.report) {
          setReport(completeData.report);
          if (completeData.report.files_to_review) {
            setFilesToReview(completeData.report.files_to_review);
          }
        }
        setAgents((prev) =>
          prev.map((a) => ({ ...a, status: 'COMPLETED', lastMessage: 'Analysis complete.' }))
        );
        setLoading(false);
      },
      (err) => {
        console.error('Review WebSocket error:', err);
        setAgents((prev) =>
          prev.map((a) => ({ ...a, status: 'FAILED', lastMessage: err.message || 'Stream error' }))
        );
        setLoading(false);
      }
    );
  };

  const handleAuditActiveFile = async () => {
    if (!activeFile) return;
    const content = fileContentsMap[activeFile] || (await loadContent(activeFile));
    setLoading(true);
    try {
      const res = await auditSingleFile(activeFile, content);
      setReport(res.report);
    } catch (err: any) {
      alert(`Single file audit failed: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleSaveActiveFile = async () => {
    if (!activeFile) return;
    const content = fileContentsMap[activeFile];
    if (content === undefined) return;
    try {
      await saveFileContent(activeFile, content, targetPath);
      alert(`Saved ${activeFile}`);
    } catch (err: any) {
      alert(`Save failed: ${err.message}`);
    }
  };

  const handleSelectFile = async (filePath: string) => {
    if (!openFiles.includes(filePath)) {
      setOpenFiles((prev) => [...prev, filePath]);
    }
    setActiveFile(filePath);
    setSelectedIssueLine(null);
    await loadContent(filePath);
  };

  const handleCloseTab = (filePath: string) => {
    const nextOpen = openFiles.filter((f) => f !== filePath);
    setOpenFiles(nextOpen);
    if (activeFile === filePath) {
      setActiveFile(nextOpen.length > 0 ? nextOpen[nextOpen.length - 1] : null);
    }
  };

  const handleSelectIssue = async (issue: CodeIssue) => {
    await handleSelectFile(issue.file_path);
    setSelectedIssueLine(issue.line_number || null);

    if (issue.line_number) {
      setTimeout(() => {
        const el = document.getElementById(`line-${issue.line_number}`);
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }, 100);
    }
  };

  const issuesForActiveFile = (report?.issues || []).filter((i) => i.file_path === activeFile);

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

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {activeFile && (
            <>
              <button
                onClick={handleSaveActiveFile}
                className="btn-secondary"
                style={{ padding: '3px 8px', fontSize: '0.72rem', display: 'flex', alignItems: 'center', gap: '4px' }}
                title="Save active file"
              >
                <Save size={11} /> Save
              </button>

              <button
                onClick={handleAuditActiveFile}
                disabled={loading}
                className="btn-secondary"
                style={{ padding: '3px 8px', fontSize: '0.72rem', display: 'flex', alignItems: 'center', gap: '4px' }}
                title="Audit active file buffer"
              >
                <FileCheck size={11} /> Audit Active File
              </button>
            </>
          )}

          <button
            onClick={handleRunReview}
            disabled={loading}
            className="btn-primary"
            style={{ padding: '3px 10px', fontSize: '0.75rem' }}
          >
            {loading ? <Sparkles size={12} /> : <Play size={12} fill="white" />}
            {loading ? 'Auditing...' : 'Run Full Review'}
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
            fileContent={activeFile ? fileContentsMap[activeFile] || null : null}
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
          <span>DevWatch Multi-Agent Engine</span>
          <span>{report ? `${report.total_issues} Issues Found` : 'Ready'}</span>
        </div>
        <div>UTF-8 | Python 3.11 | DevWatch OS</div>
      </div>
    </div>
  );
};

