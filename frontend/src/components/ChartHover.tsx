/**
 * The popup of the short chart on a chart card: the moment under the pointer,
 * and every line's value at it (#65). The lines are sparklines stacked on one
 * scale; this layer lies over them and works in percent of their box, so it
 * needs no measuring and stays right when the card is resized.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { formatValue } from '../lib/format'

/** The height the sparklines are drawn in; the same mapping as Sparkline, as a share of the box. */
const DRAWN = 64

export interface HoverLine {
  metric: string
  values: number[]
  /** Seconds, one per value; null for the board's own series, which carry no times. */
  times: number[] | null
  colour: string
}

export function ChartHover({ lines, low, high, labelFor }: {
  lines: HoverLine[]
  low: number
  high: number
  labelFor: (metric: string) => string
}) {
  const { i18n } = useTranslation()
  const [share, setShare] = useState<number | null>(null)
  const span = high - low || 1
  const top = (value: number) => ((DRAWN - 3 - ((value - low) / span) * (DRAWN - 6)) / DRAWN) * 100
  // Each sparkline spreads its own points evenly over the width, so each line is read at its own index.
  const tipped =
    share === null
      ? []
      : lines.map((line) => {
          const index = Math.round(share * (line.values.length - 1))
          return { line, index, left: (index / (line.values.length - 1)) * 100, value: line.values[index] }
        })
  const first = tipped[0]
  const time = first && first.line.times ? first.line.times[first.index] : null
  const round = (value: number) => formatValue(Math.round(value * 10) / 10)
  const single = lines.length === 1
  const anchor = first ? (first.left < 25 ? '0%' : first.left > 75 ? '-100%' : '-50%') : '-50%'

  return (
    <div
      className="absolute inset-0"
      data-testid="chart-hover"
      onPointerMove={(event) => {
        const rect = event.currentTarget.getBoundingClientRect()
        if (rect.width > 0) setShare(Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)))
      }}
      onPointerLeave={() => setShare(null)}
    >
      {first && (
        <>
          <div className="pointer-events-none absolute inset-y-0 w-px" style={{ left: `${first.left}%`, background: 'var(--nd-border-strong)' }} />
          {tipped.map(({ line, left, value }) => (
            <span
              key={line.metric}
              className="pointer-events-none absolute rounded-full"
              style={{ left: `${left}%`, top: `${top(value)}%`, width: 8, height: 8, transform: 'translate(-50%, -50%)', background: 'var(--nd-bg)', border: `2px solid ${line.colour}` }}
            />
          ))}
          <div
            className="glass-strong pointer-events-none absolute z-10 whitespace-nowrap rounded-lg px-2 py-1 text-[11px] shadow-xl"
            style={{ left: `${first.left}%`, top: `${Math.min(...tipped.map(({ value }) => top(value)))}%`, transform: `translate(${anchor}, calc(-100% - 8px))` }}
            data-testid="chart-tip"
          >
            {time !== null && (
              <div className="text-faint">{new Date(time * 1000).toLocaleString(i18n.language, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}</div>
            )}
            {single ? (
              <div className="num">{round(first.value)}</div>
            ) : (
              tipped.map(({ line, value }) => (
                <div key={line.metric} className="flex items-center gap-1.5" data-testid="chart-tip-line">
                  <span className="rounded-full" style={{ width: 7, height: 7, background: line.colour }} />
                  <span className="text-muted">{labelFor(line.metric)}</span>
                  <span className="num ml-auto pl-2">{round(value)}</span>
                </div>
              ))
            )}
          </div>
        </>
      )}
    </div>
  )
}
