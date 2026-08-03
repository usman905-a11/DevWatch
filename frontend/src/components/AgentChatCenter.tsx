import React, { useState } from 'react';
import { Bot, Send, Sparkles, CheckCircle2, Clock, AlertCircle, RefreshCw, Cpu } from 'lucide-react';
import { ReviewReport } from '../types';

export interface AgentState {
  name: string;
  role: string;
  status: 'IDLE' | 'RUNNING' | 'COMPLETED' | 'FAILED';
  lastMessage?: string;
}

interface AgentChatCenterProps {
  agents: AgentState[];
  report: ReviewReport | null;
  loading: boolean;
  onRunReview: () => void;
}

interface ChatMessage {
  sender: 'user' | 'agent';
  agentName?: string;
  text: string;
  timestamp: string;
}

export const AgentChatCenter: React.FC<AgentChatCenterProps> = ({
  agents,
  report,
  loading,
  onRunReview,
}) => {
  const [inputMsg, setInputMsg] = useState<string>('');
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([
    {
      sender: 'agent',
      agentName: 'Planner Agent',
      text: 'DevWatch Multi-Agent Crew ready. Click "Run Review" to scan for OWASP security threats and reliability flaws.',
      timestamp: 'Just now',
    },
  ]);

  const handleSendMessage = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputMsg.trim()) return;

    const newMsg: ChatMessage = {
      sender: 'user',
      text: inputMsg,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    setChatMessages((prev) => [...prev, newMsg]);
    setInputMsg('');

    // Simulate AI Agent response
    setTimeout(() => {
      let reply = "Analyzing your request against the latest review findings...";
      if (report && report.issues.length > 0) {
        reply = `I identified ${report.total_issues} total issues (${report.critical_count} Critical, ${report.high_count} High). Would you like me to generate a refactoring patch for a specific file?`;
      } else {
        reply = "The codebase looks clean! No severe OWASP vulnerabilities or reliability anti-patterns detected.";
      }

      setChatMessages((prev) => [
        ...prev,
        {
          sender: 'agent',
          agentName: 'Synthesizer Agent',
          text: reply,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        },
      ]);
    }, 600);
  };

  return (
    <div
      style={{
        width: '320px',
        backgroundColor: 'var(--vscode-bg-panel)',
        borderLeft: '1px solid var(--vscode-border)',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        flexShrink: 0,
      }}
    >
      {/* Panel Header */}
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
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Bot size={15} color="var(--vscode-blue)" />
          <span>AGENT CREW CENTER</span>
        </div>
        <span style={{ fontSize: '0.65rem', background: 'var(--vscode-bg-activity)', padding: '2px 6px', borderRadius: '4px' }}>
          LLM ACTIVE
        </span>
      </div>

      {/* Crew Agent Execution Status Pipeline */}
      <div style={{ padding: '12px', borderBottom: '1px solid var(--vscode-border)', backgroundColor: 'var(--vscode-bg-sidebar)' }}>
        <div style={{ fontSize: '0.72rem', fontWeight: 600, color: 'var(--vscode-text-muted)', marginBottom: '8px' }}>
          CREW PIPELINE PIPELINE STATUS:
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {agents.map((agent) => (
            <div
              key={agent.name}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '0.75rem',
                padding: '4px 8px',
                borderRadius: '4px',
                background: agent.status === 'RUNNING' ? 'rgba(0, 122, 204, 0.15)' : 'transparent',
                border: agent.status === 'RUNNING' ? '1px solid var(--vscode-blue)' : '1px solid transparent',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                {agent.status === 'COMPLETED' && <CheckCircle2 size={13} color="var(--severity-low-text)" />}
                {agent.status === 'RUNNING' && <RefreshCw size={13} color="var(--vscode-blue)" className="spin" />}
                {agent.status === 'FAILED' && <AlertCircle size={13} color="var(--severity-critical-text)" />}
                {agent.status === 'IDLE' && <Clock size={13} color="var(--vscode-text-muted)" />}
                <span style={{ fontWeight: 500, color: 'var(--vscode-text-bright)' }}>{agent.name}</span>
              </div>

              <span
                style={{
                  fontSize: '0.65rem',
                  fontWeight: 600,
                  color:
                    agent.status === 'COMPLETED'
                      ? 'var(--severity-low-text)'
                      : agent.status === 'RUNNING'
                      ? 'var(--vscode-blue)'
                      : 'var(--vscode-text-muted)',
                }}
              >
                {agent.status}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* AI Chat History Container */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
        {chatMessages.map((msg, idx) => (
          <div
            key={idx}
            style={{
              alignSelf: msg.sender === 'user' ? 'flex-end' : 'flex-start',
              maxWidth: '90%',
              backgroundColor: msg.sender === 'user' ? 'var(--vscode-accent)' : 'var(--vscode-bg-activity)',
              border: '1px solid var(--vscode-border-light)',
              borderRadius: '8px',
              padding: '8px 12px',
              fontSize: '0.78rem',
              color: 'var(--vscode-text-bright)',
            }}
          >
            {msg.agentName && (
              <div style={{ fontSize: '0.68rem', fontWeight: 600, color: 'var(--vscode-blue)', marginBottom: '3px' }}>
                {msg.agentName}
              </div>
            )}
            <div style={{ lineHeight: '1.4' }}>{msg.text}</div>
            <div style={{ fontSize: '0.62rem', color: 'var(--vscode-text-muted)', textAlign: 'right', marginTop: '4px' }}>
              {msg.timestamp}
            </div>
          </div>
        ))}
      </div>

      {/* Interactive Chat Form Input */}
      <form
        onSubmit={handleSendMessage}
        style={{
          padding: '10px 12px',
          borderTop: '1px solid var(--vscode-border)',
          backgroundColor: 'var(--vscode-bg-sidebar)',
          display: 'flex',
          gap: '6px',
        }}
      >
        <input
          type="text"
          value={inputMsg}
          onChange={(e) => setInputMsg(e.target.value)}
          placeholder="Ask Agent Crew to refactor code..."
          style={{
            flex: 1,
            background: 'var(--vscode-bg-editor)',
            border: '1px solid var(--vscode-border-light)',
            borderRadius: '4px',
            padding: '6px 10px',
            color: 'var(--vscode-text-main)',
            fontSize: '0.75rem',
            outline: 'none',
          }}
        />
        <button
          type="submit"
          className="btn-primary"
          style={{ padding: '6px 10px' }}
        >
          <Send size={13} />
        </button>
      </form>
    </div>
  );
};
