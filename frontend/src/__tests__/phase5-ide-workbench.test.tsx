import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import fixture from './fixtures/canonical-wire.json'
import App from '../App'
import { ActivityBar } from '../components/ActivityBar'
import { BottomDrawer } from '../components/BottomDrawer'
import { CodeEditor } from '../components/CodeEditor'
import { FileExplorer } from '../components/FileExplorer'
import { FolderPickerModal } from '../components/FolderPickerModal'
import { HistoryPanel } from '../components/HistoryPanel'
import { SettingsPanel } from '../components/SettingsPanel'
import { WorkspaceSearchPanel } from '../components/WorkspaceSearchPanel'
import { JobActivity } from '../review/JobActivity'
import { ReportPanel } from '../review/ReportPanel'
import type { JobView, ReportDraft, StreamEvent } from '../review/wire'

const job = fixture.job as JobView
const report = {
  ...(fixture.report as ReportDraft),
  coverage: {
    ...(fixture.report as ReportDraft).coverage,
    metrics: {
      total_discovered: 120,
      eligible: 42,
      excluded: 78,
      excluded_by_reason: { ignored_dir: 70, too_large: 8 },
      assigned: 25,
      inspected: 18,
      skipped_limits: 0,
      failed: 0,
    },
  },
} as ReportDraft

