import React, { useState } from 'react';
import { runCodeReview } from './services/api';
import { ReviewReport, CodeIssue } from './types';
import { AgentStatusCard } from './components/AgentStatusCard';
import { SummaryHeader } from './components/SummaryHeader';
import { IssueList } from './components/IssueList';
import { CodeViewerModal } from './components/CodeViewerModal';
import { ShieldCheck, Play, Sparkles, FolderGit2 } from 'lucide-react';

interface AgentState {
  name: string;
  role: string;
  status: 'IDLE' | 'RUNNING' | 'COMPLETED' | 'FAILED';
  lastMessage?: string;
}

export const App: React.FC = () => {
  const [targetPath, setTargetPath] = useState<string>('.');
  const [loading, setLoading] = useState<boolean>(false);
  const [report, setReport] = useState<ReviewReport | null>(null);
  const [selectedIssue, setSelectedIssue] = useState<CodeIssue | null>(null);
  const [agents, setAgents] = useState<AgentState[]>([
    { name: 'Planner Agent', role: 'Senior Code Review Architect', status: 'IDLE' },
    { name: 'Security Auditor', role: 'Cybersecurity Vulnerability Auditor', status: 'IDLE' },
    { name: 'Quality Auditor', role: 'Principal Code Quality Analyst', status: 'IDLE' },
    { name: 'Synthesizer Agent', role: 'Technical Review Editor', status: 'IDLE' },
  ]);

  const handleStartReview = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!targetPath) return;

    setLoading(true);
    setReport(null);

    setAgents((prev) =>
      prev.map((a) => ({ ...a, status: 'RUNNING', lastMessage: 'Scanning codebase files...' }))
    );

    try {
      const response = await runCodeReview(targetPath);
      setReport(response.report);

      setAgents((prev) =>
        prev.map((a) => ({ ...a, status: 'COMPLETED', lastMessage: 'Analysis complete.' }))
      );
    } catch (err: any) {
      alert(`Review Failed: ${err.message}`);
      setAgents((prev) =>
        prev.map((a) => ({ ...a, status: 'FAILED', lastMessage: err.message }))
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: '1080px', margin: '0 auto', padding: '36px 20px' }}>
      {/* Top Chrome / Anthropic Brand Header */}
      <div className="agent-window" style={{ marginBottom: '24px' }}>
        <div className="agent-window-header">
          <div className="window-dots">
            <div className="window-dot window-dot-red" />
            <div className="window-dot window-dot-blue" />
            <div className="window-dot window-dot-green" />
          </div>
          <div className="window-title" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <ShieldCheck size={14} color="var(--anthropic-orange)" /> DevWatch OS v0.1.0
          </div>
          <span style={{ fontSize: '0.7rem', color: 'var(--anthropic-text-muted)', fontFamily: 'Fira Code, monospace' }}>
            CrewAI Platform
          </span>
        </div>

        <div style={{ padding: '24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
          <div>
            <h1 className="font-heading" style={{ fontSize: '1.6rem', fontWeight: 700, color: 'var(--anthropic-text-main)', letterSpacing: '-0.02em' }}>
              DevWatch Agent Workspace
            </h1>
            <p style={{ fontSize: '0.88rem', color: 'var(--anthropic-text-muted)', marginTop: '4px' }}>
              Automated multi-agent code review, OWASP vulnerability scanning, and logic analysis.
            </p>
          </div>

          <form onSubmit={handleStartReview} style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
            <div style={{ position: 'relative', width: '260px' }}>
              <FolderGit2 size={15} color="var(--anthropic-text-muted)" style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)' }} />
              <input
                type="text"
                value={targetPath}
                onChange={(e) => setTargetPath(e.target.value)}
                placeholder="Target path (e.g. .)"
                style={{
                  width: '100%',
                  background: '#161614',
                  border: '1px solid var(--anthropic-border-subtle)',
                  padding: '9px 12px 9px 36px',
                  borderRadius: '6px',
                  color: 'white',
                  fontSize: '0.85rem',
                  outline: 'none',
                  fontFamily: 'Lora, Georgia, serif',
                }}
              />
            </div>
            <button type="submit" disabled={loading} className="btn-anthropic">
              {loading ? <Sparkles size={15} /> : <Play size={15} />}
              {loading ? 'Analyzing...' : 'Run Review'}
            </button>
          </form>
        </div>
      </div>

      {/* CrewAI Agent Execution Status Window */}
      <AgentStatusCard agents={agents} />

      {/* Review Metrics & Issues Inspector */}
      {report && (
        <>
          <SummaryHeader report={report} />
          <IssueList issues={report.issues} onSelectIssue={(issue) => setSelectedIssue(issue)} />
        </>
      )}

      {/* Issue Detail Inspector Window */}
      <CodeViewerModal issue={selectedIssue} onClose={() => setSelectedIssue(null)} />
    </div>
  );
};

export default App;
