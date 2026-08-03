import React, { useState } from 'react';
import { X, ShieldAlert, CheckCircle2, FileCode, AlertTriangle, Lightbulb } from 'lucide-react';
import { CodeIssue } from '../types';

interface CodeEditorProps {
  openFiles: string[];
  activeFile: string | null;
  onSelectTab: (filePath: string) => void;
  onCloseTab: (filePath: string) => void;
  fileContent: string | null;
  issuesForFile: CodeIssue[];
  selectedIssueLine: number | null;
}

export const CodeEditor: React.FC<CodeEditorProps> = ({
  openFiles,
  activeFile,
  onSelectTab,
  onCloseTab,
  fileContent,
  issuesForFile,
  selectedIssueLine,
}) => {
  if (!activeFile || openFiles.length === 0) {
    return (
      <div
        style={{
          flex: 1,
          backgroundColor: 'var(--vscode-bg-editor)',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'var(--vscode-text-muted)',
          userSelect: 'none',
        }}
      >
        <FileCode size={48} color="#3c3c3c" style={{ marginBottom: '16px' }} />
        <div style={{ fontSize: '0.9rem', fontWeight: 500, color: 'var(--vscode-text-main)' }}>
          DevWatch Code Review Editor
        </div>
        <div style={{ fontSize: '0.78rem', marginTop: '6px' }}>
          Select a file from the left Explorer or click "Run Review" to scan codebase.
        </div>
      </div>
    );
  }

  const lines = (fileContent || '// Loading code content or file empty...').split('\n');

  // Map line numbers to issues
  const issuesByLine = issuesForFile.reduce((acc, issue) => {
    if (issue.line_number) {
      if (!acc[issue.line_number]) acc[issue.line_number] = [];
      acc[issue.line_number].push(issue);
    }
    return acc;
  }, {} as Record<number, CodeIssue[]>);

  return (
    <div
      style={{
        flex: 1,
        backgroundColor: 'var(--vscode-bg-editor)',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        overflow: 'hidden',
      }}
    >
      {/* Editor Tab Bar */}
      <div
        style={{
          backgroundColor: 'var(--vscode-bg-activity)',
          display: 'flex',
          overflowX: 'auto',
          borderBottom: '1px solid var(--vscode-border)',
          userSelect: 'none',
        }}
      >
        {openFiles.map((file) => {
          const isActive = file === activeFile;
          const fileIssues = issuesForFile.filter((i) => i.file_path === file);

          return (
            <div
              key={file}
              onClick={() => onSelectTab(file)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                padding: '8px 14px',
                fontSize: '0.78rem',
                fontFamily: 'JetBrains Mono, monospace',
                color: isActive ? 'var(--vscode-text-bright)' : 'var(--vscode-text-muted)',
                backgroundColor: isActive ? 'var(--vscode-bg-editor)' : 'var(--vscode-bg-tab-inactive)',
                borderRight: '1px solid var(--vscode-border)',
                borderTop: isActive ? '2px solid var(--vscode-blue)' : '2px solid transparent',
                cursor: 'pointer',
                minWidth: '120px',
                maxWidth: '200px',
              }}
            >
              <FileCode size={14} color={isActive ? '#61afef' : 'var(--vscode-text-muted)'} />
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
                {file.split('/').pop()}
              </span>

              {fileIssues.length > 0 && (
                <span
                  style={{
                    fontSize: '0.65rem',
                    background: 'var(--severity-critical-text)',
                    color: '#fff',
                    borderRadius: '50%',
                    width: '14px',
                    height: '14px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontWeight: 700,
                  }}
                >
                  {fileIssues.length}
                </span>
              )}

              <X
                size={13}
                onClick={(e) => {
                  e.stopPropagation();
                  onCloseTab(file);
                }}
                className="hover-opacity"
                style={{ opacity: 0.7 }}
              />
            </div>
          );
        })}
      </div>

      {/* Editor Content Area */}
      <div style={{ flex: 1, overflow: 'auto', position: 'relative', fontFamily: 'JetBrains Mono, monospace', fontSize: '0.85rem' }}>
        {lines.map((lineText, idx) => {
          const lineNum = idx + 1;
          const lineIssues = issuesByLine[lineNum] || [];
          const hasIssues = lineIssues.length > 0;
          const isTargetLine = selectedIssueLine === lineNum;

          // Determine highlight severity class
          let highlightClass = '';
          if (hasIssues) {
            const hasCritical = lineIssues.some((i) => i.severity === 'CRITICAL');
            const hasHigh = lineIssues.some((i) => i.severity === 'HIGH');
            highlightClass = hasCritical ? 'line-highlight-critical' : hasHigh ? 'line-highlight-high' : 'line-highlight-medium';
          }

          return (
            <React.Fragment key={lineNum}>
              <div
                id={`line-${lineNum}`}
                style={{
                  display: 'flex',
                  alignItems: 'stretch',
                  minHeight: '22px',
                  lineHeight: '22px',
                  backgroundColor: isTargetLine
                    ? 'rgba(0, 122, 204, 0.25)'
                    : hasIssues
                    ? 'rgba(255, 255, 255, 0.02)'
                    : 'transparent',
                  transition: 'background 0.15s ease',
                }}
                className={highlightClass}
              >
                {/* Line Number Column */}
                <div
                  style={{
                    width: '48px',
                    color: hasIssues ? 'var(--severity-critical-text)' : 'var(--vscode-text-muted)',
                    textAlign: 'right',
                    paddingRight: '12px',
                    userSelect: 'none',
                    backgroundColor: 'var(--vscode-bg-editor)',
                    borderRight: '1px solid var(--vscode-border)',
                    fontSize: '0.75rem',
                    flexShrink: 0,
                  }}
                >
                  {lineNum}
                </div>

                {/* Code Text */}
                <div style={{ paddingLeft: '12px', whiteSpace: 'pre', color: 'var(--vscode-text-main)', flex: 1 }}>
                  {lineText || ' '}
                </div>

                {/* Inline Diagnostic Warning Pill */}
                {hasIssues && (
                  <div style={{ paddingRight: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    {lineIssues.map((iss, iIdx) => (
                      <span
                        key={iIdx}
                        title={iss.description}
                        style={{
                          fontSize: '0.65rem',
                          background: iss.category === 'Security' ? 'var(--severity-critical-bg)' : 'var(--severity-medium-bg)',
                          color: iss.category === 'Security' ? 'var(--severity-critical-text)' : 'var(--severity-medium-text)',
                          border: `1px solid ${iss.category === 'Security' ? 'var(--severity-critical-border)' : 'var(--severity-medium-border)'}`,
                          padding: '1px 6px',
                          borderRadius: '3px',
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '4px',
                        }}
                      >
                        {iss.category === 'Security' ? <ShieldAlert size={10} /> : <CheckCircle2 size={10} />}
                        {iss.title}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* Expanded Diagnostic Inline Code Decorator Card */}
              {hasIssues && (
                <div
                  style={{
                    marginLeft: '48px',
                    backgroundColor: '#1b1d23',
                    borderLeft: '4px solid var(--severity-critical-text)',
                    borderBottom: '1px solid var(--vscode-border)',
                    padding: '8px 16px',
                    fontSize: '0.78rem',
                    fontFamily: 'Inter, sans-serif',
                  }}
                >
                  {lineIssues.map((iss, iIdx) => (
                    <div key={iIdx} style={{ marginBottom: iIdx < lineIssues.length - 1 ? '8px' : '0' }}>
                      <div style={{ fontWeight: 600, color: 'var(--vscode-text-bright)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span className={`severity-badge severity-${iss.severity.toLowerCase()}`}>
                          {iss.severity}
                        </span>
                        <span>{iss.title}</span>
                      </div>
                      <div style={{ color: 'var(--vscode-text-muted)', marginTop: '4px', fontSize: '0.75rem' }}>
                        {iss.description}
                      </div>
                      <div
                        style={{
                          marginTop: '6px',
                          color: 'var(--vscode-blue)',
                          fontSize: '0.72rem',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '4px',
                        }}
                      >
                        <Lightbulb size={12} />
                        <strong>Fix Suggestion:</strong> {iss.suggestion}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
};
