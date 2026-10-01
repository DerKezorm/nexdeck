import { useTranslation } from 'react-i18next'

import { tLabel } from '../i18n/texts'
import type { WidgetData } from '../lib/types'
import { Rolled } from './Rolled'

/**
 * Where the power in a house goes, as one picture: solar above, the house in
 * the middle, the battery to the left, the grid to the right and the car
 * below, with dots running along each line the way the power runs, faster
 * the more there is.
 *
 * The numbers come as kilowatts with the signs the source uses: the grid is
 * positive while the house takes from it, the battery positive while it
 * gives to the house. A place the installation does not have is null and is
 * left out rather than drawn at zero.
 */
export interface Flow {
  solar?: number | null
  home?: number | null
  grid?: number | null
  battery?: number | null
  battery_soc?: number | null
  car?: number | null
}

/** Below this a line is idle: drawn, but nothing runs along it. */
const IDLE_KW = 0.05

/** Seconds for a dot to run one gap: fast for a lot of power, slow for a little. */
export function runSeconds(kilowatts: number): number {
  return Math.min(3, Math.max(0.5, 3 - Math.abs(kilowatts) / 2.5))
}

interface Line {
  key: string
  d: string
  /** Positive runs from the start of the path to its end. */
  power: number
  colour: string
}

const AT = { solar: [150, 32], home: [150, 112], battery: [46, 112], grid: [254, 112], car: [150, 192] } as const
const R = 22

function Node({ x, y, colour, children }: { x: number; y: number; colour: string; children: React.ReactNode }) {
  return (
    <g>
      <circle cx={x} cy={y} r={R} fill="color-mix(in srgb, var(--nd-text) 6%, var(--nd-bg))" stroke={colour} strokeWidth="2" />
      <g transform={`translate(${x - 12} ${y - 12})`} stroke={colour} fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        {children}
      </g>
    </g>
  )
}

function Value({ x, y, value, label, anchor = 'middle', unit = 'kW' }: { x: number; y: number; value: number; label: string; anchor?: 'start' | 'middle' | 'end'; unit?: string }) {
  return (
    <text x={x} y={y} textAnchor={anchor} className="fill-[var(--nd-text)]">
      <tspan className="num" fontSize="14" fontWeight="600">
        <Rolled value={Math.abs(value)} />
      </tspan>
      <tspan fontSize="11" className="fill-[var(--nd-text-muted)]"> {unit}</tspan>
      <tspan x={x} dy="14" fontSize="11" className="fill-[var(--nd-text-muted)]">
        {label}
      </tspan>
    </text>
  )
}

export function FlowCard({ data }: { data: WidgetData | undefined }) {
  const { t } = useTranslation()
  const flow = (data?.meta?.flow ?? {}) as Flow
  const has = (value: number | null | undefined): value is number => typeof value === 'number' && Number.isFinite(value)
  if (!has(flow.home)) return <div className="flex-1 flex items-center justify-center text-xs text-faint">{t('card.collecting')}</div>
  const lines: Line[] = []
  if (has(flow.solar)) lines.push({ key: 'solar', d: `M${AT.solar[0]} ${AT.solar[1] + R} V${AT.home[1] - R}`, power: flow.solar, colour: 'var(--nd-warn)' })
  // Discharging feeds the house, from the battery towards the middle; charging runs the other way.
  if (has(flow.battery)) lines.push({ key: 'battery', d: `M${AT.battery[0] + R} ${AT.battery[1]} H${AT.home[0] - R}`, power: flow.battery, colour: 'var(--nd-ok)' })
  // Taking from the grid runs towards the house; feeding in runs away from it.
  if (has(flow.grid)) lines.push({ key: 'grid', d: `M${AT.grid[0] - R} ${AT.grid[1]} H${AT.home[0] + R}`, power: flow.grid, colour: '#818cf8' })
  if (has(flow.car)) lines.push({ key: 'car', d: `M${AT.home[0]} ${AT.home[1] + R} V${AT.car[1] - R}`, power: flow.car, colour: 'var(--nd-accent)' })
  return (
    <div className="flex-1 min-h-0 px-2 pb-2" data-testid="flow">
      <svg viewBox="0 0 300 228" className="w-full h-full" role="img" aria-label={t('card.flow')}>
        {lines.map((line) => (
          <path key={`${line.key}-ground`} d={line.d} stroke="color-mix(in srgb, var(--nd-text) 12%, transparent)" strokeWidth="6" strokeLinecap="round" fill="none" />
        ))}
        {lines.map((line) =>
          Math.abs(line.power) < IDLE_KW ? null : (
            <path
              key={line.key}
              d={line.d}
              className={`nd-flow-run ${line.power < 0 ? 'nd-flow-back' : ''}`}
              stroke={line.colour}
              style={{ animationDuration: `${runSeconds(line.power)}s` }}
              data-testid={`flow-${line.key}`}
              data-way={line.power < 0 ? 'back' : 'on'}
            />
          ),
        )}
        {has(flow.solar) && (
          <>
            <Node x={AT.solar[0]} y={AT.solar[1]} colour="var(--nd-warn)">
              <circle cx="12" cy="12" r="4" fill="var(--nd-warn)" />
              <path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2" />
            </Node>
            <Value x={AT.solar[0] + R + 10} y={AT.solar[1] - 2} value={flow.solar} label={tLabel('Solar')} anchor="start" />
          </>
        )}
        <Node x={AT.home[0]} y={AT.home[1]} colour="var(--nd-accent)">
          <path d="M4 12l8-7 8 7v8H4z" />
        </Node>
        <Value x={AT.home[0] + R + 10} y={AT.home[1] + R + 4} value={flow.home} label={tLabel('House')} anchor="start" />
        {has(flow.battery) && (
          <>
            <Node x={AT.battery[0]} y={AT.battery[1]} colour="var(--nd-ok)">
              <rect x="6" y="5" width="12" height="16" rx="2" />
              <path d="M10 3h4" />
              <rect x="9" y={8 + 10 * (1 - Math.min(100, Math.max(0, flow.battery_soc ?? 50)) / 100)} width="6" height={Math.max(1, 10 * Math.min(100, Math.max(0, flow.battery_soc ?? 50)) / 100)} fill="var(--nd-ok)" stroke="none" />
            </Node>
            <Value x={AT.battery[0]} y={AT.battery[1] + R + 14} value={flow.battery} label={has(flow.battery_soc) ? `${tLabel('Battery')} · ${Math.round(flow.battery_soc)} %` : tLabel('Battery')} />
          </>
        )}
        {has(flow.grid) && (
          <>
            <Node x={AT.grid[0]} y={AT.grid[1]} colour="#818cf8">
              <path d="M13 3l-6 10h5l-1 8 6-10h-5z" fill="#818cf8" stroke="none" />
            </Node>
            <Value x={AT.grid[0]} y={AT.grid[1] + R + 14} value={flow.grid} label={tLabel(flow.grid < 0 ? 'Feed-in' : 'Grid')} />
          </>
        )}
        {has(flow.car) && (
          <>
            <Node x={AT.car[0]} y={AT.car[1]} colour="var(--nd-accent)">
              <path d="M4 15l2-6h12l2 6v4H4z" />
              <circle cx="8" cy="19" r="1.5" fill="var(--nd-accent)" />
              <circle cx="16" cy="19" r="1.5" fill="var(--nd-accent)" />
            </Node>
            <Value x={AT.car[0] + R + 10} y={AT.car[1] - 2} value={flow.car} label={tLabel('Car')} anchor="start" />
          </>
        )}
      </svg>
    </div>
  )
}
