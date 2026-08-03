import React from 'react';
import { Files, Search, ShieldAlert, CheckCircle2, Bot, Settings, Play } from 'lucide-react';

export type ActivityView = 'explorer' | 'security' | 'quality' | 'chat' | 'settings';

interface ActivityBarProps {
  activeView: ActivityView;
  setActiveView: (view: ActivityView) => void;
  onRunReview: () => void;
  loading: boolean;
  totalIssuesCount?: number;
}

export const ActivityBar: React.FC<ActivityBarProps> = ({
  activeView,
  setActiveView,
  onRunReview,
  loading,
  totalIssuesCount = 0,
}) => {
  return (
    <div
      style={{
        width: '48px',
        backgroundColor: 'var(--vscode-bg-activity)',
        borderRight: '1px solid var(--vscode-border)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '10px 0',
        userSelect: 'none',
        flexShrink: 0,
        zIndex: 20,
      }}
    >
      {/* Top Icons */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', alignItems: 'center' }}>
        {/* Play / Trigger Review Button */}
        <button
          onClick={onRunReview}
          disabled={loading}
          title="Run Multi-Agent Code Review"
          style={{
            width: '34px',
            height: '34px',
            borderRadius: '6px',
            background: loading ? '#333' : 'var(--vscode-blue)',
            border: 'none',
            color: '#fff',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: loading ? 'not-allowed' : 'pointer',
            transition: 'transform 0.15s ease, background 0.15s ease',
            boxShadow: '0 2px 8px rgba(0, 122, 204, 0.4)',
          }}
        >
          <Play size={16} fill="white" style={{ marginLeft: '2px' }} />
        </button>

        <div style={{ width: '28px', height: '1px', background: 'var(--vscode-border)' }} />

        {/* Explorer Toggle */}
        <button
          onClick={() => setActiveView('explorer')}
          title="Explorer (Files & Risk Scope)"
          style={{
            background: 'transparent',
            border: 'none',
            color: activeView === 'explorer' ? 'var(--vscode-text-bright)' : 'var(--vscode-text-muted)',
            padding: '8px',
            borderRadius: '4px',
            cursor: 'pointer',
            position: 'relative',
            borderLeft: activeView === 'explorer' ? '2px solid var(--vscode-blue)' : '2px solid transparent',
          }}
        >
          <Files size={20} />
        </button>

        {/* Security Audit View */}
        <button
          onClick={() => setActiveView('security')}
          title="Security Auditor Findings"
          style={{
            background: 'transparent',
            border: 'none',
            color: activeView === 'security' ? 'var(--severity-critical-text)' : 'var(--vscode-text-muted)',
            padding: '8px',
            borderRadius: '4px',
            cursor: 'pointer',
            position: 'relative',
            borderLeft: activeView === 'security' ? '2px solid var(--severity-critical-text)' : '2px solid transparent',
          }}
        >
          <ShieldAlert size={20} />
          {totalIssuesCount > 0 && (
            <span
              style={{
                position: 'absolute',
                top: '2px',
                right: '2px',
                background: 'var(--severity-critical-text)',
                color: '#fff',
                borderRadius: '50%',
                width: '14px',
                height: '14px',
                fontSize: '0.6rem',
                fontWeight: 700,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              {totalIssuesCount > 9 ? '9+' : totalIssuesCount}
            </span>
          )}
        </button>

        {/* Quality Audit View */}
        <button
          onClick={() => setActiveView('quality')}
          title="Quality Auditor Findings"
          style={{
            background: 'transparent',
            border: 'none',
            color: activeView === 'quality' ? 'var(--severity-medium-text)' : 'var(--vscode-text-muted)',
            padding: '8px',
            borderRadius: '4px',
            cursor: 'pointer',
            borderLeft: activeView === 'quality' ? '2px solid var(--severity-medium-text)' : '2px solid transparent',
          }}
        >
          <CheckCircle2 size={20} />
        </button>

        {/* Agent Chat View */}
        <button
          onClick={() => setActiveView('chat')}
          title="Agent Crew Chat & Status"
          style={{
            background: 'transparent',
            border: 'none',
            color: activeView === 'chat' ? 'var(--vscode-blue)' : 'var(--vscode-text-muted)',
            padding: '8px',
            borderRadius: '4px',
            cursor: 'pointer',
            borderLeft: activeView === 'chat' ? '2px solid var(--vscode-blue)' : '2px solid transparent',
          }}
        >
          <Bot size={20} />
        </button>
      </div>

      {/* Bottom Settings Icon */}
      <div>
        <button
          onClick={() => setActiveView('settings')}
          title="Settings & Config"
          style={{
            background: 'transparent',
            border: 'none',
            color: activeView === 'settings' ? 'var(--vscode-text-bright)' : 'var(--vscode-text-muted)',
            padding: '8px',
            borderRadius: '4px',
            cursor: 'pointer',
          }}
        >
          <Settings size={20} />
        </button>
      </div>
    </div>
  );
};
