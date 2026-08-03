import React, { useState } from 'react';
import { Folder, FileCode, AlertTriangle, ChevronDown, ChevronRight, Search, Shield, Filter } from 'lucide-react';
import { CodeIssue } from '../types';

interface FileExplorerProps {
  targetPath: string;
  setTargetPath: (path: string) => void;
  filesToReview: string[];
  issues: CodeIssue[];
  selectedFile: string | null;
  onSelectFile: (filePath: string) => void;
}

export const FileExplorer: React.FC<FileExplorerProps> = ({
  targetPath,
  setTargetPath,
  filesToReview,
  issues,
  selectedFile,
  onSelectFile,
}) => {
  const [filterText, setFilterText] = useState<string>('');
  const [isExplorerOpen, setIsExplorerOpen] = useState<boolean>(true);

  // Group issues by file path
  const issueCountsByFile = issues.reduce((acc, issue) => {
    acc[issue.file_path] = (acc[issue.file_path] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);

  const filteredFiles = filesToReview.filter((f) =>
    f.toLowerCase().includes(filterText.toLowerCase())
  );

  return (
    <div
      style={{
        width: '260px',
        backgroundColor: 'var(--vscode-bg-sidebar)',
        borderRight: '1px solid var(--vscode-border)',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        userSelect: 'none',
        flexShrink: 0,
      }}
    >
      {/* Sidebar Section Title */}
      <div
        style={{
          padding: '10px 14px',
          fontSize: '0.7rem',
          fontWeight: 700,
          color: 'var(--vscode-text-muted)',
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
          borderBottom: '1px solid var(--vscode-border)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <span>EXPLORER</span>
        <span style={{ fontSize: '0.65rem', background: '#333', padding: '2px 6px', borderRadius: '4px' }}>
          {filesToReview.length} FILES
        </span>
      </div>

      {/* Target Path Input */}
      <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--vscode-border)' }}>
        <div
          style={{
            position: 'relative',
            display: 'flex',
            alignItems: 'center',
          }}
        >
          <Search size={13} color="var(--vscode-text-muted)" style={{ position: 'absolute', left: '8px' }} />
          <input
            type="text"
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
            placeholder="Filter files..."
            style={{
              width: '100%',
              background: 'var(--vscode-bg-activity)',
              border: '1px solid var(--vscode-border-light)',
              padding: '5px 8px 5px 26px',
              borderRadius: '4px',
              color: 'var(--vscode-text-main)',
              fontSize: '0.75rem',
              outline: 'none',
            }}
          />
        </div>
      </div>

      {/* Codebase Tree Container */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '6px 0' }}>
        {/* Repo Root Node */}
        <div
          onClick={() => setIsExplorerOpen(!isExplorerOpen)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            padding: '4px 12px',
            cursor: 'pointer',
            fontSize: '0.8rem',
            fontWeight: 600,
            color: 'var(--vscode-text-bright)',
          }}
        >
          {isExplorerOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <Folder size={15} color="#dcb67a" />
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {targetPath === '.' ? 'workspace' : targetPath}
          </span>
        </div>

        {/* File Tree List */}
        {isExplorerOpen && (
          <div style={{ marginLeft: '12px' }}>
            {filteredFiles.length === 0 ? (
              <div style={{ padding: '8px 16px', fontSize: '0.75rem', color: 'var(--vscode-text-muted)' }}>
                No files found
              </div>
            ) : (
              filteredFiles.map((filePath) => {
                const issueCount = issueCountsByFile[filePath] || 0;
                const isSelected = selectedFile === filePath;

                return (
                  <div
                    key={filePath}
                    onClick={() => onSelectFile(filePath)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '4px 12px 4px 16px',
                      cursor: 'pointer',
                      fontSize: '0.78rem',
                      color: isSelected ? 'var(--vscode-text-bright)' : 'var(--vscode-text-main)',
                      background: isSelected ? 'var(--vscode-bg-selected)' : 'transparent',
                      borderRadius: '3px',
                      margin: '1px 4px',
                      transition: 'background 0.1s ease',
                    }}
                    className="hover-opacity"
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', overflow: 'hidden' }}>
                      <FileCode size={14} color={isSelected ? '#61afef' : 'var(--vscode-text-muted)'} />
                      <span
                        style={{
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                          fontFamily: 'JetBrains Mono, monospace',
                        }}
                      >
                        {filePath}
                      </span>
                    </div>

                    {/* Risk Issue Badge */}
                    {issueCount > 0 && (
                      <span
                        style={{
                          background: 'var(--severity-critical-bg)',
                          color: 'var(--severity-critical-text)',
                          border: '1px solid rgba(241, 76, 76, 0.4)',
                          borderRadius: '10px',
                          padding: '1px 6px',
                          fontSize: '0.65rem',
                          fontWeight: 700,
                        }}
                      >
                        {issueCount}
                      </span>
                    )}
                  </div>
                );
              })
            )}
          </div>
        )}
      </div>

      {/* Target Path Switcher Footer */}
      <div
        style={{
          padding: '10px 12px',
          borderTop: '1px solid var(--vscode-border)',
          background: 'var(--vscode-bg-activity)',
          fontSize: '0.72rem',
        }}
      >
        <div style={{ color: 'var(--vscode-text-muted)', marginBottom: '4px' }}>Scan Root Directory:</div>
        <input
          type="text"
          value={targetPath}
          onChange={(e) => setTargetPath(e.target.value)}
          placeholder="e.g. ."
          style={{
            width: '100%',
            background: 'var(--vscode-bg-sidebar)',
            border: '1px solid var(--vscode-border)',
            padding: '4px 8px',
            borderRadius: '3px',
            color: 'var(--vscode-text-main)',
            fontSize: '0.75rem',
            fontFamily: 'monospace',
          }}
        />
      </div>
    </div>
  );
};
