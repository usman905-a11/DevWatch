import React from 'react';
import { CodeIssue } from '../types';
import { X, AlertCircle, Sparkles } from 'lucide-react';

interface CodeViewerModalProps {
  issue: CodeIssue | null;
  onClose: () => void;
}

export const CodeViewerModal: React.FC<CodeViewerModalProps> = ({ issue, onClose }) => {
  if (!issue) return null;

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(0, 0, 0, 0.75)',
        backdropFilter: 'blur(4px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        padding: '24px',
      }}
      onClick={onClose}
    >
      <div
        className="agent-window"
        style={{
          width: '100%',
          maxWidth: '680px',
          maxHeight: '85vh',
          overflowY: 'auto',
          background: 'var(--anthropic-dark)',
          border: '1px solid var(--anthropic-border)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="agent-window-header">
          <div className="window-dots">
            <div className="window-dot window-dot-red" />
            <div className="window-dot window-dot-blue" />
            <div className="window-dot window-dot-green" />
          </div>
          <div className="window-title">Issue Inspector: {issue.category}</div>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', color: 'var(--anthropic-text-muted)', cursor: 'pointer' }}
          >
            <X size={16} />
          </button>
        </div>

        <div style={{ padding: '24px' }}>
          <div style={{ marginBottom: '16px' }}>
            <span className="font-heading" style={{ fontSize: '0.7rem', color: 'var(--anthropic-text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              {issue.severity} SEVERITY
            </span>
            <h2 className="font-heading" style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--anthropic-text-main)', marginTop: '2px' }}>
              {issue.title}
            </h2>
          </div>

          <div style={{ marginBottom: '16px', fontSize: '0.8rem', color: 'var(--anthropic-text-muted)' }}>
            Location: <code style={{ color: 'var(--anthropic-blue)', background: 'var(--anthropic-blue-bg)', padding: '2px 6px', borderRadius: '4px' }}>{issue.file_path}:{issue.line_number || 'N/A'}</code>
          </div>

          <div style={{ marginBottom: '16px' }}>
            <h4 className="font-heading" style={{ fontSize: '0.8rem', color: 'var(--anthropic-text-muted)', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <AlertCircle size={14} color="var(--anthropic-orange)" /> Description
            </h4>
            <p style={{ background: '#161614', border: '1px solid var(--anthropic-border-subtle)', padding: '10px 14px', borderRadius: '6px', fontSize: '0.82rem', color: 'var(--anthropic-text-main)', lineHeight: '1.6' }}>
              {issue.description}
            </p>
          </div>

          {issue.code_snippet && (
            <div style={{ marginBottom: '16px' }}>
              <h4 className="font-heading" style={{ fontSize: '0.8rem', color: 'var(--anthropic-text-muted)', marginBottom: '6px' }}>Offending Code Snippet</h4>
              <pre style={{ background: '#0e0e0d', border: '1px solid var(--anthropic-border-subtle)', padding: '12px 14px', borderRadius: '6px', color: 'var(--severity-critical-text)', overflowX: 'auto', fontSize: '0.8rem' }}>
                <code>{issue.code_snippet}</code>
              </pre>
            </div>
          )}

          <div>
            <h4 className="font-heading" style={{ fontSize: '0.8rem', color: 'var(--anthropic-green)', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Sparkles size={14} color="var(--anthropic-green)" /> Suggested Fix
            </h4>
            <p style={{ background: 'var(--anthropic-green-bg)', border: '1px solid rgba(120, 140, 93, 0.3)', padding: '10px 14px', borderRadius: '6px', fontSize: '0.82rem', color: '#b2c896', lineHeight: '1.6' }}>
              {issue.suggestion}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};
