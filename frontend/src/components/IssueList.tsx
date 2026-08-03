import React, { useState } from 'react';
import { CodeIssue, IssueSeverity } from '../types';
import { Search, ChevronRight, FileCode } from 'lucide-react';

interface IssueListProps {
  issues: CodeIssue[];
  onSelectIssue: (issue: CodeIssue) => void;
}

export const IssueList: React.FC<IssueListProps> = ({ issues, onSelectIssue }) => {
  const [filterSeverity, setFilterSeverity] = useState<string>('ALL');
  const [searchTerm, setSearchTerm] = useState<string>('');

  const filteredIssues = issues.filter((issue) => {
    const matchesSeverity = filterSeverity === 'ALL' || issue.severity === filterSeverity;
    const matchesSearch =
      issue.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
      issue.file_path.toLowerCase().includes(searchTerm.toLowerCase()) ||
      issue.category.toLowerCase().includes(searchTerm.toLowerCase());
    return matchesSeverity && matchesSearch;
  });

  const getSeverityBadge = (severity: IssueSeverity) => {
    switch (severity) {
      case 'CRITICAL':
        return <span className="tag-badge tag-critical">Critical</span>;
      case 'HIGH':
        return <span className="tag-badge tag-high">High</span>;
      case 'MEDIUM':
        return <span className="tag-badge tag-medium">Medium</span>;
      case 'LOW':
        return <span className="tag-badge tag-low">Low</span>;
      default:
        return <span className="tag-badge">{severity}</span>;
    }
  };

  return (
    <div className="agent-window">
      <div className="agent-window-header">
        <div className="window-dots">
          <div className="window-dot window-dot-red" />
          <div className="window-dot window-dot-blue" />
          <div className="window-dot window-dot-green" />
        </div>
        <div className="window-title">Detected Issues Inspector</div>
        <span style={{ fontSize: '0.7rem', color: 'var(--anthropic-text-muted)', fontFamily: 'Fira Code, monospace' }}>
          {filteredIssues.length} Findings
        </span>
      </div>

      <div style={{ padding: '20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '12px' }}>
          <div style={{ position: 'relative', width: '280px' }}>
            <Search size={14} color="var(--anthropic-text-muted)" style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)' }} />
            <input
              type="text"
              placeholder="Search by file or title..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              style={{
                width: '100%',
                background: '#161614',
                border: '1px solid var(--anthropic-border-subtle)',
                padding: '6px 12px 6px 30px',
                borderRadius: '6px',
                color: 'white',
                outline: 'none',
                fontSize: '0.8rem',
                fontFamily: 'Lora, Georgia, serif',
              }}
            />
          </div>

          <div style={{ display: 'flex', gap: '4px' }}>
            {['ALL', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].map((sev) => (
              <button
                key={sev}
                onClick={() => setFilterSeverity(sev)}
                className="font-heading"
                style={{
                  background: filterSeverity === sev ? 'var(--anthropic-orange-bg)' : 'transparent',
                  border: filterSeverity === sev ? '1px solid var(--anthropic-orange)' : '1px solid transparent',
                  color: filterSeverity === sev ? 'var(--anthropic-orange)' : 'var(--anthropic-text-muted)',
                  padding: '4px 10px',
                  borderRadius: '6px',
                  fontSize: '0.75rem',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                {sev}
              </button>
            ))}
          </div>
        </div>

        {filteredIssues.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '32px', color: 'var(--anthropic-text-muted)', fontSize: '0.85rem' }}>
            No issues match the selected filter criteria.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {filteredIssues.map((issue, idx) => (
              <div
                key={idx}
                onClick={() => onSelectIssue(issue)}
                style={{
                  background: '#161614',
                  border: '1px solid var(--anthropic-border-subtle)',
                  borderRadius: '8px',
                  padding: '12px 16px',
                  cursor: 'pointer',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  transition: 'background 0.15s ease',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'var(--anthropic-surface-hover)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = '#161614';
                }}
              >
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                    {getSeverityBadge(issue.severity)}
                    <span className="font-heading" style={{ fontWeight: 600, fontSize: '0.9rem', color: 'var(--anthropic-text-main)' }}>
                      {issue.title}
                    </span>
                    <span style={{ fontSize: '0.7rem', color: 'var(--anthropic-text-muted)', background: 'rgba(255,255,255,0.04)', padding: '2px 6px', borderRadius: '4px', fontFamily: 'Poppins, sans-serif' }}>
                      {issue.category}
                    </span>
                  </div>
                  <p style={{ fontSize: '0.78rem', color: 'var(--anthropic-text-muted)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <FileCode size={13} color="var(--anthropic-blue)" />
                    <code>{issue.file_path}:{issue.line_number || 'N/A'}</code> — {issue.description}
                  </p>
                </div>
                <ChevronRight size={16} color="var(--anthropic-text-subtle)" />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
