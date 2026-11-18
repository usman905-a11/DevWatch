import React from 'react'
import { DEWATCH_MONACO_THEME } from './monacoSetup'

export type ExecutionMode = 'balanced' | 'parallel' | 'sequential'

interface SettingsPanelProps {
  executionMode: ExecutionMode
  jobTokens: string
  onChangeExecutionMode: (mode: ExecutionMode) => void
  onChangeJobTokens: (value: string) => void
}

export const SettingsPanel: React.FC<SettingsPanelProps> = ({
  executionMode,
  jobTokens,
  onChangeExecutionMode,
  onChangeJobTokens,
}) => {
  return (
    <div className="sidebar-panel">
      <div className="sidebar-panel-header">
        <span className="sidebar-panel-title">Settings &amp; Defaults</span>
      </div>
      <div className="settings-stack">
        <section className="settings-card">
          <h3>Execution defaults</h3>
          <label className="settings-field">
            <span>Execution mode</span>
            <select
              value={executionMode}
              onChange={e => onChangeExecutionMode(e.target.value as ExecutionMode)}
            >
              <option value="balanced">Balanced (2 specialists)</option>
              <option value="parallel">Parallel (3 specialists)</option>
              <option value="sequential">Sequential (1 specialist)</option>
            </select>
          </label>
          <label className="settings-field">
            <span>Token budget (optional)</span>
            <input
              type="number"
              min={1000}
              step={1000}
              placeholder="Default backend limit"
              value={jobTokens}
              onChange={e => onChangeJobTokens(e.target.value)}
            />
          </label>
        </section>

        <section className="settings-card">
          <h3>Backend connection</h3>
          <p className="settings-kv">
            <span>Auth:</span> <code>Configured via .env</code>
          </p>
          <p className="settings-hint">
            Service URL and authentication credentials are supplied server-side from the root .env configuration.
          </p>
        </section>

        <section className="settings-card">
          <h3>Editor environment</h3>
          <p className="settings-kv">
            <span>Theme:</span> <code>{DEWATCH_MONACO_THEME}</code>
          </p>
          <p className="settings-kv">
            <span>Mode:</span> <code>Read-only code audit</code>
          </p>
        </section>
      </div>
    </div>
  )
}

