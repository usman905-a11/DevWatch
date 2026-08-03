import React from 'react';
import { ReviewReport } from '../types';

interface SummaryHeaderProps {
  report: ReviewReport;
}

export const SummaryHeader: React.FC<SummaryHeaderProps> = ({ report }) => {
  return (
    <div className="agent-window" style={{ marginBottom: '24px' }}>
      <div className="agent-window-header">
        <div className="window-dots">
          <div className="window-dot window-dot-red" />
          <div className="window-dot window-dot-blue" />
          <div className="window-dot window-dot-green" />
        </div>
        <div className="window-title">Review Summary Metrics</div>
        <span style={{ fontSize: '0.7rem', color: 'var(--anthropic-text-muted)', fontFamily: 'Fira Code, monospace' }}>
          Target: {report.target_path}
        </span>
      </div>

      <div style={{ padding: '24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '20px' }}>
        <div>
          <h2 className="font-heading" style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--anthropic-text-main)', marginBottom: '4px' }}>
            Codebase Audit Overview
          </h2>
          <p style={{ fontSize: '0.85rem', color: 'var(--anthropic-text-muted)' }}>
            Deduplicated findings across security & code quality analyzer agents.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '14px' }}>
          <div style={{ background: '#161614', border: '1px solid var(--anthropic-border-subtle)', padding: '10px 18px', borderRadius: '8px', textAlign: 'center' }}>
            <span className="font-heading" style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--severity-critical-text)' }}>{report.critical_count}</span>
            <p className="font-heading" style={{ fontSize: '0.7rem', color: 'var(--anthropic-text-muted)', textTransform: 'uppercase', marginTop: '2px' }}>Critical</p>
          </div>

          <div style={{ background: '#161614', border: '1px solid var(--anthropic-border-subtle)', padding: '10px 18px', borderRadius: '8px', textAlign: 'center' }}>
            <span className="font-heading" style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--severity-high-text)' }}>{report.high_count}</span>
            <p className="font-heading" style={{ fontSize: '0.7rem', color: 'var(--anthropic-text-muted)', textTransform: 'uppercase', marginTop: '2px' }}>High</p>
          </div>

          <div style={{ background: '#161614', border: '1px solid var(--anthropic-border-subtle)', padding: '10px 18px', borderRadius: '8px', textAlign: 'center' }}>
            <span className="font-heading" style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--severity-medium-text)' }}>{report.medium_count}</span>
            <p className="font-heading" style={{ fontSize: '0.7rem', color: 'var(--anthropic-text-muted)', textTransform: 'uppercase', marginTop: '2px' }}>Medium</p>
          </div>

          <div style={{ background: '#161614', border: '1px solid var(--anthropic-border-subtle)', padding: '10px 18px', borderRadius: '8px', textAlign: 'center' }}>
            <span className="font-heading" style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--severity-low-text)' }}>{report.low_count}</span>
            <p className="font-heading" style={{ fontSize: '0.7rem', color: 'var(--anthropic-text-muted)', textTransform: 'uppercase', marginTop: '2px' }}>Low</p>
          </div>
        </div>
      </div>
    </div>
  );
};
