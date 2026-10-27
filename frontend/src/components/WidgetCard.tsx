import { AlertTriangle, Ellipsis, ExternalLink, RefreshCw, Settings2, Trash2, Wrench } from 'lucide-react'
import { lazy, Suspense, useEffect, useId, useRef, useState, type CSSProperties, type MouseEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { shownStyle, useLook } from '../lib/appearance'
import { colourKind, followPointer, lookOf, useLogoColour } from '../lib/cardLook'
import { cardStatus } from '../lib/cardStatus'
import { momentOf } from '../lib/chronicle'
import { maintenanceTarget } from '../lib/maintenance'
import { canRefract, refract } from '../lib/refraction'
import { safeUrl } from '../lib/safeUrl'
import { useDisguise } from '../lib/showcase'
import { useAuth } from '../stores/auth'

import { tLabel } from '../i18n/texts'
import type { Action, WidgetData, WidgetView } from '../lib/types'
import { renderWidget } from './renderers'
import { ForecastLine } from './ForecastLine'
import { ServiceIcon } from './ServiceIcon'
import { WhyLink } from './WhyLink'
import { subjectOf } from '../lib/diagnosis'

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

/** The maintenance dialog loads when an administrator opens it, not with every board. */
const MaintenanceDialog = lazy(() => import('./MaintenanceDialog').then((module) => ({ default: module.MaintenanceDialog })))

/** The frame every widget shares: header, floating controls, body, error strip. */
export function WidgetCard({ widget, data, series, editing, canAct, canWrite, onAction, onRefresh, onSettings, onRemove, onArrange }: Props) {
  const { t, i18n } = useTranslation()
  const disguise = useDisguise()
  // A camera, an embedded page and a note show the home itself, and nothing in
  // them can be told apart from the rest: in showcase mode they are blurred.
  const veiled = disguise.on && ['camera', 'iframe', 'text'].includes(widget.renderer)
  // A failed fetch is an error state of its own: red, with the server's reason.
  // The server names the reason by code; other languages translate the code,
  // English shows the server's own sentence with its specifics. A code without
  // a sentence of its own is translated by its wording, so a sentence with a
  // name in it (a missing scope, for one) keeps the name in every language.
  const failed = Boolean(data?.error)
  // With findings switched off, the card keeps its numbers and drops the alarm:
  // a Findings card next to it says what is wrong, once instead of on every card.
  const showFindings = widget.options?.show_findings === true
  const status = cardStatus(widget, data)
  const errorCode = String(data?.meta?.code ?? '')
  const errorText = disguise.free(failed ? (i18n.language.split('-')[0] === 'en' ? String(data?.error) : t(`errors.widget.${errorCode}`, { defaultValue: tLabel(String(data?.error)) })) : '')
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
  // What it hangs on that is down, first: that is the reason to look at (roadmap M5).
  if (data?.cause) reasons.unshift(t('dependencies.because', { name: data.cause }))
  // Since when, from the chronicle once nexdeck was restarted (roadmap M2).
  const since = (status === 'warn' || status === 'bad') && typeof data?.since === 'number' ? t('attention.since', { when: momentOf(data.since, i18n.language, t) }) : ''
  const statusTitle = [t(`status.${status}`), ...reasons, since].filter(Boolean).join(' · ')

  const open = (event: MouseEvent<HTMLElement>) => {
    if (!clickable || !link) return
    const target = event.target as HTMLElement
    if (target.closest(INTERACTIVE)) return
    if (window.getSelection()?.toString()) return
    window.open(link, '_blank', 'noopener,noreferrer')
  }

  // Maintenance: an administrator sets it from the card; everyone sees until when.
  const admin = useAuth((state) => state.user?.role === 'admin')
  const [maintaining, setMaintaining] = useState(false)
  const mayMaintain = admin && maintenanceTarget(widget) != null
  const away = widget.maintenance ?? null
  const awayLabel = away ? t('maintenance.chip', { time: new Date(away.until).toLocaleTimeString(i18n.language, { hour: '2-digit', minute: '2-digit' }) }) : ''
  const awayChip = away ? (
    mayMaintain ? (
      <button type="button" className="nd-away max-w-[50%]" onClick={() => setMaintaining(true)} title={awayLabel} aria-label={awayLabel} data-testid="card-maintenance">
        <Wrench size={10} aria-hidden="true" />
        {/* A narrow card keeps its title; the wrench alone says it, the words are in the tooltip. */}
        <span className="truncate hidden @min-[300px]:inline">{awayLabel}</span>
      </button>
    ) : (
      <span className="nd-away max-w-[50%]" title={awayLabel} aria-label={awayLabel} role="img" data-testid="card-maintenance">
        <Wrench size={10} aria-hidden="true" />
        <span className="truncate hidden @min-[300px]:inline">{awayLabel}</span>
      </span>
    )
  ) : null

  const controls = (
    <>
      {mayMaintain && !editing && !away && (
        <button className="btn btn-icon h-6 w-6 btn-flat" onClick={() => setMaintaining(true)} aria-label={t('maintenance.button')} title={t('maintenance.button')}>
          <Wrench size={13} />
        </button>
      )}
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
  const showControls = editing ? Boolean(onSettings || onRemove || onArrange) : Boolean(onRefresh || link || (mayMaintain && !away))

  // A colour of the card's own; a heading has one of its kind already.
  const logo = useLogoColour(widget.icon, !plain && colourKind(widget.options?.card_colour) === 'icon')
  // The attention card takes the colour of the worst it lists, unless it has one of its own.
  const tinted = widget.renderer === 'attention' && (status === 'bad' || status === 'warn') && colourKind(widget.options?.card_colour) === 'none'
    ? { ...widget.options, card_colour: status === 'bad' ? 'red' : 'yellow', card_effect: 'tint' }
    : widget.options
  const look = plain ? { className: '', style: {} } : lookOf(tinted, logo)
  const frame = useRef<HTMLElement>(null)
  const filterId = `nd-lg-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`
  const liquid = useLook((state) => shownStyle(state) === 'liquid' && state.refraction)
  useEffect(() => {
    const element = frame.current
    if (!liquid || plain || !element || !canRefract()) return
    const radius = parseFloat(getComputedStyle(element).borderTopLeftRadius) || 16
    return refract(element, filterId, radius)
  }, [liquid, plain, filterId])
  // The card tips towards the pointer: not while the board is arranged, not on
  // a touch screen, not when the account or the system asks for less motion.
  // Calm cards never move.
  const calm = useLook((state) => shownStyle(state) === 'calm')
  const tilts = useAuth((state) => state.user?.tilt !== false) && !editing && !plain && !calm
  const tiltsNow = useRef(tilts)
  useEffect(() => {
    tiltsNow.current = tilts
    // Arranging the board starts: a tipped card goes back to lying flat.
    if (!tilts && frame.current) {
      frame.current.classList.remove('is-tipping')
      frame.current.style.transform = ''
    }
  }, [tilts])
  useEffect(() => {
    const element = frame.current
    if (plain || !element) return
    return followPointer(element, () => tiltsNow.current)
  }, [plain])

  return (
    <>
    <section
      ref={frame}
      className={`card glass ${plain ? 'card-plain' : ''} ${editing ? 'is-editing' : ''} ${clickable ? 'has-link' : ''} ${failed ? 'has-error' : ''} ${look.className}`}
      style={look.style as CSSProperties}
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
          {!failed && (status === 'warn' || status === 'bad') && (reasons.length > 0 || since) && (
            <span className={`hidden @min-[300px]:inline text-[10px] truncate max-w-[45%] ${status === 'bad' ? 'text-bad' : 'text-warn'}`} title={statusTitle} data-testid="card-reason">
              {[reasons[0], since].filter(Boolean).join(' · ')}
            </span>
          )}
          {/* Roadmap M6: from the reason to the page that says why, for administrators. */}
          {!failed && (status === 'warn' || status === 'bad') ? <WhyLink subject={subjectOf(widget)} name={widget.title || widget.kind} className="hidden @min-[300px]:inline" /> : null}
          {awayChip}
          {/* In the head, beside the dot and the beta mark rather than over them. */}
          {showControls && <div className="card-controls in-head">{controls}</div>}
          <span className="dot" data-status={status} role="img" aria-label={statusTitle} title={statusTitle} />
          {widget.beta && (
            <span className="chip !py-0 text-[10px] cursor-help hidden @min-[240px]:inline-flex" title={t('widget.betaHelp')}>
              beta
            </span>
          )}
        </header>
      )}
      {/* A card without a head: the controls float over the corner, always while editing, on hover otherwise. */}
      {showControls && bare && <div className="card-controls glass">{controls}</div>}
      {bare && awayChip ? <div className="nd-away-corner">{awayChip}</div> : null}
      <div className={`flex-1 min-h-0 flex flex-col ${veiled ? 'nd-veiled' : ''}`} aria-hidden={veiled || undefined}>
        {renderWidget({ widget, data, series, canAct, canWrite, onAction, link, editing })}
        {!bare && !failed && data?.forecast ? <ForecastLine forecast={data.forecast} /> : null}
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
          {data?.cause ? <p className="text-[11px] text-ink/80" data-testid="card-cause">{t('dependencies.because', { name: data.cause })}</p> : null}
          <WhyLink subject={subjectOf(widget)} name={widget.title || widget.kind} />
          {data?.meta?.stale_since ? <p className="text-[10px] text-muted">{t('card.staleData')}</p> : null}
        </div>
      )}
    </section>
    {/* Beside the card, not in it: a click in the dialog must not reach the card's own link. */}
    {maintaining ? <Suspense fallback={null}><MaintenanceDialog widget={widget} open onClose={() => setMaintaining(false)} /></Suspense> : null}
    </>
  )
}

export function CardBody({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`flex-1 min-h-0 px-3 pb-3 ${className}`}>{children}</div>
}
