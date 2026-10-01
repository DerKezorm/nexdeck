import { AlertTriangle, Ellipsis, ExternalLink, RefreshCw, Settings2, Trash2 } from 'lucide-react'
import type { MouseEvent, ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { cardStatus } from '../lib/cardStatus'
import { safeUrl } from '../lib/safeUrl'
import { useDisguise } from '../lib/showcase'

import { tLabel } from '../i18n/texts'
import type { Action, WidgetData, WidgetView } from '../lib/types'
import { renderWidget } from './renderers'
import { ServiceIcon } from './ServiceIcon'

interface Props {
  widget: WidgetView
  data: WidgetData | undefined
  series?: Record<string, number[]>
  editing?: boolean
  canAct?: boolean
  canWrite?: boolean
  onAction?: (action: Action) => void
  onRefresh?: () => void
  onSettings?: () => void
  onRemove?: () => void
  /** Opens the menu of sizes and pages, below the button that was pressed. */
  onArrange?: (anchor: DOMRect) => void
}

const INTERACTIVE = 'a, button, input, select, textarea, [role="button"], .no-click'

/** The frame every widget shares: header, floating controls, body, error strip. */
export function WidgetCard({ widget, data, series, editing, canAct, canWrite, onAction, onRefresh, onSettings, onRemove, onArrange }: Props) {
  const { t, i18n } = useTranslation()
  const disguise = useDisguise()
  // A camera, an embedded page and a note show the home itself, and nothing in
  // them can be told apart from the rest: in showcase mode they are blurred.
  const veiled = disguise.on && ['camera', 'iframe', 'text'].includes(widget.renderer)
  // A failed fetch is an error state of its own: red, with the server's reason.
  // The server names the reason by code; other languages translate the code,
  // English shows the server's own sentence with its specifics.
  const failed = Boolean(data?.error)
  // With findings switched off, the card keeps its numbers and drops the alarm:
  // a Findings card next to it says what is wrong, once instead of on every card.
  const showFindings = widget.options?.show_findings === true
  const status = cardStatus(widget, data)
  const errorCode = String(data?.meta?.code ?? '')
  const errorText = disguise.free(failed ? (i18n.language.split('-')[0] === 'en' ? String(data?.error) : t(`errors.widget.${errorCode}`, { defaultValue: String(data?.error) })) : '')
  // ⚠️ data?.link comes from the service, not from the operator. A
  // javascript: address here would run as part of nexdeck.
  const link = safeUrl(widget.link || data?.link || widget.service_link) || undefined
  // Clocks and app tiles draw themselves without a header; the player's cover runs to the edge.
  const bare = ['app', 'clock', 'button', 'image', 'player', 'heading', 'tabs', 'group'].includes(widget.renderer)
  // A heading has no ground at all: it stands between the cards, not among them.
  const plain = widget.renderer === 'heading'
  // With a link, the whole card is the link; app tiles are anchors already.
  // ⚠️ Not the player: every gap between its buttons would open the media
  // server in a new tab, which is not what a miss next to "pause" should do.
  const clickable = Boolean(link) && !editing && widget.renderer !== 'app' && widget.renderer !== 'player'
  // The dot says what it means: the state in words, and the reason when the
  // service gives one (Nexview names its findings, for example).
  const urgent = Array.isArray(data?.meta?.urgent) ? (data?.meta?.urgent as unknown[]).map(String) : []
  const reasons = (showFindings || failed ? [errorText, data?.meta?.status_reason ? String(data.meta.status_reason) : '', ...urgent] : [errorText]).filter(Boolean).map((text) => tLabel(text))
  const statusTitle = [t(`status.${status}`), ...reasons].join(' · ')

  const open = (event: MouseEvent<HTMLElement>) => {
    if (!clickable || !link) return
    const target = event.target as HTMLElement
    if (target.closest(INTERACTIVE)) return
    if (window.getSelection()?.toString()) return
    window.open(link, '_blank', 'noopener,noreferrer')
  }

  const controls = (
    <>
      {onRefresh && !editing && (
        <button className="btn btn-icon h-6 w-6 btn-flat" onClick={onRefresh} aria-label={t('widget.refreshNow')} title={t('widget.refreshNow')}>
          <RefreshCw size={13} />
        </button>
      )}
      {link && !editing && (
        <a className="btn btn-icon h-6 w-6 btn-flat" href={link} target="_blank" rel="noopener noreferrer" aria-label={t('widget.openLink')} title={t('widget.openLink')}>
          <ExternalLink size={13} />
        </a>
      )}
      {editing && onArrange && (
        <button className="btn btn-icon h-6 w-6 btn-flat" onClick={(event) => onArrange(event.currentTarget.getBoundingClientRect())} aria-label={t('arrange.menu')} title={t('arrange.menu')} aria-haspopup="menu">
          <Ellipsis size={13} />
        </button>
      )}
      {editing && onSettings && (
        <button className="btn btn-icon h-6 w-6 btn-flat" onClick={onSettings} aria-label={t('widget.settings')} title={t('widget.settings')}>
          <Settings2 size={13} />
        </button>
      )}
      {editing && onRemove && (
        <button className="btn btn-icon h-6 w-6 btn-flat btn-danger" onClick={onRemove} aria-label={t('widget.remove.title')} title={t('widget.remove.title')}>
          <Trash2 size={13} />
        </button>
      )}
    </>
  )
  const showControls = editing ? Boolean(onSettings || onRemove || onArrange) : Boolean(onRefresh || link)

  return (
    <section
      className={`card glass ${plain ? 'card-plain' : ''} ${editing ? 'is-editing' : ''} ${clickable ? 'has-link' : ''} ${failed ? 'has-error' : ''}`}
      data-status={status}
      data-widget={widget.id}
      aria-label={widget.title || widget.kind}
      onClick={clickable ? open : undefined}
    >
      {!bare && (
        <header className="flex items-center gap-2 px-3 pt-2.5 pb-1 min-h-9">
          <ServiceIcon icon={widget.icon} size={18} />
          <h3 className="text-[13px] font-medium truncate flex-1 text-ink/90" title={disguise.free(widget.title)}>
            {disguise.free(widget.title)}
          </h3>
          {/* Why yellow or red, right on the card; the veil already says it for failures. */}
          {!failed && (status === 'warn' || status === 'bad') && reasons.length > 0 && (
            <span className={`hidden @min-[300px]:inline text-[10px] truncate max-w-[45%] ${status === 'bad' ? 'text-bad' : 'text-warn'}`} title={statusTitle}>
              {reasons[0]}
            </span>
          )}
          <span className="dot" data-status={status} role="img" aria-label={statusTitle} title={statusTitle} />
          {widget.beta && (
            <span className="chip !py-0 text-[10px] cursor-help hidden @min-[240px]:inline-flex" title={t('widget.betaHelp')}>
              beta
            </span>
          )}
        </header>
      )}
      {/* The controls float over the corner: always while editing, on hover otherwise. */}
      {showControls && <div className="card-controls glass">{controls}</div>}
      <div className={`flex-1 min-h-0 flex flex-col ${veiled ? 'nd-veiled' : ''}`} aria-hidden={veiled || undefined}>
        {renderWidget({ widget, data, series, canAct, canWrite, onAction, link, editing })}
      </div>
      {veiled && (
        <div className={`nd-veil ${bare ? 'inset-0' : 'inset-x-0 bottom-0 top-9'}`} data-testid="showcase-veil">
          {t('showcase.hidden')}
        </div>
      )}
      {/* The failure lies over the body: the layout underneath stays as it is, the
          last good values show through, and the red is impossible to miss. */}
      {failed && (
        <div className={`card-error ${bare ? 'inset-0' : 'inset-x-0 bottom-0 top-9'}`} title={String(data?.meta?.hint ?? '')} data-testid="card-error">
          <AlertTriangle size={22} className="text-bad flex-none" aria-hidden="true" />
          <p className="text-[12px] font-medium text-bad leading-snug line-clamp-3">{errorText}</p>
          {data?.meta?.stale_since ? <p className="text-[10px] text-muted">{t('card.staleData')}</p> : null}
        </div>
      )}
    </section>
  )
}

export function CardBody({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`flex-1 min-h-0 px-3 pb-3 ${className}`}>{children}</div>
}
