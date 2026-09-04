import { ExternalLink, LayoutDashboard, Play, Settings, Zap } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

import type { BoardSummary } from '../api/types'
import type { Action, WidgetView } from '../lib/types'
import { ServiceIcon } from './ServiceIcon'

interface Entry {
  id: string
  title: string
  subtitle?: string
  icon?: React.ReactNode
  run: () => void
  keywords: string
}

interface Props {
  open: boolean
  onClose: () => void
  boards: BoardSummary[]
  widgets: WidgetView[]
  actions?: { widget: WidgetView; action: Action }[]
  onAction?: (widgetId: number, action: Action) => void
}

/** Ctrl+K: services, actions, boards, pages and settings, all from the keyboard. */
export function CommandPalette({ open, onClose, boards, widgets, actions = [], onAction }: Props) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [index, setIndex] = useState(0)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) {
      setQuery('')
      setIndex(0)
      window.setTimeout(() => input.current?.focus(), 10)
    }
  }, [open])

  const entries = useMemo<Entry[]>(() => {
    const list: Entry[] = []
    for (const widget of widgets) {
      if (widget.link) {
        list.push({ id: `w${widget.id}`, title: widget.title, subtitle: t('palette.open'), icon: <ServiceIcon icon={widget.icon} size={16} />, keywords: `${widget.title} ${widget.kind}`.toLowerCase(), run: () => window.open(widget.link, '_blank', 'noopener') })
      }
    }
    for (const { widget, action } of actions) {
      list.push({ id: `a${widget.id}-${action.id}`, title: `${action.label} · ${widget.title}`, subtitle: t('palette.action'), icon: <Zap size={16} className="text-accent" />, keywords: `${action.label} ${widget.title}`.toLowerCase(), run: () => onAction?.(widget.id, action) })
    }
    for (const board of boards) {
      list.push({ id: `b${board.id}`, title: board.name, subtitle: t('palette.board'), icon: <LayoutDashboard size={16} />, keywords: `${board.name} board`.toLowerCase(), run: () => navigate(`/b/${board.slug}`) })
      for (const page of board.pages) {
        list.push({ id: `p${page.id}`, title: `${board.name} › ${page.name}`, subtitle: t('palette.page'), icon: <LayoutDashboard size={16} />, keywords: `${board.name} ${page.name}`.toLowerCase(), run: () => navigate(`/b/${board.slug}/${page.slug}`) })
      }
    }
    for (const [path, label] of [['/settings', t('settings.title')], ['/settings/integrations', t('settings.integrations.title')], ['/settings/boards', t('settings.boards.title')], ['/settings/channels', t('settings.channels.title')], ['/notices', t('notices.title')]]) {
      list.push({ id: `s${path}`, title: label, subtitle: t('palette.settings'), icon: <Settings size={16} />, keywords: label.toLowerCase(), run: () => navigate(path) })
    }
    return list
  }, [widgets, actions, boards, navigate, onAction, t])

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const matches = needle ? entries.filter((e) => e.keywords.includes(needle)) : entries
    return matches.slice(0, 12)
  }, [entries, query])

  if (!open) return null
  const run = (entry: Entry) => {
    entry.run()
    onClose()
  }
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[12vh] px-4" role="dialog" aria-modal="true" aria-label={t('palette.title')}>
      <div className="absolute inset-0 bg-black/50" onClick={onClose} aria-hidden="true" />
      <div className="relative glass-strong rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden">
        <input
          ref={input}
          className="w-full h-12 px-4 bg-transparent outline-none text-[15px]"
          placeholder={t('palette.placeholder')}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            setIndex(0)
          }}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') {
              e.preventDefault()
              setIndex((i) => Math.min(filtered.length - 1, i + 1))
            } else if (e.key === 'ArrowUp') {
              e.preventDefault()
              setIndex((i) => Math.max(0, i - 1))
            } else if (e.key === 'Enter' && filtered[index]) {
              run(filtered[index])
            } else if (e.key === 'Escape') {
              onClose()
            }
          }}
          aria-label={t('palette.title')}
        />
        <ul className="border-t border-line max-h-[50vh] scroll py-1" role="listbox">
          {filtered.length === 0 && <li className="px-4 py-3 text-sm text-muted">{t('palette.nothing')}</li>}
          {filtered.map((entry, i) => (
            <li key={entry.id} role="option" aria-selected={i === index}>
              <button className={`w-full flex items-center gap-3 px-4 py-2 text-left ${i === index ? 'bg-accent-soft' : 'hover:bg-surface-hover'}`} onMouseEnter={() => setIndex(i)} onClick={() => run(entry)}>
                <span className="w-5 flex justify-center text-muted">{entry.icon ?? <Play size={14} />}</span>
                <span className="flex-1 truncate text-sm">{entry.title}</span>
                <span className="text-[11px] text-faint">{entry.subtitle}</span>
                {entry.id.startsWith('w') && <ExternalLink size={12} className="text-faint" />}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