describe('Phase 5 Modern Dark IDE Workbench', () => {
  it('renders the Dark IDE shell preserving connection, workspace, execution mode, token budget, and job contracts', () => {
    const html = renderToStaticMarkup(<App />)
    expect(html).toContain('ide-shell')
    expect(html).toContain('Execution mode')
    expect(html).toContain('Token budget')
    expect(html).toContain('balanced')
    expect(html).toContain('parallel')
    expect(html).toContain('sequential')
    expect(html).toContain('Resize sidebar')
    expect(html).toContain('Open local folder')
    expect(html).toContain('Choose folder')
    expect(html).not.toContain('Folder path')
    expect(html).not.toContain('Set workspace')
    expect(html).not.toContain('Service URL')
    expect(html).not.toContain('API key')
    expect(html).not.toContain('Open job')
    expect(html).not.toContain('Repository path')
    expect(html).not.toContain('Apply fix')
  })

  it('renders the left activity bar tabs, filterable FileExplorer with finding counts, HistoryPanel, Search, and Settings', () => {
    const railHtml = renderToStaticMarkup(
      <ActivityBar activeView="explorer" findingCount={3} historyCount={2} onSelectView={vi.fn()} />,
    )
    expect(railHtml).toContain('Explorer')
    expect(railHtml).toContain('Search')
    expect(railHtml).toContain('History')
    expect(railHtml).toContain('Findings')
    expect(railHtml).toContain('Settings')

    const explorerHtml = renderToStaticMarkup(
      <FileExplorer
        workspacePath="E:/repo"
        selectedFile="src/app.py"
        findingCounts={{ 'src/app.py': 2 }}
        onSelectFile={vi.fn()}
        loadDir={async () => []}
      />,
    )
    expect(explorerHtml).toContain('Filter files')

    const nowSeconds = Math.floor(Date.now() / 1000)
    const richJob = {
      ...job,
      created_at: nowSeconds - 120,
      updated_at: nowSeconds - 60,
      workspace_path: 'E:/repo/my-app',
      summary_preview: 'Checked auth & SQL parameterization',
      finding_counts: { defects: 2, uncertain: 1, advisories: 0 },
    }
    const historyHtml = renderToStaticMarkup(
      <HistoryPanel
        jobs={[richJob]}
        activeJobId={richJob.job_id}
        activeWorkspacePath="E:/repo/my-app"
        onSelectJob={vi.fn()}
        onNewReview={vi.fn()}
        onRefresh={vi.fn()}
      />,
    )
    expect(historyHtml).toContain('Review History')
    expect(historyHtml).toContain('New review')
    expect(historyHtml).toContain('Today')
    expect(historyHtml).toContain('Checked auth &amp; SQL parameterization')
    expect(historyHtml).toContain('2 defects')

    const searchHtml = renderToStaticMarkup(
      <WorkspaceSearchPanel
        tabs={[
          {
            path: 'src/auth.py',
            loading: false,
            file: { path: 'src/auth.py', size: 32, binary: false, tooLarge: false, maxBytes: 1000, lineCount: 2, content: 'def verify():\n  return True' },
          },
        ]}
        initialQuery="verify"
        onJumpToLine={vi.fn()}
      />,
    )
    expect(searchHtml).toContain('src/auth.py')
    expect(searchHtml).toContain('verify')

    const settingsHtml = renderToStaticMarkup(
      <SettingsPanel
        executionMode="balanced"
        jobTokens="120000"
        onChangeExecutionMode={vi.fn()}
        onChangeJobTokens={vi.fn()}
      />,
    )
    expect(settingsHtml).toContain('Execution defaults')
    expect(settingsHtml).toContain('dewatch-dark')
    expect(settingsHtml).toContain('.env')

    const pickerHtml = renderToStaticMarkup(
      <FolderPickerModal
        open
        browseData={{
          current_path: 'E:/projects',
          parent_path: 'E:/',
          roots: [{ name: 'Home', path: 'C:/Users/HP' }, { name: 'E:\\', path: 'E:\\' }],
          directories: [{ name: 'dewatch', path: 'E:/projects/dewatch' }],
        }}
        loading={false}
        error={null}
        onNavigate={vi.fn()}
        onSelectFolder={vi.fn()}
        onClose={vi.fn()}
      />,
    )
    expect(pickerHtml).toContain('role="dialog"')
    expect(pickerHtml).toContain('E:/projects')
    expect(pickerHtml).toContain('dewatch')
    expect(pickerHtml).toContain('Open Selected Folder')
  })

  it('shows code breadcrumb, finding count badge on tabs, rich 7-agent grid, filtered report controls, and bottom workbench drawer', () => {
    const editorHtml = renderToStaticMarkup(
      <CodeEditor
        tabs={[
          {
            path: 'src/auth.py',
            loading: false,
            file: { path: 'src/auth.py', size: 20, binary: false, tooLarge: false, maxBytes: 1000, lineCount: 1, content: 'x = 1' },
          },
        ]}
        activePath="src/auth.py"
        highlightRange={{ path: 'src/auth.py', startLine: 1, endLine: 1 }}
        findings={report.confirmed_defects}
        onSelectTab={vi.fn()}
        onCloseTab={vi.fn()}
      />,
    )
    expect(editorHtml).toContain('editor-breadcrumb')
    expect(editorHtml).toContain('src/auth.py')

    const events: StreamEvent[] = [
      { job_id: job.job_id, seq: 1, timestamp: 1, type: 'agent_started', payload: { agent_id: 'bug_reliability', task_id: 't1' } },
      { job_id: job.job_id, seq: 2, timestamp: 2, type: 'tool_called', payload: { agent_id: 'bug_reliability', task_id: 't1', tool: 'read_file' } },
    ]
    const activityHtml = renderToStaticMarkup(<JobActivity events={events} job={{ ...job, status: 'running' }} connection="connected" />)
    expect(activityHtml).toContain('agent-card-grid')
    expect(activityHtml).toContain('Bug &amp; Reliability')
    expect(activityHtml).toContain('Seven review agents')

    const reportHtml = renderToStaticMarkup(<ReportPanel report={report} onSource={vi.fn()} />)
    expect(reportHtml).toContain('Filter findings')
    expect(reportHtml).toContain('Severity:')
    expect(reportHtml).toContain('Confirmed defects (')

    const drawerHtml = renderToStaticMarkup(
      <BottomDrawer
        activeTab="coverage"
        open
        report={report}
        events={events}
        steps={[]}
        onToggleOpen={vi.fn()}
        onSelectTab={vi.fn()}
        onOpenFinding={vi.fn()}
      />,
    )
    expect(drawerHtml).toContain('Problems')
    expect(drawerHtml).toContain('Coverage &amp; Audit')
    expect(drawerHtml).toContain('Execution Logs')
    expect(drawerHtml).toContain('120')
    expect(drawerHtml).toContain('42.9%')
  })
})
