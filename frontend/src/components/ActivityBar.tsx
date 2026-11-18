import React from 'react'
import { Files, History, Search, Settings, ShieldAlert } from 'lucide-react'

export type ActivityView = 'explorer' | 'search' | 'history' | 'findings' | 'settings'

interface ActivityBarProps {
  activeView: ActivityView
  findingCount?: number
  historyCount?: number
  onSelectView: (view: ActivityView) => void
}

const ITEMS: ReadonlyArray<{
  id: ActivityView
  label: string
  Icon: React.ComponentType<{ className?: string }>
}> = [
  { id: 'explorer', label: 'Explorer', Icon: Files },
  { id: 'search', label: 'Search', Icon: Search },
  { id: 'history', label: 'History', Icon: History },
  { id: 'findings', label: 'Findings', Icon: ShieldAlert },
  { id: 'settings', label: 'Settings', Icon: Settings },
]

export const ActivityBar: React.FC<ActivityBarProps> = ({
  activeView,
  findingCount = 0,
  historyCount = 0,
  onSelectView,
}) => {
  return (
    <nav className="ide-activity-bar" aria-label="IDE Activity Bar">
      {ITEMS.map(({ id, label, Icon }) => {
        const active = activeView === id
        const badge = id === 'findings' ? findingCount : id === 'history' ? historyCount : 0
        return (
          <button
            key={id}
            type="button"
            className={`activity-rail-btn ${active ? 'active' : ''}`}
            aria-label={label}
            aria-pressed={active}
            title={label}
            onClick={() => onSelectView(id)}
          >
            <Icon className="icon-md" />
            {badge > 0 && <span className="activity-rail-badge">{badge > 99 ? '99+' : badge}</span>}
          </button>
        )
      })}
    </nav>
  )
}

