import React, { useState } from 'react';
import { ShieldAlert, AlertTriangle, CheckCircle2, Terminal, ListFilter, X, ChevronUp, ChevronDown } from 'lucide-react';
import { ReviewReport, CodeIssue } from '../types';

interface BottomPanelProps {
  report: ReviewReport | null;
  onSelectIssue: (issue: CodeIssue) => void;
  isOpen: boolean;
  onToggleOpen: () => void;
}

export const BottomPanel: React.FC<BottomPanelProps> = ({
  report,
  onSelectIssue,
  isOpen,
  onToggleOpen,
}) => {
  const [activeTab, setActiveTab] = useState<'problems' | 'terminal' | 'scope'>('problems');
  const [severityFilter, setSeverityFilter] = useState<string>('ALL');

  if (!isOpen) {
    return (
      <div
        style={{
          height: '24px',
          backgroundColor: 'var(--vscode-bg-activity)',
          borderTop: '1px solid var(--vscode-border)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 12px',
          fontSize: '0.72rem',
          color: 'var(--vscode-text-muted)',
          cursor: 'pointer',
          userSelect: 'none',
        }}
        onClick={onToggleOpen}
      >
        <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
          <span>PROBLEMS ({report?.total_issues || 0})</span>
          <span>OUTPUT</span>
          <span>DEVWATCH CONSOLE</span>
        </div>
        <ChevronUp size={14} />
      </div>
    );
  }

  const issues = report?.issues || [];
  const filteredIssues = issues.filter((iss) =>
    severityFilter === 'ALL' ? true : iss.severity === severityFilter
  );

  return (
    <div
      style={{
        height: '200px',
        backgroundColor: 'var(--vscode-bg-panel)',
        borderTop: '1px solid var(--vscode-border)',
        display: 'flex',
        flexDirection: 'column',
        flexShrink: 0,
      }}
    >
      {/* Panel Header & Tabs */}
      <div
        style={{
          backgroundColor: 'var(--vscode-bg-activity)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 12px',
          borderBottom: '1px solid var(--vscode-border)',
          userSelect: 'none',
        }}
      >
        <div style={{ display: 'flex', gap: '4px' }}>
          <button
            onClick={() => setActiveTab('problems')}
            style={{
              background: activeTab === 'problems' ? 'var(--vscode-bg-panel)' : 'transparent',
              border: 'none',
              borderBottom: activeTab === 'problems' ? '2px solid var(--vscode-blue)' : '2px solid transparent',
              color: activeTab === 'problems' ? 'var(--vscode-text-bright)' : 'var(--vscode-text-muted)',
              padding: '6px 12px',
              fontSize: '0.75rem',
              fontWeight: 600,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <span>PROBLEMS</span>
            <span
              style={{
                background: report && report.total_issues > 0 ? 'var(--severity-critical-bg)' : '#333',
                color: report && report.total_issues > 0 ? 'var(--severity-critical-text)' : '#fff',
                padding: '1px 6px',
                borderRadius: '10px',
                fontSize: '0.65rem',
              }}
            >
              {report?.total_issues || 0}
            </span>
          </button>

          <button
            onClick={() => setActiveTab('terminal')}
            style={{
              background: activeTab === 'terminal' ? 'var(--vscode-bg-panel)' : 'transparent',
              border: 'none',
              borderBottom: activeTab === 'terminal' ? '2px solid var(--vscode-blue)' : '2px solid transparent',
              color: activeTab === 'terminal' ? 'var(--vscode-text-bright)' : 'var(--vscode-text-muted)',
              padding: '6px 12px',
              fontSize: '0.75rem',
              fontWeight: 600,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <Terminal size={13} />
            <span>AGENT OUTPUT</span>
          </button>
        </div>

        {/* Action icons / Collapse Button */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {activeTab === 'problems' && (
            <select
              value={severityFilter}
              onChange={(e) => setSeverityFilter(e.target.value)}
              style={{
                background: 'var(--vscode-bg-sidebar)',
                color: 'var(--vscode-text-main)',
                border: '1px solid var(--vscode-border)',
                borderRadius: '3px',
                padding: '2px 6px',
                fontSize: '0.7rem',
                outline: 'none',
              }}
            >
              <option value="ALL">All Severities</option>
              <option value="CRITICAL">CRITICAL</option>
              <option value="HIGH">HIGH</option>
              <option value="MEDIUM">MEDIUM</option>
              <option value="LOW">LOW</option>
            </select>
          )}

          <ChevronDown
            size={14}
            onClick={onToggleOpen}
            style={{ cursor: 'pointer', color: 'var(--vscode-text-muted)' }}
            className="hover-opacity"
          />
        </div>
      </div>

      {/* Tab Content Body */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 12px' }}>
        {activeTab === 'problems' && (
          <div>
            {filteredIssues.length === 0 ? (
              <div style={{ fontSize: '0.78rem', color: 'var(--vscode-text-muted)', padding: '12px' }}>
                No problem findings match current filter criteria.
              </div>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.75rem', textAlign: 'left' }}>
                <thead>
                  <tr style={{ color: 'var(--vscode-text-muted)', borderBottom: '1px solid var(--vscode-border)' }}>
                    <th style={{ padding: '4px 8px' }}>SEVERITY</th>
                    <th style={{ padding: '4px 8px' }}>TITLE</th>
                    <th style={{ padding: '4px 8px' }}>FILE & LINE</th>
                    <th style={{ padding: '4px 8px' }}>CATEGORY</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredIssues.map((issue, idx) => (
                    <tr
                      key={idx}
                      onClick={() => onSelectIssue(issue)}
                      style={{
                        borderBottom: '1px solid var(--vscode-border)',
                        cursor: 'pointer',
                        transition: 'background 0.1s ease',
                      }}
                      className="hover-opacity"
                    >
                      <td style={{ padding: '6px 8px' }}>
                        <span className={`severity-badge severity-${issue.severity.toLowerCase()}`}>
                          {issue.severity}
                        </span>
                      </td>
                      <td style={{ padding: '6px 8px', fontWeight: 500, color: 'var(--vscode-text-bright)' }}>
                        {issue.title}
                      </td>
                      <td style={{ padding: '6px 8px', fontFamily: 'JetBrains Mono, monospace', color: 'var(--vscode-blue)' }}>
                        {issue.file_path}:{issue.line_number || 'N/A'}
                      </td>
                      <td style={{ padding: '6px 8px', color: 'var(--vscode-text-muted)' }}>
                        {issue.category}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {activeTab === 'terminal' && (
          <div style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: '0.75rem', color: '#a9b7c6' }}>
            <div>[INFO] DevWatch Multi-Agent Platform Initialized.</div>
            <div>[INFO] Direct Multi-Agent Orchestrator standing by.</div>

            {report && (
              <>
                <div>[SYSTEM] Scan completed for target path: {report.target_path}</div>
                <div>[SYSTEM] Total issues identified: {report.total_issues}</div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
