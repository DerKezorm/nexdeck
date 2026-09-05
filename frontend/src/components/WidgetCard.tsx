import { ExternalLink, RefreshCw, Settings2, Trash2 } from 'lucide-react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import type { Action, WidgetData, WidgetView } from '../lib/types'
import { renderWidget } from './renderers'
import { ServiceIcon } from './ServiceIcon'

interface Props {
  widget: WidgetView
  data: WidgetData | undefined
  series?: Record<string, number[]>
  editing?: boolean
  canAct?: boolean
  onAction?: (action: Action) => void
  onRefresh?: () => void
  onSettings?: () => void
  onRemove?: () => void
}

/** The frame every widget shares: header, body, error strip. */
export function WidgetCard({ widget, data, series, editing, canAct, onAction, onRefresh, onSettings, onRemove }: Props) {
  const { t } = useTranslation()
  const status = data?.error ? 'unknown' : (data?.status ?? 'unknown')
  const link = widget.link || data?.link || undefined
  // Clocks and app tiles draw themselves without a header.
  const bare = widget.renderer === 'app' || widget.renderer === 'clock'

  const controls = (
    <>
      {onRefresh && !editing && (
        <button className="btn btn-icon h-6 w-6 border-0 bg-transparent" onClick={onRefresh} aria-label={t('widget.refreshNow')} title={t('widget.refreshNow')}>
          <RefreshCw size={13} />
        </button>
      )}
      {link && !editing && (
        <a className="btn btn-icon h-6 w-6 border-0 bg-transparent" href={link} target="_blank" rel="noreferrer" aria-label={t('widget.openLink')} title={t('widget.openLink')}>
          <ExternalLink size={13} />
        </a>
      )}
      {editing && onSettings && (
        <button className="btn btn-icon h-6 w-6 border-0 bg-transparent" onClick={onSettings} aria-label={t('widget.settings')} title={t('widget.settings')}>
          <Settings2 size={13} />
        </button>
      )}
      {editing && onRemove && (
        <button className="btn btn-icon h-6 w-6 border-0 bg-transparent btn-danger" onClick={onRemove} aria-label={t('widget.remove.title')} title={t('widget.remove.title')}>
          <Trash2 size={13} />
        </button>
      )}
    </>
  )

  return (
    <section
      className={`card glass ${editing ? 'is-editing' : ''}`}
      data-status={status}
      data-widget={widget.id}
      aria-label={widget.title || widget.kind}
    >
      {!bare && (
        <header className="flex items-center gap-2 px-3 pt-2.5 pb-1 min-h-9">
          <ServiceIcon icon={widget.icon} size={18} />
          <h3 className="text-[13px] font-medium truncate flex-1 text-ink/90">{widget.title}</h3>
          {/* While editing the controls stay visible; otherwise they appear on hover. */}
          <div className={`flex items-center gap-1 transition-opacity ${editing ? '' : 'opacity-0 [.card:hover_&]:opacity-100'}`}>{controls}</div>
          <span className="dot" data-status={status} aria-label={status} />
          {widget.beta && <span className="chip !py-0 text-[10px]">beta</span>}
        </header>
      )}
      {bare && editing && (onSettings || onRemove) && (
        <div className="absolute top-2 right-2 z-10 flex items-center gap-1 glass rounded-lg px-0.5">{controls}</div>
      )}
      <div className="flex-1 min-h-0 flex flex-col">
        {renderWidget({ widget, data, series, canAct, onAction, link, editing })}
      </div>
      {data?.error && (
        <footer className="px-3 py-1.5 text-[11px] text-bad border-t border-line truncate" title={String(data.meta?.hint ?? '')}>
          {data.error}
        </footer>
      )}
    </section>
  )
}

export function CardBody({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`flex-1 min-h-0 px-3 pb-3 ${className}`}>{children}</div>
}
