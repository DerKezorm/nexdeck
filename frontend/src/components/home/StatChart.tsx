import { useLayoutEffect, useRef, useState } from 'react'

import { axisRange } from '../../lib/home'

/** The width a box is drawn at, where the screen decides it rather than the page; ``fallback`` until it is measured, and where it is not. */
export function useWidth(fallback: number, measure = true) {
  const box = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(fallback)
  useLayoutEffect(() => {
    if (!measure || !box.current) return setWidth(fallback)
    const take = () => setWidth(Math.round(box.current?.getBoundingClientRect().width || fallback))
    take()
    if (typeof ResizeObserver === 'undefined') return
    const watch = new ResizeObserver(take)
    watch.observe(box.current)
    return () => watch.disconnect()
  }, [fallback, measure])
  return [box, width] as const
}

export interface ChartLine {
  points: [number, number][]
  colour: string
  fill?: boolean
  dash?: boolean
  dot?: boolean
  width?: number
  /** What a pointer over it reads; the series' name. */
  label?: string
}

interface Props {
  width: number
  height: number
  /** The times the x axis spans, in milliseconds. */
  from: number
  to: number
  lines?: ChartLine[]
  /** Low to high per step, behind the lines. */
  band?: { points: [number, number, number][]; colour: string }
  /** A counter's change per step; ``step`` is how long one is, in milliseconds. */
  bars?: { points: [number, number][]; colour: string; step: number }
  /** A target as it changed: a step line, broken while it is null. */
  steps?: { points: [number, number | null][]; colour: string }
  /** When something happened, as bars along the bottom: a thermostat heating. */
  spans?: { spans: [number, number][]; colour: string }
  labels?: [number, string][]
  /** How a value on the y axis is written. */
  tick?: (value: number) => string
  /** No axis, no labels, edge to edge: the small card's line behind its number. */
  plain?: boolean
}

/**
 * A chart of its own, drawn as SVG like ``Sparkline``: lines, a band, bars,
 * a step line and spans on one time axis. No library: the house's history is
 * a few hundred points, and the page draws them at the size it is given.
 */
export function StatChart({ width, height, from, to, lines = [], band, bars, steps, spans, labels = [], tick = (value) => String(Math.round(value)), plain = false }: Props) {
  const pad = plain ? { l: 0, r: 0, t: 4, b: 0 } : { l: 30, r: 6, t: 8, b: spans ? 26 : 18 }
  const values = [
    ...lines.flatMap((line) => line.points.map((point) => point[1])),
    ...(band?.points.flatMap((point) => [point[1], point[2]]) ?? []),
    ...(bars?.points.map((point) => point[1]) ?? []),
    ...(steps?.points.flatMap((point) => (point[1] === null ? [] : [point[1]])) ?? []),
  ]
  const [min, max] = axisRange(values, Boolean(bars))
  const span = Math.max(1, to - from)
  const plotW = Math.max(1, width - pad.l - pad.r)
  const plotH = Math.max(1, height - pad.t - pad.b)
  const X = (t: number) => pad.l + ((t - from) / span) * plotW
  const Y = (value: number) => pad.t + (1 - (value - min) / (max - min)) * plotH
  const bottom = height - pad.b
  const path = (points: [number, number][]) => points.map(([t, value], index) => `${index ? 'L' : 'M'}${X(t).toFixed(1)},${Y(value).toFixed(1)}`).join(' ')

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="block overflow-visible" role="img" aria-hidden={plain || undefined} data-chart>
      {!plain && [min, (min + max) / 2, max].map((value) => (
        <g key={value}>
          <line x1={pad.l} x2={width - pad.r} y1={Y(value)} y2={Y(value)} stroke="color-mix(in srgb, var(--nd-text) 7%, transparent)" />
          <text x={pad.l - 4} y={Y(value) + 3} textAnchor="end" className="stat-tick">{tick(value)}</text>
        </g>
      ))}
      {spans?.spans.map(([start, end]) => {
        const left = Math.max(pad.l, X(start))
        const right = Math.min(width - pad.r, X(end))
        return right > left ? <rect key={start} x={left} y={bottom - 6} width={Math.max(1.5, right - left)} height={6} rx={2} fill={spans.colour} opacity={0.85} data-span /> : null
      })}
      {band && band.points.length > 1 && (
        <polygon
          points={`${band.points.map(([t, , high]) => `${X(t).toFixed(1)},${Y(high).toFixed(1)}`).join(' ')} ${[...band.points].reverse().map(([t, low]) => `${X(t).toFixed(1)},${Y(low).toFixed(1)}`).join(' ')}`}
          fill={band.colour} opacity={0.18} data-band />
      )}
      {bars?.points.map(([t, value], index) => {
        const cell = X(t + bars.step) - X(t)
        const barW = Math.max(1, cell * 0.66)
        return (
          <rect key={t} x={X(t) + (cell - barW) / 2} y={Y(Math.max(0, value))} width={barW} height={Math.max(0, Y(Math.min(0, value)) - Y(Math.max(0, value)))} rx={Math.min(3, barW / 3)}
            fill={bars.colour} opacity={index === bars.points.length - 1 ? 1 : 0.72} data-bar />
        )
      })}
      {steps && steps.points.length > 0 && (
        <path
          d={steps.points.reduce((d, [t, value], index) => {
            const next = steps.points[index + 1]?.[0] ?? to
            if (value === null) return d
            return `${d} M${X(Math.max(from, t)).toFixed(1)},${Y(value).toFixed(1)} H${X(Math.min(to, next)).toFixed(1)}`
          }, '')}
          fill="none" stroke={steps.colour} strokeWidth={1.5} strokeDasharray="4 3" data-steps />
      )}
      {lines.map((line, index) => line.points.length > 0 && (
        <g key={index} data-line={line.label ?? index}>
          {line.fill && line.points.length > 1 && (
            <path d={`${path(line.points)} L${X(line.points.at(-1)![0]).toFixed(1)},${bottom} L${X(line.points[0][0]).toFixed(1)},${bottom} Z`} fill={line.colour} opacity={0.12} />
          )}
          <path d={path(line.points)} fill="none" stroke={line.colour} strokeWidth={line.width ?? 2} strokeLinejoin="round" strokeLinecap="round"
            strokeDasharray={line.dash ? '3 3' : undefined} style={line.dash ? undefined : { filter: `drop-shadow(0 0 3px ${line.colour})` }}>
            {line.label && <title>{line.label}</title>}
          </path>
          {line.dot && <circle cx={X(line.points.at(-1)![0])} cy={Y(line.points.at(-1)![1])} r={3.5} fill={line.colour} />}
        </g>
      ))}
      {!plain && labels.map(([t, text]) => {
        const share = (t - from) / span
        return (
          <text key={`${t}${text}`} x={X(t)} y={height - 4} textAnchor={share <= 0.02 ? 'start' : share >= 0.98 ? 'end' : 'middle'} className="stat-tick">{text}</text>
        )
      })}
    </svg>
  )
}

