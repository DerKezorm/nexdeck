/**
 * The renderers: one small component per data shape. Every adapter maps its
 * service onto one of these, which keeps thirty integrations drawable with
 * fifteen components.
 */
import DOMPurify from 'dompurify'
import {
  Cloud,
  CloudDrizzle,
  CloudFog,
  CloudLightning,
  CloudRain,
  CloudSnow,
  CloudSun,
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
import { marked } from 'marked'
import { useEffect, useMemo, useState, type ComponentType, type ReactNode } from 'react'

import { formatValue, timeAgo } from '../lib/format'
import type { Action, Secondary, Status, WidgetData, WidgetView } from '../lib/types'
import { ServiceIcon, lucideIcon } from './ServiceIcon'
import { Sparkline } from './Sparkline'

export interface RenderProps {
  widget: WidgetView
  data: WidgetData | undefined
  series?: Record<string, number[]>
  canAct?: boolean
  onAction?: (action: string, params?: Record<string, unknown>) => void
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
  app: AppTile,
}

export function renderWidget(props: RenderProps) {
  const Renderer = RENDERERS[props.widget.renderer] ?? ValueCard
  return <Renderer {...props} />
}

// ---------------------------------------------------------------------------
// Shared pieces
// ---------------------------------------------------------------------------

function Chips({ items, series }: { items?: Secondary[]; series?: Record<string, number[]> }) {
  if (!items?.length) return null
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.slice(0, 4).map((item, index) => (
        <span className="chip" key={index}>
          {item.label}
          <b className="num">{formatValue(item.value, item.unit)}</b>
          {item.metric && series?.[item.metric] && (
            <span className="inline-block w-8 ml-1 -mb-0.5">
              <Sparkline values={series[item.metric]} height={10} fill={false} />
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
        const Symbol = action.icon ? (symbols[action.icon] ?? lucideIcon(action.icon)) : null
        return (
          <button
            key={action.id}
            className={`btn ${compact ? 'btn-icon h-6 w-6 border-0 bg-transparent' : 'h-7 px-2 text-xs'} ${action.danger ? 'btn-danger' : ''}`}
            onClick={(event) => {
              event.stopPropagation()
              onAction(action.id, action.params)
            }}
            aria-label={action.label}
            title={action.label}
          >
            {Symbol ? <Symbol size={13} /> : null}
            {!compact && <span>{action.label}</span>}
          </button>
        )
      })}
    </div>
  )
}

function statusOf(value: unknown): Status {
  return value === 'ok' || value === 'warn' || value === 'bad' ? value : 'unknown'
}

// ---------------------------------------------------------------------------
// Value: one big number
// ---------------------------------------------------------------------------

export function ValueCard({ data, series, onAction, canAct }: RenderProps) {
  const primary = data?.primary
  const metric = Object.keys(data?.metrics ?? {})[0]
  const points = metric ? series?.[metric] : undefined
  const hasFooter = Boolean(data?.secondary?.length || data?.actions?.length)
  return (
    <div className="flex-1 flex flex-col min-h-0 relative">
      {points && points.length > 1 && (
        <div className="absolute inset-x-0 bottom-0 h-[55%] opacity-60 pointer-events-none" aria-hidden="true">
          <Sparkline values={points} height={60} className="!h-full" />
        </div>
      )}
      <div className="flex-1 flex flex-col justify-center px-3 min-h-0 relative">
        <div className="num text-[30px] leading-none font-semibold tracking-tight rise" key={String(primary?.value)}>
          {formatValue(primary?.value)}
          {primary?.unit && <span className="text-sm text-muted font-medium ml-1.5">{primary.unit}</span>}
        </div>
        {primary?.label && <div className="text-[11px] text-muted mt-1.5 uppercase tracking-wide">{primary.label}</div>}
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
// Gauge: a ring for percentages
// ---------------------------------------------------------------------------

export function GaugeCard({ data }: RenderProps) {
  const value = typeof data?.primary?.value === 'number' ? data.primary.value : 0
  const radius = 26
  const circumference = 2 * Math.PI * radius
  const colour = data?.status === 'bad' ? 'var(--nd-bad)' : data?.status === 'warn' ? 'var(--nd-warn)' : 'var(--nd-accent)'
  return (
    <div className="flex-1 flex items-center gap-4 px-4 pb-3 min-h-0">
      <svg viewBox="0 0 64 64" className="w-[72px] h-[72px] flex-none" aria-hidden="true">
        <circle cx="32" cy="32" r={radius} fill="none" stroke="color-mix(in srgb, var(--nd-text) 10%, transparent)" strokeWidth="6" />
        <circle
          cx="32"
          cy="32"
          r={radius}
          fill="none"
          stroke={colour}
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - Math.min(100, Math.max(0, value)) / 100)}
          transform="rotate(-90 32 32)"
          style={{ transition: 'stroke-dashoffset 600ms cubic-bezier(.2,.7,.2,1)' }}
        />
        <text x="32" y="36" textAnchor="middle" className="num" fill="var(--nd-text)" fontSize="14" fontWeight="600">
          {Math.round(value)}%
        </text>
      </svg>
      <div className="min-w-0 flex-1">
        <div className="text-[11px] text-muted uppercase tracking-wide">{data?.primary?.label}</div>
        <div className="mt-2">
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
            <div className="text-[11px] text-muted w-14 truncate">{row.label}</div>
            <div className="min-w-0">
              {points && points.length > 1 ? (
                <Sparkline values={points} height={16} min={isPercent ? 0 : undefined} max={isPercent ? 100 : undefined} />
              ) : isPercent && numeric !== null ? (
                <div className="bar" data-status={numeric >= 90 ? 'bad' : numeric >= 75 ? 'warn' : 'ok'}>
                  <i style={{ width: `${Math.min(100, numeric)}%` }} />
                </div>
              ) : (
                <div className="bar"><i style={{ width: 0 }} /></div>
              )}
            </div>
            <div className="num text-[13px] font-semibold text-right w-16">{formatValue(row.value, row.unit)}</div>
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

export function ListCard({ data, onAction, canAct, series }: RenderProps) {
  const items = data?.items ?? []
  if (!items.length && !data?.error) return <Empty>Nothing to show</Empty>
  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <ul className="flex-1 min-h-0 scroll px-1.5 pb-1">
        {items.map((item, index) => {
          const status = statusOf(item.status)
          const progress = typeof item.progress === 'number' ? item.progress : null
          const memory = typeof item.memory_percent === 'number' ? item.memory_percent : null
          return (
            <li key={String(item.id ?? index)} className="group/row flex items-center gap-2.5 px-1.5 py-1.5 rounded-lg hover:bg-surface-hover">
              {item.icon ? <ServiceIcon icon={String(item.icon)} size={18} /> : <span className="dot" data-status={status} />}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-medium truncate">{String(item.title ?? '')}</span>
                  {typeof item.cpu === 'number' && <span className="num text-[10px] text-muted">{item.cpu.toFixed(0)}%</span>}
                </div>
                {item.subtitle ? <div className="text-[11px] text-muted truncate">{String(item.subtitle)}</div> : null}
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
              {item.actions && canAct ? (
                <span className="opacity-0 group-hover/row:opacity-100 transition-opacity">
                  <ActionButtons actions={item.actions as Action[]} onAction={onAction} canAct={canAct} compact />
                </span>
              ) : null}
              {item.value !== undefined && item.value !== '' && (
                <span className="num text-xs text-muted whitespace-nowrap">{String(item.value)}</span>
              )}
              {item.url ? (
                <a href={String(item.url)} target="_blank" rel="noreferrer" className="text-faint hover:text-accent" aria-label="Open">
                  <ExternalLink size={12} />
                </a>
              ) : null}
            </li>
          )
        })}
      </ul>
      {(data?.secondary?.length || data?.actions?.length) ? (
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

export function NowPlayingCard({ data }: RenderProps) {
  const items = data?.items ?? []
  if (!items.length) return <Empty>Nothing is playing</Empty>
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
                style={item.art ? { backgroundImage: `url(${item.art})`, backgroundSize: 'cover' } : undefined}
              >
                {!item.art && String(item.title ?? '?').slice(0, 2).toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-[13px] font-medium truncate">{String(item.title ?? '')}</div>
                <div className="text-[11px] text-muted truncate">{String(item.subtitle ?? '')}</div>
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
// Calendar: upcoming items grouped by day
// ---------------------------------------------------------------------------

export function CalendarCard({ data }: RenderProps) {
  const items = data?.items ?? []
  if (!items.length) return <Empty>Nothing coming up</Empty>
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
          <div className="text-[10px] uppercase tracking-wide text-faint mb-1">{dayLabel(date)}</div>
          {entries.map((entry, index) => (
            <div key={index} className="flex items-center gap-2 py-1">
              <span className="dot" data-status={statusOf(entry.status)} />
              <span className="text-[13px] font-medium truncate flex-1">{String(entry.title ?? '')}</span>
              <span className="text-[11px] text-muted truncate max-w-[45%]">{String(entry.subtitle ?? '')}</span>
            </div>
          ))}
        </li>
      ))}
    </ul>
  )
}

function dayLabel(date: string): string {
  const today = new Date()
  const target = new Date(date + 'T00:00:00')
  const diff = Math.round((target.getTime() - new Date(today.toDateString()).getTime()) / 86400000)
  if (diff === 0) return 'Today'
  if (diff === 1) return 'Tomorrow'
  if (Number.isNaN(diff)) return date
  return target.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'short' })
}

// ---------------------------------------------------------------------------
// Text: markdown
// ---------------------------------------------------------------------------

export function TextCard({ data }: RenderProps) {
  const html = useMemo(() => {
    const source = String(data?.meta?.markdown ?? '')
    return DOMPurify.sanitize(marked.parse(source, { async: false }) as string, { ADD_ATTR: ['target'] })
  }, [data?.meta?.markdown])
  return <div className="prose-card flex-1 min-h-0 scroll px-3 pb-3 text-[13px]" dangerouslySetInnerHTML={{ __html: html }} />
}

// ---------------------------------------------------------------------------
// Bookmarks
// ---------------------------------------------------------------------------

export function BookmarksCard({ data }: RenderProps) {
  const items = data?.items ?? []
  const grid = data?.meta?.layout === 'grid'
  if (!items.length) return <Empty>No links yet</Empty>
  return (
    <ul className={`flex-1 min-h-0 scroll px-2 pb-2 ${grid ? 'grid grid-cols-3 gap-1 content-start' : ''}`}>
      {items.map((item, index) => (
        <li key={index}>
          <a
            href={String(item.url ?? '#')}
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

export function IframeCard({ data, editing }: RenderProps) {
  const url = String(data?.meta?.url ?? '')
  if (!url) return <Empty>No URL set</Empty>
  return (
    <div className="flex-1 min-h-0 relative">
      <iframe src={url} title="Embedded page" className="absolute inset-0 w-full h-full border-0 rounded-b-[var(--nd-radius)] bg-white" sandbox="allow-scripts allow-same-origin allow-forms allow-popups" loading="lazy" />
      {editing && <div className="absolute inset-0" />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Clock
// ---------------------------------------------------------------------------

export function ClockCard({ data }: RenderProps) {
  const [now, setNow] = useState(() => new Date())
  const seconds = Boolean(data?.meta?.seconds)
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), seconds ? 1000 : 10000)
    return () => window.clearInterval(id)
  }, [seconds])
  const timeZone = (data?.meta?.timezone as string) || undefined
  const hour12 = data?.meta?.format === '12h'
  let time = '--:--'
  let date = ''
  try {
    time = now.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: seconds ? '2-digit' : undefined, hour12, timeZone })
    date = now.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long', timeZone })
  } catch {
    time = now.toLocaleTimeString()
  }
  return (
    <div className="flex-1 flex flex-col justify-center px-4 py-3 min-h-0">
      <div className="num text-[40px] leading-none font-semibold tracking-tight">{time}</div>
      {data?.meta?.date !== false && <div className="text-xs text-muted mt-2">{date}</div>}
      {data?.meta?.label ? <div className="text-[11px] text-faint mt-0.5 uppercase tracking-wide">{String(data.meta.label)}</div> : null}
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
            {data?.primary?.label ? ` · ${data.primary.label}` : ''}
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
  const items = data?.items ?? []
  if (!items.length) return <Empty>No entries</Empty>
  const cards = data?.meta?.style === 'cards'
  return (
    <ul className={`flex-1 min-h-0 scroll px-2 pb-2 ${cards ? 'grid grid-cols-2 gap-2 content-start' : ''}`}>
      {items.map((item, index) => (
        <li key={index}>
          <a href={String(item.url ?? '#')} target="_blank" rel="noreferrer" className={`block rounded-lg hover:bg-surface-hover ${cards ? 'p-2' : 'px-2 py-1.5'}`}>
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
  const lines = (data?.meta?.lines_preview as string[] | undefined) ?? []
  return (
    <pre className="flex-1 min-h-0 scroll px-3 pb-3 m-0 font-mono text-[11px] leading-[1.5] text-muted whitespace-pre-wrap">
      {lines.length ? lines.map((line, index) => (
        <div key={index} className={/error|fatal/i.test(line) ? 'text-bad' : /warn/i.test(line) ? 'text-warn' : ''}>
          {line}
        </div>
      )) : <span className="text-faint">Waiting for log lines…</span>}
    </pre>
  )
}

// ---------------------------------------------------------------------------
// Chart: a larger series with min, max and current
// ---------------------------------------------------------------------------

export function ChartCard({ data, series }: RenderProps) {
  const metric = Object.keys(data?.metrics ?? {})[0]
  const points = (metric && series?.[metric]) || []
  const current = data?.primary?.value
  const unit = data?.primary?.unit ?? ''
  return (
    <div className="flex-1 flex flex-col min-h-0 px-3 pb-3">
      <div className="flex items-baseline gap-2">
        <span className="num text-2xl font-semibold">{formatValue(current, unit)}</span>
        <span className="text-[11px] text-muted">{data?.primary?.label}</span>
        {points.length > 1 && (
          <span className="ml-auto num text-[10px] text-faint">
            min {formatValue(Math.min(...points))} · max {formatValue(Math.max(...points))}
          </span>
        )}
      </div>
      <div className="flex-1 min-h-0 mt-1">
        {points.length > 1 ? <Sparkline values={points} height={64} /> : <Empty>Collecting…</Empty>}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// App tile: launcher with reachability
// ---------------------------------------------------------------------------

export function AppTile({ widget, data, link }: RenderProps) {
  const health = widget.health
  const status: Status = health ? (health.last_ok === null ? 'unknown' : health.last_ok ? 'ok' : 'bad') : 'unknown'
  const description = String(data?.meta?.description ?? '')
  const href = link || widget.link || undefined
  const bars = health?.bars ?? []
  const Tag = href ? 'a' : 'div'
  return (
    <Tag
      href={href}
      target={href && data?.meta?.open_new_tab !== false ? '_blank' : undefined}
      rel="noreferrer"
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
          {health?.last_latency_ms !== null && health?.last_latency_ms !== undefined && (
            <span className="num text-[10px] text-faint">{health.last_latency_ms} ms</span>
          )}
        </div>
      </div>
      {bars.length > 0 && (
        <div className="flex gap-[2px] mt-2 h-[6px]" aria-hidden="true">
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
