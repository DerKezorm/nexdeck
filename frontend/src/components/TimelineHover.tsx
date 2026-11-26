/**
 * The popup of a timeline card: the moment under the pointer, and every
 * line's reading at it, with its unit.
 *
 * Unlike ChartHover, the points carry their own times and need not be evenly
 * spaced, so each line is read at the point nearest the moment rather than at
 * an index. A line with nothing near that moment (a gap, or it began later) is
 * left out of the tip rather than shown with a reading from elsewhere.
 * Positions are in percent of the drawing's box, which needs no measuring.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { formatValue } from '../lib/format'

export interface TipLine {
  key: string
  label: string
  colour: string
  unit: string
  points: [number, number | null][]
}

export function TimelineHover({ lines, first, last, down, short }: {
  lines: TipLine[]
  first: number
  last: number
  /** Where a value sits, in percent from the top of the box. */
  down: (value: number) => number
  /** A stretch of a day or so: the tip names the time, not only the day. */
  short: boolean
}) {
  const { i18n } = useTranslation()
  const [moment, setMoment] = useState<number | null>(null)
  const span = last - first || 1
  const across = (time: number) => ((time - first) / span) * 100

  const pick = (share: number) => {
    const wanted = first + share * span
    let best: number | null = null
    for (const line of lines) {
      for (const [time] of line.points) {
        if (best === null || Math.abs(time - wanted) < Math.abs(best - wanted)) best = time
      }
    }
    setMoment(best)
  }
  const tipped =
    moment === null
      ? []
      : lines.flatMap((line) => {
          const spacing = line.points.length > 1 ? (line.points[line.points.length - 1][0] - line.points[0][0]) / (line.points.length - 1) : 0
          const near = line.points.reduce((best, point) => (Math.abs(point[0] - moment) < Math.abs(best[0] - moment) ? point : best), line.points[0])
          const value = near[1]
          return value !== null && Math.abs(near[0] - moment) <= spacing / 2 + 1 ? [{ line, value }] : []
        })
  const left = moment === null ? 0 : across(moment)
  const anchor = left < 25 ? '0%' : left > 75 ? '-100%' : '-50%'
  const round = (value: number) => formatValue(Math.round(value * 10) / 10)

  return (
    <div
      className="absolute inset-0"
      data-testid="timeline-hover"
      onPointerMove={(event) => {
        const rect = event.currentTarget.getBoundingClientRect()
        if (rect.width > 0) pick(Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)))
      }}
      onPointerLeave={() => setMoment(null)}
    >
      {moment !== null && tipped.length > 0 && (
        <>
          <div className="pointer-events-none absolute inset-y-0 w-px" style={{ left: `${left}%`, background: 'var(--nd-border-strong)' }} />
          {tipped.map(({ line, value }) => (
            <span
              key={line.key}
              className="pointer-events-none absolute rounded-full"
              style={{ left: `${left}%`, top: `${down(value)}%`, width: 8, height: 8, transform: 'translate(-50%, -50%)', background: 'var(--nd-bg)', border: `2px solid ${line.colour}` }}
            />
          ))}
          <div
            className="glass-strong pointer-events-none absolute z-10 whitespace-nowrap rounded-lg px-2 py-1 text-[11px] shadow-xl"
            style={{ left: `${left}%`, top: `${Math.min(...tipped.map(({ value }) => down(value)))}%`, transform: `translate(${anchor}, calc(-100% - 8px))` }}
            data-testid="timeline-tip"
          >
            <div className="text-faint">
              {new Date(moment * 1000).toLocaleString(i18n.language, short ? { hour: '2-digit', minute: '2-digit' } : { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}
            </div>
            {tipped.map(({ line, value }) => (
              <div key={line.key} className="flex items-center gap-1.5" data-testid="timeline-tip-line">
                <span className="rounded-full" style={{ width: 7, height: 7, background: line.colour }} />
                <span className="text-muted">{line.label}</span>
                <span className="num ml-auto pl-2">{`${round(value)}${line.unit ? ` ${line.unit}` : ''}`}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
