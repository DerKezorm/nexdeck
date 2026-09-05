import type { LucideIcon } from 'lucide-react'
import { NavLink } from 'react-router-dom'

export interface NavEntry {
  /** Path below the base; the empty string is the index page. */
  to: string
  icon: LucideIcon
  label: string
  /** Left out when false. Undefined means: show it. */
  show?: boolean
}

/** The left-hand list shared by the account settings and the system settings. */
export function SettingsNav({ base, entries, label }: { base: string; entries: NavEntry[]; label: string }) {
  return (
    <nav className="flex md:flex-col gap-1 overflow-x-auto" aria-label={label}>
      {entries
        .filter((entry) => entry.show !== false)
        .map((entry) => (
          <NavLink
            key={entry.to}
            to={entry.to ? `${base}/${entry.to}` : base}
            end={entry.to === ''}
            className={({ isActive }) =>
              `flex items-center gap-2 h-9 px-3 rounded-lg text-sm whitespace-nowrap ${isActive ? 'bg-accent-soft text-accent font-medium' : 'text-muted hover:text-ink hover:bg-surface-hover'}`
            }
          >
            <entry.icon size={15} />
            {entry.label}
          </NavLink>
        ))}
    </nav>
  )
}
