/**
 * A chart over 7 days, 30 days or a year (roadmap M4): the average as a line,
 * for a single line the band from the lowest to the highest behind it, and
 * the forecast carried on, dashed, to the limit it heads for.
 *
 * Loaded only once a card is switched to one of these ranges: the board's
 * first load stays as it was.
 */
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { get } from '../api/client'
import { carriesOn, type Forecast } from '../lib/forecast'
import { formatValue } from '../lib/format'
import { useBoxSize } from '../lib/useBoxSize'

/** ``[ts, avg, min, max]``, ts in seconds. */
type Point = [number, number, number, number]

const DAY = 86400
const PAD = { left: 38, right: 8, top: 8, bottom: 18 }

/** The points, and when they were read: the chart is drawn up to that moment, not to whenever it renders. */
function useLongHistory(widgetId: number, days: number): { lines: Record<string, Point[]>; at: number } | null {
  const [points, setPoints] = useState<{ lines: Record<string, Point[]>; at: number } | null>(null)
  useEffect(() => {
    setPoints(null)
    if (!(widgetId > 0)) return
    let gone = false
    const read = () =>
      get<Record<string, Point[]>>(`/widgets/${widgetId}/history/long?days=${days}`)
        .then((answer) => {
          if (!gone && answer && typeof answer === 'object') setPoints({ lines: answer, at: Date.now() / 1000 })
        })
        .catch(() => undefined)
    void read()
    // Hours and days change slowly; ten minutes is often enough.
    const timer = window.setInterval(() => void read(), 600_000)
    return () => {
      gone = true
      window.clearInterval(timer)
    }
  }, [widgetId, days])
  return points
}

function ticks(low: number, high: number, count = 4): number[] {
  const step = (high - low) / count
  return Array.from({ length: count + 1 }, (_, index) => low + step * index)
}

