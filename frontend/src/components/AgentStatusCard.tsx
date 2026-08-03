import React from 'react';
import { Terminal, CheckCircle2, Loader2, AlertCircle } from 'lucide-react';

interface AgentStatusCardProps {
  agents: Array<{
    name: string;
    role: string;
    status: 'IDLE' | 'RUNNING' | 'COMPLETED' | 'FAILED';
    lastMessage?: string;
  }>;
}

export const AgentStatusCard: React.FC<AgentStatusCardProps> = ({ agents }) => {
  return (
    <div className="agent-window" style={{ marginBottom: '24px' }}>
      <div className="agent-window-header">
        <div className="window-dots">
          <div className="window-dot window-dot-red" />
          <div className="window-dot window-dot-blue" />
          <div className="window-dot window-dot-green" />
        </div>
        <div className="window-title" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Terminal size={14} color="var(--anthropic-orange)" /> CrewAI Execution Crew
        </div>
        <span style={{ fontSize: '0.7rem', color: 'var(--anthropic-text-muted)', fontFamily: 'Fira Code, monospace' }}>
          4 Active Agents
        </span>
      </div>

      <div style={{ padding: '20px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '16px' }}>
        {agents.map((agent) => (
          <div
            key={agent.name}
            style={{
              padding: '16px',
              borderRadius: '8px',
              background: '#161614',
              border: '1px solid var(--anthropic-border-subtle)',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
            }}
          >
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                <span className="font-heading" style={{ fontWeight: 600, fontSize: '0.9rem', color: 'var(--anthropic-text-main)' }}>
                  {agent.name}
                </span>
                {agent.status === 'RUNNING' && <Loader2 size={15} color="var(--anthropic-orange)" style={{ animation: 'spin 1s linear infinite' }} />}
                {agent.status === 'COMPLETED' && <CheckCircle2 size={15} color="var(--anthropic-green)" />}
                {agent.status === 'FAILED' && <AlertCircle size={15} color="var(--anthropic-orange)" />}
                {agent.status === 'IDLE' && <span style={{ fontSize: '0.7rem', color: 'var(--anthropic-text-subtle)' }}>Idle</span>}
              </div>
              <p style={{ fontSize: '0.78rem', color: 'var(--anthropic-text-muted)', marginBottom: '10px' }}>{agent.role}</p>
            </div>

            {agent.lastMessage && (
              <p style={{ fontSize: '0.75rem', color: 'var(--anthropic-text-muted)', background: '#111110', padding: '6px 10px', borderRadius: '6px', fontFamily: 'Fira Code, monospace' }}>
                &gt; {agent.lastMessage}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};
