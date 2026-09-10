/**
 * The renderers: one small component per data shape. Every adapter maps its
 * service onto one of these, which keeps thirty integrations drawable with
 * fifteen components.
 *
 * Labels arrive from the adapters in English and are translated by wording
 * (``tLabel``); the renderers' own words are translation keys.
 */
import {
  Cloud,
  CloudDrizzle,
  CloudFog,
  CloudLightning,
  CloudRain,
  CloudSnow,
  CloudSun,
  Download,
  ExternalLink,
  Moon,
  Pause,
  Play,
  RotateCw,
  Search,
  Square,
  Sun,
  type LucideProps,
} from 'lucide-react'
import { useEffect, useMemo, useState, type ComponentType, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'

import { fileUrl, mediaUrl } from '../api/client'
import { tLabel } from '../i18n/texts'
import { formatValue, timeAgo } from '../lib/format'
import { safeUrl } from '../lib/safeUrl'
import type { Action, Saveable, Secondary, Status, WidgetData, WidgetView } from '../lib/types'
import { AskCard } from './AskCard'
import { ButtonCard } from './ButtonCard'
import { CameraCard } from './CameraCard'
import { ImageCard } from './ImageCard'
import { SearchCard } from './SearchCard'
import { WolCard } from './WolCard'
import { LucideByName, ServiceIcon } from './ServiceIcon'
import { Sparkline } from './Sparkline'

export interface RenderProps {
  widget: WidgetView
  data: WidgetData | undefined
  series?: Record<string, number[]>
  canAct?: boolean
  onAction?: (action: Action) => void
  link?: string
  editing?: boolean
}

const RENDERERS: Record<string, ComponentType<RenderProps>> = {
  value: ValueCard,
  gauge: GaugeCard,
  stats: StatsCard,
  list: ListCard,
  nowplaying: NowPlayingCard,
  calendar: CalendarCard,
  text: TextCard,
  bookmarks: BookmarksCard,
  iframe: IframeCard,
  clock: ClockCard,
  weather: WeatherCard,
  feed: FeedCard,
  log: LogCard,
  chart: ChartCard,
  bars: BarsCard,
  timeline: TimelineCard,
  ring: RingCard,
  app: AppTile,
  button: ButtonCard,
  image: ImageCard,
  posters: PostersCard,
  counters: CountersCard,
  camera: CameraCard,
  search: SearchCard,
  ask: AskCard,
  wol: WolCard,
}

export function renderWidget(props: RenderProps) {
  // A widget may ask for another drawing per option; the data says so.
  const name = typeof props.data?.meta?.renderer === 'string' ? props.data.meta.renderer : props.widget.renderer
  const Renderer = RENDERERS[name] ?? ValueCard
  return <Renderer {...props} />
}

// ---------------------------------------------------------------------------
// Shared pieces
// ---------------------------------------------------------------------------

/** A history line is worth drawing once it has a few points and moves at all. */
function worthDrawing(points: number[] | undefined): points is number[] {
  return Boolean(points && points.length >= 5 && new Set(points).size > 1)
}

/**
 * The row of small facts under a card's number.
 *
 * ⚠️ It used to wrap. On a narrow card that turned one line into three, the
 * card had no room left for its own number, and `min-h-0` let the content run
 * out of the top instead of being cut: on an iPhone the speedtest card had its
 * number, title and chips printed over each other, and Pi-hole read
 * "Queries 38," with the value sliced through. It scrolls sideways now, so a
 * card that is too narrow loses the last chip off the edge rather than its
 * own headline.
 */
function Chips({ items, series }: { items?: Secondary[]; series?: Record<string, number[]> }) {
  if (!items?.length) return null
  return (
    <div className="flex gap-1.5 overflow-x-auto scrollbar-none min-w-0 [&>*]:shrink-0">
      {items.slice(0, 4).map((item, index) => (
        <span className="chip" key={index}>
          {tLabel(item.label)}
          <b className="num">{formatValue(item.value, item.unit)}</b>
          {item.metric && worthDrawing(series?.[item.metric]) && (
            <span className="inline-block w-8 ml-1 -mb-0.5">
              <Sparkline values={series![item.metric]} height={10} fill={false} />
            </span>
          )}
        </span>
      ))}
    </div>
  )
}

function Empty({ children }: { children: ReactNode }) {
  return <div className="flex-1 flex items-center justify-center text-xs text-faint px-3 pb-3">{children}</div>
}

function ActionButtons({
  actions,
  onAction,
  canAct,
  compact,
}: {
  actions?: Action[] | Record<string, unknown>[]
  onAction?: RenderProps['onAction']
  canAct?: boolean
  compact?: boolean
}) {
  if (!actions?.length || !canAct || !onAction) return null
  const symbols: Record<string, ComponentType<LucideProps>> = { play: Play, square: Square, 'rotate-cw': RotateCw, pause: Pause, search: Search }
  return (
    <div className={`flex items-center gap-1 ${compact ? '' : 'mt-2'}`}>
      {(actions as Action[]).map((action) => {
        const Known = action.icon ? symbols[action.icon] : undefined
        const label = tLabel(action.label)
        return (
          <button
            key={action.id}
            className={`btn ${compact ? 'btn-icon h-6 w-6 border-0 bg-transparent' : 'h-7 px-2 text-xs'} ${action.danger ? 'btn-danger' : ''}`}
            onClick={(event) => {
              event.stopPropagation()
              onAction(action)
            }}
            aria-label={label}
            title={label}
          >
            {Known ? <Known size={13} /> : action.icon ? <LucideByName name={action.icon} size={13} /> : null}
            {!compact && <span>{label}</span>}
          </button>
        )
      })}
    </div>
  )
}

/**
 * The save link that sits beside a row's buttons.
 *
 * ⚠️ An anchor, not a button, and pointing at nexdeck rather than at the
 * service. Both matter: `download` is ignored across origins, so a link
 * straight to the service opens the video in a tab instead of saving it, and
 * on a homelab the browser usually cannot reach the service at all.
 */
function SaveLink({ widgetId, file }: { widgetId: number; file: Saveable }) {
  const { t } = useTranslation()
  const label = t('card.saveFile', { name: file.name })
  return (
    <a
      className="btn btn-icon h-6 w-6 border-0 bg-transparent"
      href={fileUrl(widgetId, file.path)}
      download={file.name}
      aria-label={label}
      title={label}
      onClick={(event) => event.stopPropagation()}
    >
      <Download size={13} />
    </a>
  )
}

function statusOf(value: unknown): Status {
  return value === 'ok' || value === 'warn' || value === 'bad' ? value : 'unknown'
}

// ---------------------------------------------------------------------------
// Value: one big number
// ---------------------------------------------------------------------------

export function ValueCard({ data, series, onAction, canAct }: RenderProps) {
  const { t } = useTranslation()
  const primary = data?.primary
  const metric = Object.keys(data?.metrics ?? {})[0]
  const points = metric ? series?.[metric] : undefined
  const hasFooter = Boolean(data?.secondary?.length || data?.actions?.length)
  return (
    <div className="flex-1 flex flex-col min-h-0 relative">
      {worthDrawing(points) && (
        <div className="absolute inset-x-0 bottom-0 h-[55%] opacity-60" title={t('card.history')} aria-hidden="true">
          <Sparkline values={points} height={60} className="!h-full" />
        </div>
      )}
      <div className="flex-1 flex flex-col justify-center px-3 min-h-0 relative">
        <div className="num text-[30px] leading-none font-semibold tracking-tight rise" key={String(primary?.value)}>
          {formatValue(primary?.value)}
          {primary?.unit && <span className="text-sm text-muted font-medium ml-1.5">{primary.unit}</span>}
        </div>
        {primary?.label && <div className="text-[11px] text-muted mt-1.5 uppercase tracking-wide">{tLabel(primary.label)}</div>}
      </div>
      {hasFooter && (
        <div className="px-3 pb-2.5 pt-1 flex items-end justify-between gap-2 relative">
          <Chips items={data?.secondary} series={series} />
          <ActionButtons actions={data?.actions} onAction={onAction} canAct={canAct} compact />
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Gauge: a dial, the way a rev counter looks
// ---------------------------------------------------------------------------

/** How far round the face a full dial goes. Not 360: it opens at the bottom. */
const SWEEP = 270

/** Where a point sits on an arc that opens downwards, 135° to 405°. */
function dialPoint(share: number, radius: number): [number, number] {
  const angle = ((135 + (share / 100) * SWEEP) * Math.PI) / 180
  return [50 + radius * Math.cos(angle), 50 + radius * Math.sin(angle)]
}

/** An SVG arc along the dial, from one share to another. */
function dialArc(from: number, to: number, radius: number): string {
  const [x1, y1] = dialPoint(from, radius)
  const [x2, y2] = dialPoint(to, radius)
  // ⚠️ Measured in degrees, not in share. The flag tells SVG which of the two
  // arcs between the points to draw, and it flips past a half turn, which on
  // a 270° face is two thirds of the way and not half. Reading it as half
  // sent every value between 50% and 67% the long way round the dial.
  const large = ((to - from) / 100) * SWEEP > 180 ? 1 : 0
  return `M ${x1} ${y1} A ${radius} ${radius} 0 ${large} 1 ${x2} ${y2}`
}

export function GaugeCard({ data }: RenderProps) {
  const { t } = useTranslation()
  const primary = data?.primary
  const dial = (data?.meta?.gauge ?? null) as { share?: number; max?: number } | null
  // ⚠️ Two kinds of card end up here. One was turned into a dial by the
  // collector and carries its share in `meta`; the other measures a
  // percentage to begin with, and then the number *is* the share.
  const share = Math.max(
    0,
    Math.min(100, typeof dial?.share === 'number' ? dial.share : primary?.unit === '%' && typeof primary?.value === 'number' ? primary.value : 0),
  )
  const colour = data?.status === 'bad' ? 'var(--nd-bad)' : data?.status === 'warn' ? 'var(--nd-warn)' : 'var(--nd-accent)'
  const [tipX, tipY] = dialPoint(share, 30)
  // Only where it adds something. A card that already measures a share
  // would read "18% of 100%", which is a sentence about nothing.
  const ceiling = typeof dial?.max === 'number' ? dial.max : null

  return (
    <div className="flex-1 flex items-center gap-3 px-4 pb-3 min-h-0">
      <svg viewBox="0 0 100 82" className="w-[104px] h-[86px] flex-none" aria-hidden="true">
        <path d={dialArc(0, 100, 38)} fill="none" stroke="color-mix(in srgb, var(--nd-text) 10%, transparent)" strokeWidth="9" strokeLinecap="round" />
        {share > 0 && (
          <path
            d={dialArc(0, share, 38)}
            fill="none"
            stroke={colour}
            strokeWidth="9"
            strokeLinecap="round"
            style={{ transition: 'd 600ms cubic-bezier(.2,.7,.2,1)' }}
          />
        )}
        {/* The ticks are the quarters, so a glance says roughly where it sits. */}
        {[0, 25, 50, 75, 100].map((at) => {
          const [ix, iy] = dialPoint(at, 30)
          const [ox, oy] = dialPoint(at, 25.5)
          return <line key={at} x1={ix} y1={iy} x2={ox} y2={oy} stroke="color-mix(in srgb, var(--nd-text) 18%, transparent)" strokeWidth="1.5" strokeLinecap="round" />
        })}
        <line
          x1="50"
          y1="50"
          x2={tipX}
          y2={tipY}
          stroke="var(--nd-text)"
          strokeWidth="2.5"
          strokeLinecap="round"
          style={{ transition: 'x2 600ms cubic-bezier(.2,.7,.2,1), y2 600ms cubic-bezier(.2,.7,.2,1)' }}
        />
        <circle cx="50" cy="50" r="4" fill="var(--nd-bg-elev)" stroke="var(--nd-text)" strokeWidth="2.5" />
      </svg>
      <div className="min-w-0 flex-1">
        <div className="text-[11px] text-muted uppercase tracking-wide truncate">{tLabel(primary?.label)}</div>
        <div className="num text-[19px] font-semibold leading-tight mt-0.5 truncate">{formatValue(primary?.value, primary?.unit)}</div>
        {ceiling !== null && (
          <div className="text-[10px] text-muted num">
            {t('gauge.of')} {formatValue(ceiling, primary?.unit)}
          </div>
        )}
        <div className="mt-1.5">
          <Chips items={data?.secondary} />
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Stats: several metrics with bars and sparklines
// ---------------------------------------------------------------------------

export function StatsCard({ data, series }: RenderProps) {
  const rows: Secondary[] = []
  if (data?.primary) rows.push({ label: data.primary.label ?? '', value: data.primary.value, unit: data.primary.unit, metric: Object.keys(data.metrics ?? {})[0] })
  rows.push(...(data?.secondary ?? []))
  return (
    <div className="flex-1 flex flex-col px-3 pb-2.5 min-h-0 scroll">
      <div className="my-auto flex flex-col gap-1.5">
        {rows.map((row, index) => {
          const numeric = typeof row.value === 'number' ? row.value : null
          const isPercent = row.unit === '%'
          const points = row.metric ? series?.[row.metric] : undefined
          return (
            <div key={index} className="grid grid-cols-[auto_1fr_auto] items-center gap-x-3">
              {/* Labels grow with the language, values never wrap: "WAN eingehend" and "95.8 MB/s" must both fit. */}
              <div className="text-[11px] text-muted min-w-[4.6rem] max-w-[10rem] truncate" title={tLabel(row.label)}>
                {tLabel(row.label)}
              </div>
              <div className="min-w-0">
                {worthDrawing(points) ? (
                  <Sparkline values={points} height={16} min={isPercent ? 0 : undefined} max={isPercent ? 100 : undefined} />
                ) : isPercent && numeric !== null ? (
                  <div className="bar" data-status={numeric >= 90 ? 'bad' : numeric >= 75 ? 'warn' : 'ok'}>
                    <i style={{ width: `${Math.min(100, numeric)}%` }} />
                  </div>
                ) : (
                  <div className="bar">
                    <i style={{ width: 0 }} />
                  </div>
                )}
              </div>
              <div className="num text-[13px] font-semibold text-right whitespace-nowrap min-w-[3.5rem]">{formatValue(row.value, row.unit)}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// List: rows with status, value, optional progress and actions
// ---------------------------------------------------------------------------

export function ListCard({ widget, data, onAction, canAct, series }: RenderProps) {
  const { t, i18n } = useTranslation()
  const items = data?.items ?? []
  if (!items.length && !data?.error) return <Empty>{data?.meta?.empty ? tLabel(String(data.meta.empty)) : t('card.nothing')}</Empty>
  // A row that carries an error code is translated by the code; other subtitles by wording.
  const subtitleOf = (item: Record<string, unknown>): string => {
    const text = String(item.subtitle ?? '')
    if (item.error_code && i18n.language.split('-')[0] !== 'en') return t(`errors.widget.${String(item.error_code)}`, { defaultValue: text })
    return tLabel(text)
  }
  return (
    <div className="flex-1 min-h-0 flex flex-col">
      {data?.meta?.notice ? (
        // One sentence about the card as a whole, above its rows: why a list
        // has no buttons, for instance. Without it the buttons are simply
        // missing and nobody can tell whether that is a fault.
        <div className="mx-3 mb-1.5 text-[11px] text-muted border-l-2 border-[var(--nd-warn,theme(colors.amber.400))] pl-2">{tLabel(String(data.meta.notice))}</div>
      ) : null}
      <ul className="flex-1 min-h-0 scroll px-1.5 pb-1">
        {items.map((item, index) => {
          const status = statusOf(item.status)
          const progress = typeof item.progress === 'number' ? item.progress : null
          const memory = typeof item.memory_percent === 'number' ? item.memory_percent : null
          return (
            <li key={String(item.id ?? index)} className="group/row flex items-center gap-2.5 px-1.5 py-1.5 rounded-lg hover:bg-surface-hover">
              {item.art ? (
                // A cover beside the row, for lists of titles: requests,
                // recently added. Small, and the dot moves onto its corner so
                // the row still says how it stands.
                <span className="relative shrink-0 w-8 aspect-[2/3] rounded overflow-hidden bg-surface-hover">
                  <img src={mediaUrl(widget.id, String(item.art))} alt="" loading="lazy" className="absolute inset-0 w-full h-full object-cover" />
                  <span className="dot absolute -right-0.5 -bottom-0.5 ring-2 ring-[var(--nd-card)]" data-status={status} />
                </span>
              ) : item.icon ? <ServiceIcon icon={String(item.icon)} size={18} /> : <span className="dot" data-status={status} />}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-medium truncate">{String(item.title ?? '')}</span>
                  {typeof item.cpu === 'number' && <span className="num text-[10px] text-muted">{item.cpu.toFixed(0)}%</span>}
                </div>
                {item.subtitle ? <div className="text-[11px] text-muted truncate">{subtitleOf(item)}</div> : null}
                {progress !== null && (
                  <div className="bar mt-1" data-status={status}>
                    <i style={{ width: `${progress}%` }} />
                  </div>
                )}
                {memory !== null && progress === null && (
                  <div className="bar mt-1" data-status={memory > 90 ? 'bad' : 'ok'}>
                    <i style={{ width: `${memory}%`, background: 'color-mix(in srgb, var(--nd-accent) 55%, transparent)' }} />
                  </div>
                )}
              </div>
              {(item.file || (item.actions && canAct)) ? (
                // ⚠️ Hidden until hovered, on most lists: a restart button on
                // every container row would be noise. A card whose rows exist
                // to be pressed says so with `actions_visible`, because on a
                // wall with a touchscreen there is no hovering and the buttons
                // would never be seen at all.
                <span className={`flex items-center gap-1 ${data?.meta?.actions_visible ? '' : 'opacity-0 group-hover/row:opacity-100 transition-opacity'}`}>
                  {/* Saving is not acting on the service, so it stays for a
                      viewer who may only look. */}
                  {item.file ? <SaveLink widgetId={widget.id} file={item.file as Saveable} /> : null}
                  <ActionButtons actions={item.actions as Action[]} onAction={onAction} canAct={canAct} compact />
                </span>
              ) : null}
              {item.value !== undefined && item.value !== '' && <span className="num text-xs text-muted whitespace-nowrap">{String(item.value)}</span>}
              {item.url ? (
                <a href={safeUrl(item.url)} target="_blank" rel="noopener noreferrer" className="text-faint hover:text-accent" aria-label={t('card.open')}>
                  <ExternalLink size={12} />
                </a>
              ) : null}
            </li>
          )
        })}
      </ul>
      {data?.secondary?.length || data?.actions?.length ? (
        <div className="px-3 pb-2.5 pt-1 flex items-center justify-between gap-2 border-t border-line">
          <Chips items={data?.secondary} series={series} />
          <ActionButtons actions={data?.actions} onAction={onAction} canAct={canAct} compact />
        </div>
      ) : null}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Now playing: media streams
// ---------------------------------------------------------------------------

export function NowPlayingCard({ widget, data }: RenderProps) {
  const { t } = useTranslation()
  const items = data?.items ?? []
  if (!items.length) return <Empty>{t('card.nothingPlaying')}</Empty>
  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <ul className="flex-1 min-h-0 scroll px-3 pb-2 space-y-2">
        {items.map((item, index) => {
          const progress = typeof item.progress === 'number' ? item.progress : 0
          const paused = item.state === 'paused'
          return (
            <li key={index} className="flex gap-3 items-center">
              <div
                className="w-10 h-14 rounded-md flex-none overflow-hidden bg-gradient-to-br from-accent/40 to-indigo-500/40 flex items-center justify-center text-[10px] font-semibold text-white/80"
                style={item.art ? { backgroundImage: `url(${mediaUrl(widget.id, String(item.art))})`, backgroundSize: 'cover' } : undefined}
              >
                {!item.art && String(item.title ?? '?').slice(0, 2).toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-[13px] font-medium truncate">{String(item.title ?? '')}</div>
                <div className="text-[11px] text-muted truncate">{tLabel(String(item.subtitle ?? ''))}</div>
                <div className="flex items-center gap-2 mt-1.5">
                  {paused ? <Pause size={11} className="text-warn flex-none" /> : <Play size={11} className="text-ok flex-none" />}
                  <div className="bar flex-1">
                    <i style={{ width: `${progress}%` }} />
                  </div>
                  <span className="num text-[10px] text-muted">{String(item.remaining ?? '')}</span>
                </div>
              </div>
            </li>
          )
        })}
      </ul>
      <div className="px-3 pb-2.5 pt-1 border-t border-line">
        <Chips items={data?.secondary} />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Counters: a row of icons, each with its number
// ---------------------------------------------------------------------------

export function CountersCard({ data }: RenderProps) {
  const items = data?.items ?? []
  return (
    <div className="flex-1 flex items-center justify-around gap-3 px-4 pb-4 min-h-0" data-testid="counters">
      {items.map((item, index) => (
        <div key={index} className="flex flex-col items-center gap-2.5 min-w-0">
          <ServiceIcon icon={String(item.icon ?? 'lucide:box')} size={26} className="text-accent" />
          <div className="num text-2xl font-semibold leading-none">{formatValue(item.value as number | string | null | undefined)}</div>
          <div className="text-[10px] uppercase tracking-wider text-muted truncate max-w-full">{tLabel(String(item.label ?? ''))}</div>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Posters: covers in a grid, newest first
// ---------------------------------------------------------------------------

export function PostersCard({ widget, data }: RenderProps) {
  const { t } = useTranslation()
  const items = data?.items ?? []
  if (!items.length) return <Empty>{data?.meta?.empty ? tLabel(String(data.meta.empty)) : t('card.nothing')}</Empty>
  return (
    <ul className="flex-1 min-h-0 scroll px-3 pb-3 grid gap-2 content-start" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(84px, 1fr))' }} data-testid="posters">
      {items.map((item, index) => {
        const art = mediaUrl(widget.id, item.art as string | undefined)
        return (
          <li key={String(item.id ?? index)} className="relative aspect-[2/3] rounded-lg overflow-hidden bg-gradient-to-br from-accent/30 to-indigo-500/30" title={`${String(item.title ?? '')}${item.subtitle ? ` · ${String(item.subtitle)}` : ''}`}>
            {art ? <img src={art} alt="" loading="lazy" className="absolute inset-0 w-full h-full object-cover" /> : <span className="absolute inset-0 flex items-center justify-center text-lg font-semibold text-white/70">{String(item.title ?? '?').slice(0, 2).toUpperCase()}</span>}
            <div className="absolute inset-x-0 bottom-0 px-1.5 pt-6 pb-1.5 bg-gradient-to-t from-black/85 via-black/50 to-transparent">
              <div className="text-[11px] font-medium leading-tight text-white line-clamp-2">{String(item.title ?? '')}</div>
              {item.subtitle ? <div className="text-[10px] text-white/70 truncate">{tLabel(String(item.subtitle))}</div> : null}
            </div>
          </li>
        )
      })}
    </ul>
  )
}

// ---------------------------------------------------------------------------
// Calendar: upcoming items grouped by day
// ---------------------------------------------------------------------------

export function CalendarCard({ data }: RenderProps) {
  const { t } = useTranslation()
  const items = data?.items ?? []
  if (!items.length) return <Empty>{t('card.nothingUpcoming')}</Empty>
  const groups = new Map<string, Record<string, unknown>[]>()
  for (const item of items) {
    const key = String(item.date ?? '')
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(item)
  }
  return (
    <ul className="flex-1 min-h-0 scroll px-3 pb-2">
      {[...groups.entries()].map(([date, entries]) => (
        <li key={date} className="py-1">
          <div className="text-[10px] uppercase tracking-wide text-faint mb-1">{dayLabel(date, t)}</div>
          {entries.map((entry, index) => (
            <div key={index} className="flex items-center gap-2 py-1">
              <span className="dot" data-status={statusOf(entry.status)} />
              <span className="text-[13px] font-medium truncate flex-1">{String(entry.title ?? '')}</span>
              <span className="text-[11px] text-muted truncate max-w-[45%]">{tLabel(String(entry.subtitle ?? ''))}</span>
            </div>
          ))}
        </li>
      ))}
    </ul>
  )
}

function dayLabel(date: string, t: TFunction): string {
  const today = new Date()
  const target = new Date(date + 'T00:00:00')
  const diff = Math.round((target.getTime() - new Date(today.toDateString()).getTime()) / 86400000)
  if (diff === 0) return t('card.today')
  if (diff === 1) return t('card.tomorrow')
  if (Number.isNaN(diff)) return date
  return target.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'short' })
}

// ---------------------------------------------------------------------------
// Text: markdown
// ---------------------------------------------------------------------------

/**
 * ⚠️ marked and DOMPurify are fetched when a note card is first drawn, not
 * with the app. Together they are a sizeable part of the first load, and they
 * are needed by exactly one of the 196 cards. Until then the card shows its
 * source as plain text, which is readable markdown anyway.
 *
 * The sanitiser is not optional and never becomes optional: the note is
 * written by a member and drawn as HTML in the operator's own origin. If the
 * import fails, the card falls back to text, never to unsanitised HTML.
 */
let render: ((source: string) => string) | null = null
let loading: Promise<void> | null = null

function loadMarkdown(): Promise<void> {
  loading ??= Promise.all([import('marked'), import('dompurify')]).then(([{ marked }, purify]) => {
    const clean = purify.default
    render = (source: string) => clean.sanitize(marked.parse(source, { async: false }) as string, { ADD_ATTR: ['target'] })
  })
  return loading
}

export function TextCard({ data }: RenderProps) {
  const source = String(data?.meta?.markdown ?? '')
  const [ready, setReady] = useState(render !== null)
  useEffect(() => {
    if (render !== null) return
    let alive = true
    void loadMarkdown().then(() => {
      if (alive) setReady(true)
    })
    return () => {
      alive = false
    }
  }, [])
  const html = useMemo(() => (ready && render ? render(source) : ''), [source, ready])
  if (!ready || !render) {
    return <div className="flex-1 min-h-0 scroll px-3 pb-3 text-[13px] whitespace-pre-wrap">{source}</div>
  }
  return <div className="prose-card flex-1 min-h-0 scroll px-3 pb-3 text-[13px]" dangerouslySetInnerHTML={{ __html: html }} />
}

// ---------------------------------------------------------------------------
// Bookmarks
// ---------------------------------------------------------------------------

export function BookmarksCard({ data }: RenderProps) {
  const { t } = useTranslation()
  const items = data?.items ?? []
  const grid = data?.meta?.layout === 'grid'
  if (!items.length) return <Empty>{t('card.noLinks')}</Empty>
  return (
    <ul className={`flex-1 min-h-0 scroll px-2 pb-2 ${grid ? 'grid grid-cols-3 gap-1 content-start' : ''}`}>
      {items.map((item, index) => (
        <li key={index}>
          <a
            href={safeUrl(item.url) || '#'}
            target="_blank"
            rel="noreferrer"
            className={`flex items-center gap-2.5 rounded-lg hover:bg-surface-hover ${grid ? 'flex-col justify-center text-center p-2' : 'px-2 py-1.5'}`}
          >
            <ServiceIcon icon={String(item.icon || 'lucide:link')} size={grid ? 24 : 18} />
            <span className="text-[13px] truncate">{String(item.title ?? '')}</span>
          </a>
        </li>
      ))}
    </ul>
  )
}

// ---------------------------------------------------------------------------
// Iframe
// ---------------------------------------------------------------------------

/** Does this address point back at nexdeck itself? */
function framesOurselves(url: string): boolean {
  try {
    return new URL(url, window.location.href).origin === window.location.origin
  } catch {
    return true
  }
}

export function IframeCard({ data, editing }: RenderProps) {
  const { t } = useTranslation()
  const url = String(data?.meta?.url ?? '')
  if (!url) return <Empty>{t('card.noUrl')}</Empty>
  // The sandbox keeps a foreign page at arm's length, but it cannot keep out a
  // page from our own address: with allow-scripts and allow-same-origin
  // together a same-origin frame reaches the app around it and can take its
  // own sandbox off. allow-same-origin has to stay, or half the services out
  // there stop working inside a frame, so the address is what gets refused.
  if (framesOurselves(url)) return <Empty>{t('card.noSelfFrame')}</Empty>
  return (
    <div className="flex-1 min-h-0 relative">
      <iframe src={url} title={t('card.embedded')} className="absolute inset-0 w-full h-full border-0 rounded-b-[var(--nd-radius)] bg-white" sandbox="allow-scripts allow-same-origin allow-forms allow-popups" loading="lazy" />
      {editing && <div className="absolute inset-0" />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Clock
// ---------------------------------------------------------------------------

/** Hours, minutes and seconds in the clock's own zone, as fractions of a turn.
 *
 *  ⚠️ Read out of the formatted parts, not off the Date. A Date carries the
 *  browser's zone, and a clock set to another zone would draw one time and
 *  print another underneath it. */
export function handsFor(now: Date, timeZone?: string): { hour: number; minute: number; second: number } {
  let parts: Intl.DateTimeFormatPart[]
  try {
    parts = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false, timeZone }).formatToParts(now)
  } catch {
    parts = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).formatToParts(now)
  }
  const read = (what: string) => Number(parts.find((part) => part.type === what)?.value ?? 0)
  // 24 becomes 0: en-GB with hour12 false writes midnight as 24.
  const hour = read('hour') % 12
  const minute = read('minute')
  const second = read('second')
  return {
    hour: ((hour + minute / 60) / 12) * 360,
    minute: ((minute + second / 60) / 60) * 360,
    second: (second / 60) * 360,
  }
}

/** The face with hands. Drawn, not fetched: one SVG, no library. */
function Dial({ now, timeZone, seconds, colour }: { now: Date; timeZone?: string; seconds: boolean; colour?: string }) {
  const turn = handsFor(now, timeZone)
  const ink = colour || 'var(--nd-text)'
  return (
    <svg viewBox="0 0 100 100" className="w-full h-full max-h-full" role="img" aria-label={new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', timeZone }).format(now)}>
      <circle cx="50" cy="50" r="47" fill="none" stroke="var(--nd-border-strong)" strokeWidth="1.5" />
      {/* Twelve marks, the quarters longer. A dial without marks is a circle. */}
      {Array.from({ length: 12 }, (_, index) => {
        const long = index % 3 === 0
        return (
          <line
            key={index}
            x1="50"
            y1={long ? 8 : 10}
            x2="50"
            y2={long ? 16 : 13}
            stroke={long ? ink : 'var(--nd-text-muted)'}
            strokeWidth={long ? 2.4 : 1.2}
            strokeLinecap="round"
            transform={`rotate(${index * 30} 50 50)`}
            opacity={long ? 0.9 : 0.45}
          />
        )
      })}
      <line x1="50" y1="50" x2="50" y2="27" stroke={ink} strokeWidth="4.4" strokeLinecap="round" transform={`rotate(${turn.hour} 50 50)`} />
      <line x1="50" y1="50" x2="50" y2="16" stroke={ink} strokeWidth="2.8" strokeLinecap="round" transform={`rotate(${turn.minute} 50 50)`} />
      {seconds && (
        <line x1="50" y1="57" x2="50" y2="13" stroke="var(--nd-accent)" strokeWidth="1.2" strokeLinecap="round" transform={`rotate(${turn.second} 50 50)`} />
      )}
      <circle cx="50" cy="50" r="2.6" fill={ink} />
    </svg>
  )
}

export function ClockCard({ data }: RenderProps) {
  const [now, setNow] = useState(() => new Date())
  const seconds = Boolean(data?.meta?.seconds)
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), seconds ? 1000 : 10000)
    return () => window.clearInterval(id)
  }, [seconds])
  const timeZone = (data?.meta?.timezone as string) || undefined
  const hour12 = data?.meta?.format === '12h'
  const hands = data?.meta?.face === 'hands'
  const colour = typeof data?.meta?.colour === 'string' && data.meta.colour ? data.meta.colour : undefined
  let time: string
  let date = ''
  try {
    time = now.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: seconds ? '2-digit' : undefined, hour12, timeZone })
    date = now.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long', timeZone })
  } catch {
    time = now.toLocaleTimeString()
  }
  const under = (
    <>
      {data?.meta?.date !== false && <div className="text-xs text-muted mt-2">{date}</div>}
      {data?.meta?.label ? <div className="text-[11px] text-faint mt-0.5 uppercase tracking-wide">{String(data.meta.label)}</div> : null}
    </>
  )
  if (hands) {
    return (
      <div className="flex-1 min-h-0 flex flex-col items-center justify-center gap-1 px-3 py-2">
        <div className="min-h-0 flex-1 aspect-square grid place-items-center">
          <Dial now={now} timeZone={timeZone} seconds={seconds} colour={colour} />
        </div>
        <div className="text-center leading-tight">{under}</div>
      </div>
    )
  }
  return (
    <div className="flex-1 flex flex-col justify-center px-4 py-3 min-h-0">
      <div className="num text-[40px] leading-none font-semibold tracking-tight" style={colour ? { color: colour } : undefined}>
        {time}
      </div>
      {under}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Weather
// ---------------------------------------------------------------------------

const CONDITION_ICONS: Record<string, ComponentType<LucideProps>> = {
  clear: Sun,
  'mostly-clear': CloudSun,
  'partly-cloudy': CloudSun,
  overcast: Cloud,
  fog: CloudFog,
  drizzle: CloudDrizzle,
  rain: CloudRain,
  showers: CloudRain,
  snow: CloudSnow,
  thunderstorm: CloudLightning,
}

export function WeatherCard({ data }: RenderProps) {
  const condition = String(data?.meta?.condition ?? 'overcast')
  const night = data?.meta?.is_day === false
  const Icon = night && condition === 'clear' ? Moon : (CONDITION_ICONS[condition] ?? Cloud)
  const days = data?.items ?? []
  return (
    <div className="flex-1 flex flex-col px-3 pb-2 min-h-0">
      <div className="flex items-center gap-3 my-auto">
        <Icon size={36} className="text-accent flex-none" strokeWidth={1.5} />
        <div className="min-w-0">
          <div className="num text-[28px] leading-none font-semibold">
            {formatValue(data?.primary?.value)}
            <span className="text-sm text-muted ml-1">{data?.primary?.unit}</span>
          </div>
          <div className="text-[11px] text-muted mt-1 capitalize truncate">
            {condition.replace('-', ' ')}
            {data?.primary?.label ? ` · ${tLabel(data.primary.label)}` : ''}
          </div>
        </div>
        <div className="ml-auto hidden lg:block">
          <Chips items={data?.secondary?.slice(0, 2)} />
        </div>
      </div>
      {days.length > 0 && (
        <div className="grid grid-flow-col auto-cols-fr gap-1 text-center leading-tight">
          {days.slice(0, 5).map((day, index) => {
            const DayIcon = CONDITION_ICONS[String(day.condition)] ?? Cloud
            return (
              <div key={index} className="text-[10px] text-muted flex flex-col items-center gap-0.5">
                <span>{new Date(String(day.date) + 'T00:00:00').toLocaleDateString(undefined, { weekday: 'short' })}</span>
                <DayIcon size={14} className="text-ink/80" />
                <span className="num whitespace-nowrap">
                  <span className="text-ink">{Math.round(Number(day.high))}°</span> {Math.round(Number(day.low))}°
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Feed
// ---------------------------------------------------------------------------

export function FeedCard({ data }: RenderProps) {
  const { t } = useTranslation()
  const items = data?.items ?? []
  if (!items.length) return <Empty>{t('card.noEntries')}</Empty>
  const cards = data?.meta?.style === 'cards'
  return (
    <ul className={`flex-1 min-h-0 scroll px-2 pb-2 ${cards ? 'grid grid-cols-2 gap-2 content-start' : ''}`}>
      {items.map((item, index) => (
        <li key={index}>
          <a href={safeUrl(item.url) || '#'} target="_blank" rel="noopener noreferrer" className={`block rounded-lg hover:bg-surface-hover ${cards ? 'p-2' : 'px-2 py-1.5'}`}>
            {cards && item.image ? <div className="aspect-video rounded-md bg-cover bg-center mb-2" style={{ backgroundImage: `url(${item.image})` }} /> : null}
            <div className="text-[13px] font-medium leading-snug line-clamp-2">{String(item.title ?? '')}</div>
            <div className="text-[11px] text-faint mt-0.5 truncate">
              {String(item.source ?? '')}
              {item.published ? ` · ${timeAgo(Number(item.published))}` : ''}
            </div>
          </a>
        </li>
      ))}
    </ul>
  )
}

// ---------------------------------------------------------------------------
// Log
// ---------------------------------------------------------------------------

export function LogCard({ data }: RenderProps) {
  const { t } = useTranslation()
  const lines = (data?.meta?.lines_preview as string[] | undefined) ?? []
  return (
    <pre className="flex-1 min-h-0 scroll px-3 pb-3 m-0 font-mono text-[11px] leading-[1.5] text-muted whitespace-pre-wrap">
      {lines.length ? (
        lines.map((line, index) => (
          <div key={index} className={/error|fatal/i.test(line) ? 'text-bad' : /warn/i.test(line) ? 'text-warn' : ''}>
            {line}
          </div>
        ))
      ) : (
        <span className="text-faint">{t('card.waitingLog')}</span>
      )}
    </pre>
  )
}

// ---------------------------------------------------------------------------
// Chart: a larger series with min, max and current
// ---------------------------------------------------------------------------

/**
 * ⚠️ Every metric the card records, not the first one.
 *
 * This took `Object.keys(data.metrics)[0]` and threw the rest away. UniFi's
 * console card measures `wan_down` and `wan_up`, the server stores both, and
 * the card drew one: to compare them you put two cards side by side, and then
 * they had different scales, so the comparison was wrong as well as awkward.
 * All the lines share one scale here, which is the whole point of drawing
 * them together.
 */
export function ChartCard({ data, series }: RenderProps) {
  const { t } = useTranslation()
  const lines = Object.keys(data?.metrics ?? {})
    .map((metric) => ({ metric, points: series?.[metric] ?? [] }))
    .filter((line) => line.points.length > 1)
  const all = lines.flatMap((line) => line.points)
  const low = all.length ? Math.min(...all) : 0
  const high = all.length ? Math.max(...all) : 0
  const current = data?.primary?.value
  const unit = data?.primary?.unit ?? ''
  //: A label for each line. The metric name is the fallback, not the choice:
  //: "wan_down" is a column name, "WAN in" is what the card already calls it.
  const labelFor = (metric: string): string => {
    if (data?.primary?.metric === metric) return tLabel(data.primary.label)
    const row = data?.secondary?.find((one) => one.metric === metric)
    return row ? tLabel(row.label) : metric
  }
  return (
    <div className="flex-1 flex flex-col min-h-0 px-3 pb-3">
      <div className="flex items-baseline gap-2">
        <span className="num text-2xl font-semibold">{formatValue(current, unit)}</span>
        <span className="text-[11px] text-muted truncate">{tLabel(data?.primary?.label)}</span>
        {all.length > 1 && (
          <span className="ml-auto num text-[10px] text-faint whitespace-nowrap">
            {t('card.min')} {formatValue(low)} · {t('card.max')} {formatValue(high)}
          </span>
        )}
      </div>
      <div className="relative flex-1 min-h-[36px] mt-1" title={t('card.history')}>
        {lines.length ? (
          lines.map((line, index) => (
            <span key={line.metric} className={index ? 'absolute inset-0' : 'block'}>
              <Sparkline
                values={line.points}
                height={64}
                min={low}
                max={high}
                fill={lines.length === 1}
                color={SLICE_COLOURS[index % SLICE_COLOURS.length]}
              />
            </span>
          ))
        ) : (
          <Empty>{t('card.collecting')}</Empty>
        )}
      </div>
      {lines.length > 1 && (
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1">
          {lines.map((line, index) => (
            <span key={line.metric} className="flex items-center gap-1.5 text-[10px] text-muted">
              <span
                className="rounded-full"
                style={{ width: 7, height: 7, background: SLICE_COLOURS[index % SLICE_COLOURS.length] }}
              />
              {labelFor(line.metric)}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Timeline: a history the card brought with it
// ---------------------------------------------------------------------------

interface Line {
  key: string
  label: string
  /** [seconds since the epoch, value]; a null value is a gap. */
  points: [number, number | null][]
}

/**
 * A history over real time, drawn as a line or as bars.
 *
 * ⚠️ Not the same thing as ChartCard. That one draws what nexdeck collected,
 * which stops after 24 hours because that is how long the minute rows are
 * kept. This draws what the service handed over, which can be months, and the
 * points carry their own timestamps rather than being evenly spaced.
 */
export function TimelineCard({ data }: RenderProps) {
  const { t, i18n } = useTranslation()
  const meta = (data?.meta ?? {}) as { shape?: string; unit?: string; lines?: Line[] }
  const lines = (meta.lines ?? []).filter((line) => line.points?.length)
  const values = lines.flatMap((line) => line.points.map(([, v]) => v)).filter((v): v is number => v !== null)
  if (!lines.length || !values.length) {
    return <Empty>{tLabel(String(data?.meta?.empty ?? '')) || t('card.nothing')}</Empty>
  }
  const times = lines.flatMap((line) => line.points.map(([at]) => at))
  const first = Math.min(...times)
  const last = Math.max(...times)
  const span = last - first || 1
  // ⚠️ From nought, not from the lowest reading. A line that starts at its own
  // minimum turns a 5% dip into a cliff, and this card exists to answer "is my
  // connection holding up", which is a question about the distance to zero.
  const top = Math.max(...values) * 1.08 || 1
  const W = 100
  const H = 46
  const at = (time: number) => ((time - first) / span) * W
  const up = (value: number) => H - (value / top) * H
  const bars = meta.shape === 'bars'
  const width = bars ? Math.max(0.6, (W / Math.max(1, lines[0].points.length)) * (lines.length > 1 ? 0.38 : 0.8)) : 0
  const when = (seconds: number) =>
    new Date(seconds * 1000).toLocaleDateString(i18n.language, { day: 'numeric', month: 'short' })

  return (
    <div className="flex-1 flex flex-col min-h-0 px-3 pb-2.5">
      <div className="flex items-baseline gap-2">
        <span className="num text-2xl font-semibold">{formatValue(data?.primary?.value, data?.primary?.unit ?? '')}</span>
        {/* Named once. With several lines the legend below carries the names,
            and repeating the first one up here made the card say "Download"
            twice with nothing to tell the two apart. */}
        {lines.length === 1 && <span className="text-[11px] text-muted truncate">{tLabel(data?.primary?.label)}</span>}
        <span className="ml-auto num text-[10px] text-faint whitespace-nowrap">
          {t('card.min')} {formatValue(Math.min(...values))} · {t('card.max')} {formatValue(Math.max(...values))}
        </span>
      </div>
      <div className="flex-1 min-h-[40px] mt-1">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="w-full h-full" role="img"
             aria-label={lines.map((line) => tLabel(line.label)).join(', ')}>
          {lines.map((line, index) => {
            const colour = SLICE_COLOURS[index % SLICE_COLOURS.length]
            if (bars) {
              return line.points.map(([time, value], point) =>
                value === null ? null : (
                  <rect
                    key={`${line.key}-${point}`}
                    x={Math.max(0, at(time) - width / 2 + (lines.length > 1 ? (index - 0.5) * width : 0))}
                    y={up(value)}
                    width={width}
                    height={Math.max(0.5, H - up(value))}
                    fill={colour}
                    opacity={0.85}
                  />
                ),
              )
            }
            // ⚠️ Broken into runs at every gap. One polyline through a missing
            // point would draw a straight line across the outage, which is the
            // one thing the reader must not be told.
            const runs: string[] = []
            let run: string[] = []
            for (const [time, value] of line.points) {
              if (value === null) {
                if (run.length > 1) runs.push(run.join(' '))
                run = []
                continue
              }
              run.push(`${at(time).toFixed(2)},${up(value).toFixed(2)}`)
            }
            if (run.length > 1) runs.push(run.join(' '))
            return runs.map((points, piece) => (
              <polyline key={`${line.key}-${piece}`} points={points} fill="none" stroke={colour}
                        strokeWidth="1.6" vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" />
            ))
          })}
        </svg>
      </div>
      <div className="flex items-center gap-x-3 gap-y-0.5 flex-wrap mt-0.5">
        {lines.map((line, index) => (
          <span key={line.key} className="flex items-center gap-1.5 text-[10px] text-muted">
            <span className="rounded-full" style={{ width: 7, height: 7, background: SLICE_COLOURS[index % SLICE_COLOURS.length] }} />
            {tLabel(line.label)}
          </span>
        ))}
        <span className="ml-auto num text-[10px] text-faint whitespace-nowrap">{when(first)} – {when(last)}</span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Bars: the same rows a list draws, measured against the largest of them
// ---------------------------------------------------------------------------

/**
 * ⚠️ The scale is the biggest row, not the sum. These rows are a ranking
 * ("this indexer grabbed 40, that one 3"), not the parts of a whole, and
 * dividing by the sum would make every bar shrink as soon as a row is added.
 * The server has already refused this drawing for a card whose rows carry no
 * numbers, so a row without one here is a gap in a list that otherwise has
 * them: it keeps its place and shows no bar.
 */
export function BarsCard({ data, onAction, canAct, series }: RenderProps) {
  const { t } = useTranslation()
  const items = data?.items ?? []
  if (!items.length && !data?.error) return <Empty>{t('card.nothing')}</Empty>
  const numbers = items
    .map((item) => (typeof item.value === 'number' ? item.value : null))
    .filter((value): value is number => value !== null)
  const top = numbers.length ? Math.max(...numbers) : 0
  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <ul className="flex-1 min-h-0 scroll px-3 pb-1 pt-0.5 flex flex-col gap-1.5">
        {items.map((item, index) => {
          const value = typeof item.value === 'number' ? item.value : null
          const status = statusOf(item.status)
          return (
            <li key={String(item.id ?? index)} className="grid grid-cols-[1fr_auto] gap-x-2 gap-y-0.5">
              <span className="text-[12px] truncate" title={String(item.title ?? '')}>
                {String(item.title ?? '')}
              </span>
              <span className="num text-[11px] text-muted whitespace-nowrap tabular-nums">
                {value === null ? '' : formatValue(value, String(item.unit ?? ''))}
              </span>
              <span className="col-span-2 bar" data-status={status}>
                <i style={{ width: value !== null && top > 0 ? `${Math.max(1.5, (value / top) * 100)}%` : 0 }} />
              </span>
            </li>
          )
        })}
      </ul>
      {data?.secondary?.length || data?.actions?.length ? (
        <div className="px-3 pb-2.5 pt-1 flex items-center justify-between gap-2 border-t border-line">
          <Chips items={data?.secondary} series={series} />
          <ActionButtons actions={data?.actions} onAction={onAction} canAct={canAct} compact />
        </div>
      ) : null}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Ring: the slices the fetch worked out, as parts of one whole
// ---------------------------------------------------------------------------

/** Six colours, in the order the slices arrive. Beyond that the ring is a
 *  guessing game, and the server keeps the slice count small. */
const SLICE_COLOURS = [
  'var(--nd-accent)',
  'var(--nd-unknown)',
  'var(--nd-warn)',
  'var(--nd-ok)',
  'var(--nd-bad)',
  'color-mix(in srgb, var(--nd-accent) 45%, transparent)',
]

export function RingCard({ data }: RenderProps) {
  const { t } = useTranslation()
  const slices = (Array.isArray(data?.meta?.ring) ? data.meta.ring : []) as { label: string; value: number }[]
  const whole = slices.reduce((sum, one) => sum + one.value, 0)
  if (!slices.length || whole <= 0) return <Empty>{t('card.nothing')}</Empty>
  // The circumference the dashes are cut from. r=42 in a 100-wide box leaves
  // room for the stroke, which is centred on the path and would otherwise be
  // clipped at the edges.
  const round = 2 * Math.PI * 42
  // Where each slice starts, worked out before anything is drawn: a running
  // total kept inside the map would be a write during render.
  const starts = slices.reduce<number[]>(
    (sofar, one) => [...sofar, sofar[sofar.length - 1] + (one.value / whole) * round],
    [0],
  )
  return (
    <div className="flex-1 min-h-0 flex items-center gap-3 px-3 pb-3 pt-1">
      <div className="shrink-0 flex flex-col items-center gap-1 max-w-[7rem]">
      <div className="relative" style={{ width: 92, height: 92 }}>
        <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90" aria-hidden="true">
          {slices.map((one, index) => {
            const length = (one.value / whole) * round
            const offset = -starts[index]
            return (
              <circle
                key={index}
                cx="50"
                cy="50"
                r="42"
                fill="none"
                stroke={SLICE_COLOURS[index % SLICE_COLOURS.length]}
                strokeWidth="14"
                strokeDasharray={`${length.toFixed(2)} ${(round - length).toFixed(2)}`}
                strokeDashoffset={offset.toFixed(2)}
              />
            )
          })}
        </svg>
        {/* The card's own headline, kept. Pi-hole's ring would otherwise lose
            the "18% blocked" it exists to say. Without one, the whole, which
            is the one number the legend does not carry: repeating the first
            slice there would print it twice on one card. */}
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="num text-lg font-semibold leading-none">
            {data?.primary?.value !== undefined && data?.primary?.value !== null
              ? formatValue(data.primary.value, data.primary.unit ?? '')
              : formatValue(whole)}
          </span>
        </div>
      </div>
      {/* ⚠️ Under the ring, not inside it. The hole of a 92px ring with a
          14px stroke is 64px across, and "Heute geblockt" printed over the
          stroke and out the sides. */}
      <span className="text-[9px] text-faint truncate max-w-full text-center">
        {data?.primary?.label ? tLabel(data.primary.label) : t('card.total')}
      </span>
      </div>
      {/* The legend is not decoration: six colours nobody can name are six
          unlabelled slices, and the contrast work in 0.2.0 was for nothing if
          the only way to read a slice is its hue. */}
      <ul className="min-w-0 flex-1 flex flex-col gap-1 scroll">
        {slices.map((one, index) => (
          <li key={index} className="flex items-center gap-2 min-w-0">
            <span
              className="shrink-0 rounded-[3px]"
              style={{ width: 9, height: 9, background: SLICE_COLOURS[index % SLICE_COLOURS.length] }}
            />
            <span className="text-[11px] text-muted truncate flex-1">{tLabel(one.label)}</span>
            <span className="num text-[11px] whitespace-nowrap tabular-nums">{formatValue(one.value)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

// ---------------------------------------------------------------------------
// App tile: launcher with reachability
// ---------------------------------------------------------------------------

export function AppTile({ widget, data, link }: RenderProps) {
  const { t } = useTranslation()
  const health = widget.health
  const window = String(widget.options?.bars ?? '24h')
  const status: Status = health ? (health.last_ok === null ? 'unknown' : health.last_ok ? 'ok' : 'bad') : 'unknown'
  const description = String(data?.meta?.description ?? '')
  const href = safeUrl(link || widget.link || widget.service_link) || undefined
  const bars = health?.bars ?? []
  const Tag = href ? 'a' : 'div'
  return (
    <Tag
      href={href}
      target={href && data?.meta?.open_new_tab !== false ? '_blank' : undefined}
      rel="noopener noreferrer"
      className="flex-1 flex flex-col justify-center px-3 py-2 min-h-0 no-underline text-inherit"
    >
      <div className="flex items-center gap-3">
        <ServiceIcon icon={widget.icon} size={30} />
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-semibold truncate">{widget.title}</div>
          {description && <div className="text-[11px] text-muted truncate">{description}</div>}
        </div>
        <div className="flex flex-col items-end gap-1">
          <span className="dot" data-status={widget.options?.check === false ? 'unknown' : status} />
          {health?.last_latency_ms !== null && health?.last_latency_ms !== undefined && <span className="num text-[10px] text-faint">{health.last_latency_ms} ms</span>}
        </div>
      </div>
      {bars.length > 0 && (
        <div className="flex gap-[2px] mt-2 h-[6px]" title={t(`card.bars.${window}`, { defaultValue: t('card.bars.24h') })} aria-hidden="true">
          {bars.map((bar, index) => (
            <span
              key={index}
              className="flex-1 rounded-sm"
              style={{
                background: bar === null ? 'color-mix(in srgb, var(--nd-text) 8%, transparent)' : bar >= 0.99 ? 'var(--nd-ok)' : bar > 0.5 ? 'var(--nd-warn)' : 'var(--nd-bad)',
                opacity: bar === null ? 1 : 0.85,
              }}
            />
          ))}
        </div>
      )}
    </Tag>
  )
}