export function LongChart({ widgetId, metrics, days, colours, labelFor, forecast }: {
  widgetId: number
  metrics: string[]
  days: number
  colours: string[]
  labelFor: (metric: string) => string
  forecast?: Forecast | null
}) {
  const { t, i18n } = useTranslation()
  const box = useRef<HTMLDivElement>(null)
  const { width, height } = useBoxSize(box)
  const fetched = useLongHistory(widgetId, days)
  const [hover, setHover] = useState<number | null>(null)
  const lines = metrics.map((metric) => ({ metric, points: fetched?.lines[metric] ?? [] })).filter((line) => line.points.length > 1)

  if (!fetched) return <div ref={box} className="flex-1 min-h-[60px]" />
  if (!lines.length || width < 40 || height < 40) {
    return (
      <div ref={box} className="flex-1 min-h-[60px] flex items-center justify-center text-[11px] text-muted">
        {fetched && !lines.length ? t('card.collectingLong') : null}
      </div>
    )
  }

  const now = fetched.at
  const single = lines.length === 1
  const ahead = carriesOn(forecast, lines[0].metric) && single && days >= 30 ? forecast : null
  const aheadDays = ahead ? Math.min((ahead.days ?? 0) + 3, days >= 365 ? 60 : 14) : 0
  const first = Math.min(...lines.map((line) => line.points[0][0]))
  const last = now + aheadDays * DAY
  const all = lines.flatMap((line) => line.points)
  let low = Math.min(...all.map((point) => (single ? point[2] : point[1])))
  let high = Math.max(...all.map((point) => (single ? point[3] : point[1])))
  if (ahead && typeof ahead.limit === 'number') {
    low = Math.min(low, ahead.limit)
    high = Math.max(high, ahead.limit)
  }
  if (high === low) high = low + 1
  const x = (ts: number) => PAD.left + ((ts - first) / (last - first)) * (width - PAD.left - PAD.right)
  const y = (value: number) => PAD.top + (1 - (value - low) / (high - low)) * (height - PAD.top - PAD.bottom)
  const dayLabel = (ts: number) =>
    new Date(ts * 1000).toLocaleDateString(i18n.language, days >= 365 ? { month: 'short' } : { day: 'numeric', month: 'short' })
  // A small card gets fewer marks on either axis: four numbers stacked into 60 pixels are a smudge.
  const steps = height < 140 ? 1 : 4
  const marks = width < 360 ? 3 : days >= 365 ? 6 : days >= 30 ? 5 : 7
  const along = Array.from({ length: marks }, (_, index) => first + ((now - first) * index) / (marks - 1))

  // The forecast, cut at the right edge when its limit lies beyond the range shown.
  let dashed: { x1: number; y1: number; x2: number; y2: number; reaches: boolean; date: string } | null = null
  if (ahead && typeof ahead.limit === 'number' && typeof ahead.slope === 'number' && typeof ahead.now === 'number' && ahead.at) {
    const end = Math.min(ahead.at, last)
    const value = ahead.now + (ahead.slope * (end - now)) / DAY
    dashed = { x1: x(now), y1: y(ahead.now), x2: x(end), y2: y(value), reaches: ahead.at <= last, date: new Date(ahead.at * 1000).toLocaleDateString(i18n.language, { day: 'numeric', month: 'short' }) }
  }

  const shown = hover !== null ? lines[0].points[hover] : null
  const pick = (clientX: number) => {
    const rect = box.current?.getBoundingClientRect()
    if (!rect) return
    const at = clientX - rect.left
    let best = 0
    lines[0].points.forEach((point, index) => {
      if (Math.abs(x(point[0]) - at) < Math.abs(x(lines[0].points[best][0]) - at)) best = index
    })
    setHover(at > x(now) + 6 ? null : best)
  }

  return (
    <div ref={box} className="relative flex-1 min-h-[60px]" data-testid="long-chart">
      <svg
        className="absolute inset-0 h-full w-full overflow-visible"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={labelFor(lines[0].metric)}
        onPointerMove={(event) => pick(event.clientX)}
        onPointerLeave={() => setHover(null)}
      >
        <g className="text-line">
          {ticks(low, high, steps).map((value) => (
            <line key={value} x1={PAD.left} x2={width - PAD.right} y1={y(value)} y2={y(value)} stroke="currentColor" strokeWidth={1} />
          ))}
        </g>
        <g className="text-faint" fill="currentColor" fontSize={10}>
          {ticks(low, high, steps).map((value) => (
            <text key={value} x={PAD.left - 6} y={y(value) + 3.5} textAnchor="end" className="num">
              {formatValue(Math.round(value * 10) / 10)}
            </text>
          ))}
          {along.map((ts, index) => (
            <text key={ts} x={x(ts)} y={height - 4} textAnchor={index === 0 ? 'start' : index === along.length - 1 ? 'end' : 'middle'}>
              {dayLabel(ts)}
            </text>
          ))}
        </g>
        {single && (
          <polygon
            points={[...lines[0].points.map((p) => `${x(p[0])},${y(p[3])}`), ...lines[0].points.slice().reverse().map((p) => `${x(p[0])},${y(p[2])}`)].join(' ')}
            fill={colours[0]}
            opacity={0.16}
            data-testid="long-chart-band"
          />
        )}
        {lines.map((line, index) => (
          <polyline
            key={line.metric}
            points={line.points.map((p) => `${x(p[0])},${y(p[1])}`).join(' ')}
            fill="none"
            stroke={colours[index % colours.length]}
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ))}
        {dashed && ahead && (
          <g className="text-bad" data-testid="long-chart-ahead">
            <line x1={PAD.left} x2={width - PAD.right} y1={y(ahead.limit ?? 0)} y2={y(ahead.limit ?? 0)} stroke="currentColor" strokeWidth={1} strokeDasharray="2 3" opacity={0.7} />
            <line x1={dashed.x1} y1={dashed.y1} x2={dashed.x2} y2={dashed.y2} stroke={colours[0]} strokeWidth={2} strokeDasharray="5 4" opacity={0.85} />
            {dashed.reaches && <circle cx={dashed.x2} cy={dashed.y2} r={4.5} fill="var(--nd-surface-strong)" stroke="currentColor" strokeWidth={2} />}
            <text x={dashed.x2 - 8} y={dashed.reaches ? dashed.y2 + 14 : dashed.y2 - 10} textAnchor="end" fill="currentColor" fontSize={10}>
              {dashed.reaches ? dashed.date : t('forecast.reachesOn', { date: dashed.date })}
            </text>
          </g>
        )}
        {shown && (
          <g>
            <line x1={x(shown[0])} x2={x(shown[0])} y1={PAD.top} y2={height - PAD.bottom} stroke="var(--nd-border-strong)" strokeWidth={1} />
            <circle cx={x(shown[0])} cy={y(shown[1])} r={4} fill="var(--nd-bg)" stroke={colours[0]} strokeWidth={2} />
          </g>
        )}
      </svg>
      {shown && (
        <div
          className="glass-strong pointer-events-none absolute z-10 whitespace-nowrap rounded-lg px-2 py-1 text-[11px] shadow-xl"
          style={{ left: Math.min(Math.max(x(shown[0]), 60), width - 60), top: y(single ? shown[3] : shown[1]), transform: 'translate(-50%, calc(-100% - 8px))' }}
          data-testid="long-chart-tip"
        >
          <div className="text-faint">
            {new Date(shown[0] * 1000).toLocaleString(i18n.language, days >= 365 ? { day: 'numeric', month: 'short', year: 'numeric' } : { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}
          </div>
          <div className="num">{formatValue(Math.round(shown[1] * 10) / 10)}</div>
          {single && shown[2] !== shown[3] && (
            <div className="num text-faint">{t('card.lowHigh', { low: formatValue(Math.round(shown[2] * 10) / 10), high: formatValue(Math.round(shown[3] * 10) / 10) })}</div>
          )}
        </div>
      )}
    </div>
  )
}