const HOUR = 3_600_000
const DAY = 24 * HOUR

/** The hour and the day of the month of a moment in the house's time zone. */
function partsOf(moment: number, zone: string): { hour: number; day: number; weekday: number } {
  const parts = new Intl.DateTimeFormat('en-GB', { timeZone: zone, hour: 'numeric', hourCycle: 'h23', day: 'numeric', weekday: 'short' }).formatToParts(new Date(moment))
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? ''
  return { hour: Number(get('hour')), day: Number(get('day')), weekday: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].indexOf(get('weekday')) }
}

/**
 * The labels under a chart, in the house's time zone and the page's language:
 * hours over a day, weekdays over a week, dates over a month, months over a
 * year. ``now`` is written at the end of a period that ends now. A narrow
 * chart gets fewer.
 */
export function timeLabels(period: string, from: number, to: number, zone: string, language: string, width: number, now: string): [number, string][] {
  const format = (options: Intl.DateTimeFormatOptions) => {
    try {
      return new Intl.DateTimeFormat(language, { timeZone: zone, ...options })
    } catch {
      return new Intl.DateTimeFormat(language, options)
    }
  }
  const room = width < 260 ? 2 : 1
  if (period === 'day') {
    const hours = format({ hour: 'numeric', minute: '2-digit' })
    return [0, 6, 12, 18].filter((_, index) => index % room === 0).map((hour) => [from + ((to - from) * hour) / 24, hours.format(new Date(from + hour * HOUR))])
  }
  if (period === 'week') {
    const days = format({ weekday: 'short' })
    return Array.from({ length: 7 }, (_, index) => [from + ((to - from) * (index + 0.5)) / 7, days.format(new Date(from + index * DAY + 12 * HOUR))] as [number, string]).filter((_, index) => index % room === 0)
  }
  if (period === '24h') {
    const hours = format({ hour: 'numeric', minute: '2-digit' })
    const found: [number, string][] = []
    for (let at = Math.ceil(from / HOUR) * HOUR; at < to - 2 * HOUR; at += HOUR) {
      if (partsOf(at, zone).hour % (6 * room) === 0) found.push([at, hours.format(new Date(at))])
    }
    return [...found, [to, now]]
  }
  if (period === '7d') {
    const days = format({ weekday: 'short' })
    const found: [number, string][] = []
    for (let at = Math.ceil(from / HOUR) * HOUR; at < to - 6 * HOUR; at += HOUR) {
      const parts = partsOf(at, zone)
      if (parts.hour === 12 && (room === 1 || parts.weekday % 2 === 0)) found.push([at, days.format(new Date(at))])
    }
    return found
  }
  if (period === '30d') {
    const dates = format({ day: 'numeric', month: 'numeric' })
    const found: [number, string][] = []
    for (let at = from + DAY; at < to - 2 * DAY; at += DAY) {
      if (partsOf(at, zone).weekday === 0 && (room === 1 || found.length % 2 === 0)) found.push([at, dates.format(new Date(at))])
    }
    return [...found, [to, now]]
  }
  const months = format({ month: 'short' })
  const found: [number, string][] = []
  for (let at = from; at < to - 10 * DAY; at += DAY) {
    if (partsOf(at, zone).day === 1) found.push([at, months.format(new Date(at))])
  }
  return found.filter((_, index) => index % (room * (width < 420 ? 2 : 1)) === 0)
}
