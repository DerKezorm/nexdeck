import { useTranslation } from 'react-i18next'

import { tLabel } from '../i18n/texts'
import type { WidgetData } from '../lib/types'
import { Rolled } from './Rolled'

/**
 * Days as squares, a column per week and a row per weekday, darker the more
 * happened that day: the way GitHub draws contributions, which everybody
 * reads at a glance. The data brings `[date, value]` pairs, oldest first.
 */
export interface Heat {
  days: [string, number][]
  unit?: string
}

/** Monday is the first row, as in most of the world's calendars. */
function weekday(day: string): number {
  return (new Date(`${day}T12:00:00`).getDay() + 6) % 7
}

/** How dark a square is: four steps above nothing, by its share of the busiest day. */
export function shade(value: number, highest: number): number {
  if (value <= 0 || highest <= 0) return 0
  return Math.min(4, Math.max(1, Math.ceil((value / highest) * 4)))
}

/** The weeks of a run of days, each a column of seven, the first padded to its weekday. */
export function weeks(days: [string, number][]): ([string, number] | null)[][] {
  if (!days.length) return []
  const cells: ([string, number] | null)[] = [...Array<null>(weekday(days[0][0])).fill(null), ...days]
  const columns: ([string, number] | null)[][] = []
  for (let index = 0; index < cells.length; index += 7) columns.push(cells.slice(index, index + 7))
  return columns
}

/** A square and the room after it, in the units of the picture. */
const CELL = 12
const GAP = 2.5

const STEPS = ['color-mix(in srgb, var(--nd-text) 7%, transparent)', 'color-mix(in srgb, var(--nd-accent) 28%, transparent)', 'color-mix(in srgb, var(--nd-accent) 50%, transparent)', 'color-mix(in srgb, var(--nd-accent) 74%, transparent)', 'var(--nd-accent)']

export function HeatmapCard({ data }: { data: WidgetData | undefined }) {
  const { t, i18n } = useTranslation()
  const heat = (data?.meta?.heatmap ?? { days: [] }) as Heat
  const days = (heat.days ?? []).filter((one): one is [string, number] => Array.isArray(one) && typeof one[0] === 'string' && typeof one[1] === 'number')
  if (!days.length) return <div className="flex-1 flex items-center justify-center text-xs text-faint">{t('card.collecting')}</div>
  const highest = Math.max(...days.map(([, value]) => value))
  const columns = weeks(days)
  const unit = heat.unit ? ` ${heat.unit}` : ''
  const when = (day: string) => new Date(`${day}T12:00:00`).toLocaleDateString(i18n.language, { weekday: 'short', day: 'numeric', month: 'short' })
  const busiest = days.reduce((best, one) => (one[1] > best[1] ? one : best), days[0])
  return (
    <div className="flex-1 flex flex-col min-h-0 px-3 pb-2.5">
      {/* Squares stay square: the picture scales as a whole and keeps its shape. */}
      <svg className="flex-1 min-h-0 w-full" viewBox={`0 0 ${columns.length * CELL - GAP} ${7 * CELL - GAP}`} preserveAspectRatio="xMidYMid meet" data-testid="heatmap">
        {columns.flatMap((column, x) =>
          column.map((cell, y) =>
            cell ? (
              <rect
                key={`${x}-${y}`}
                x={x * CELL}
                y={y * CELL}
                width={CELL - GAP}
                height={CELL - GAP}
                rx="2"
                className="bar-in"
                style={{ fill: STEPS[shade(cell[1], highest)], animationDelay: `${x * 15}ms` }}
                data-shade={shade(cell[1], highest)}
              >
                <title>{`${when(cell[0])}: ${cell[1]}${unit}`}</title>
              </rect>
            ) : null,
          ),
        )}
      </svg>
      <div className="flex items-center gap-1.5 mt-2 min-w-0">
        <span className="chip">
          {tLabel(data?.primary?.label ?? '')}
          <b className="num">
            <Rolled value={data?.primary?.value} />
          </b>
        </span>
        {busiest[1] > 0 && (
          <span className="chip truncate">
            {tLabel('Busiest day')} <b className="num">{when(busiest[0])}</b>
          </span>
        )}
        <span className="ml-auto flex items-center gap-[3px]" aria-hidden="true">
          {STEPS.map((step, index) => (
            <span key={index} className="h-2.5 w-2.5 rounded-[2px]" style={{ background: step }} />
          ))}
        </span>
      </div>
    </div>
  )
}
