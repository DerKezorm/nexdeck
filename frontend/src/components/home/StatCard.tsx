import { useQuery } from '@tanstack/react-query'
import { Activity, Palette, Trash2 } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { get } from '../../api/client'
import {
  reading, STAT_PERIODS, STAT_START, STAT_STYLES, type HomeStat, type StatAnswer, type StatLine, type StatPeriod, type StatPoint, type StatStyle,
} from '../../lib/home'
import { HEATING } from './ClimateControl'
import { StatChart, timeLabels, useWidth, type ChartLine } from './StatChart'

/** The colours of a card's lines, the first for one sensor alone; heat, violet, the accent, then three more. */
export const STAT_COLOURS = [HEATING, 'hsl(268 75% 66%)', 'var(--nd-accent)', 'rgb(74, 222, 128)', 'rgb(244, 114, 182)', 'rgb(250, 204, 21)']
const COUNTER = 'rgb(74, 222, 128)'
const FADED = 'color-mix(in srgb, var(--nd-text) 38%, transparent)'

/** How long a step of a counter's bars is, for drawing them as wide as their time. */
const STEP_MS: Record<string, number> = { '5minute': 300_000, hour: 3_600_000, day: 86_400_000, week: 7 * 86_400_000, month: 30.4 * 86_400_000 }

/** The colour a single sensor is drawn in: warm for a temperature, the accent for humidity, violet for the rest. */
function colourOf(line: StatLine): string {
  if (line.kind === 'sum') return COUNTER
  if (line.unit === '°C' || line.unit === '°F') return HEATING
  return line.unit === '%' ? 'var(--nd-accent)' : 'hsl(268 75% 66%)'
}

const means = (points: StatPoint[]): [number, number][] => points.map((point) => [point[0], point[1]])

interface Props {
  element: HomeStat
  pageId: number
  arranging: boolean
  /** On a phone: as wide as the screen. */
  wide: boolean
  size: { width: number; height: number }
  onRemove: () => void
  onStyle: (style: StatStyle) => void
  onSensors: () => void
}

/**
 * A statistics card, in one of the six styles of its board of sketches. The
 * points come from Home Assistant through the server and are asked again
 * every minute; the period is the viewer's to switch and is not kept.
 */
export function StatCard({ element, pageId, arranging, wide, size, onRemove, onStyle, onSensors }: Props) {
  const { t, i18n } = useTranslation()
  const periods = STAT_PERIODS[element.style] ?? STAT_PERIODS.line
  const [period, setPeriod] = useState<StatPeriod>(STAT_START[element.style] ?? periods[0])
  const [choosing, setChoosing] = useState(false)
  useEffect(() => {
    if (!periods.includes(period)) setPeriod(STAT_START[element.style] ?? periods[0])
  }, [periods, period, element.style])
  const shownPeriod = periods.includes(period) ? period : STAT_START[element.style] ?? periods[0]
  const sensorsKey = element.sensors.map((sensor) => sensor.entity_id).join(',')
  const stats = useQuery({
    queryKey: ['home-stat', pageId, element.id, shownPeriod, sensorsKey],
    queryFn: () => get<StatAnswer>(`/pages/${pageId}/home/stats/${element.id}?period=${shownPeriod}`),
    refetchInterval: 60_000,
    staleTime: 50_000,
  })
  const [box, measured] = useWidth(size.width, wide)
  const width = wide ? measured : size.width
  const answer = stats.data
  const first = answer?.series[0]
  const line = first && !first.missing ? first : null
  const title = element.title || line?.name || element.sensors[0]?.name || ''
  const small = element.style === 'small'
  const chartW = Math.max(60, width - 28)
  const chartH = Math.max(40, size.height - (small ? 0 : 84))
  const labels = answer ? timeLabels(shownPeriod, answer.start, answer.end, answer.zone, i18n.language, chartW, t('homePage.stats.now')) : []
  const tick = (value: number) => (line && (line.unit === '°C' || line.unit === '°F') ? `${Math.round(value)}°` : String(Math.round(value)))
  /** A measurement's line ends where it stands now, not at the last step Home Assistant has closed. */
  const toNow = (one: StatLine): [number, number][] =>
    one.kind === 'mean' && one.current !== null && !one.unavailable && answer && answer.now <= answer.end ? [...means(one.points), [answer.now, one.current]] : means(one.points)

  let body: ReactNode = null
  let foot: ReactNode = null
  if (stats.isLoading) body = <div className="h-full grid place-items-center text-xs text-muted">…</div>
  else if (stats.isError || !answer) body = <Empty title={t('homePage.stats.failed')} />
  else if (answer.problem) body = <Empty title={t(`homePage.problems.${answer.problem.code}`, { defaultValue: answer.problem.message })} />
  else if (!first || first.missing) body = <Empty title={t('homePage.stats.missing', { name: element.sensors[0]?.name ?? '' })} />
  else if (line && line.points.length === 0 && !(element.style === 'rooms' && answer.series.some((one) => !one.missing && one.points.length))) {
    body = line.source === 'history'
      ? <Empty title={t('homePage.stats.noStatsTitle')} text={t('homePage.stats.noStats', { name: line.name })} />
      : <Empty title={t('homePage.stats.noDataTitle')} text={t('homePage.stats.noData')} />
  } else if (line) {
    const from = answer.start
    const to = answer.end
    const chart = (extra: Partial<Parameters<typeof StatChart>[0]>) => (
      <StatChart width={chartW} height={chartH} from={from} to={to} labels={labels} tick={tick} {...extra} />
    )
    const counterBars = (one: StatLine) => {
      const step = STEP_MS[one.step] ?? 3_600_000
      const start = one.points[0]?.[0] ?? from
      return { from: start, to: Math.max(start + step, (one.points.at(-1)?.[0] ?? start) + step), bars: { points: means(one.points), colour: COUNTER, step } }
    }
    if (line.kind === 'sum' && element.style !== 'rooms' && element.style !== 'compare') {
      const drawn = counterBars(line)
      const per = line.step === 'month' ? 'month' : line.step === 'day' ? 'day' : 'hour'
      body = small ? null : <StatChart width={chartW} height={chartH} from={drawn.from} to={drawn.to} bars={drawn.bars} tick={(value) => String(Math.round(value))}
        labels={answer ? timeLabels(shownPeriod, drawn.from, drawn.to, answer.zone, i18n.language, chartW, t(`homePage.stats.latest.${per}`)) : []} />
      foot = <Stats items={[[t('homePage.stats.total'), reading(line.total, line.unit)], [t(`homePage.stats.perStep.${per}`), reading(line.mean, line.unit)],
        [t(`homePage.stats.latest.${per}`), reading(line.latest, line.unit)]]} />
    } else if (element.style === 'rooms') {
      const shown = answer.series.map((one, index) => ({ one, colour: STAT_COLOURS[index % STAT_COLOURS.length] }))
      body = chart({ lines: shown.flatMap(({ one, colour }) => (one.missing ? [] : [{ points: toNow(one), colour, width: 1.6, label: one.name } satisfies ChartLine])) })
      foot = (
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11.5px] text-muted mt-1.5" data-legend>
          {shown.map(({ one, colour }, index) => (
            <span key={index} className={`whitespace-nowrap ${one.missing ? 'text-warn' : ''}`}>
              <i className="inline-block w-2.5 h-[3px] rounded align-middle mr-1.5" style={{ background: one.missing ? 'var(--nd-warn)' : colour }} />
              {one.missing ? t('homePage.stats.missing', { name: element.sensors[index]?.name ?? '' }) : `${one.name} ${reading(one.current ?? one.mean, one.unit)}`}
            </span>
          ))}
        </div>
      )
    } else if (element.style === 'band') {
      body = chart({ band: { points: line.points.filter((point): point is [number, number, number, number] => point.length === 4).map(([t0, , low, high]) => [t0, low, high]), colour: colourOf(line) },
        lines: [{ points: means(line.points), colour: colourOf(line), label: line.name }] })
      const date = new Intl.DateTimeFormat(i18n.language, { timeZone: answer.zone, day: 'numeric', month: 'numeric' })
      foot = <Stats items={[[t('homePage.stats.mean'), reading(line.mean, line.unit)],
        [t('homePage.stats.lowest'), line.low ? t('homePage.stats.on', { value: reading(line.low[0], line.unit), date: date.format(new Date(line.low[1])) }) : '–'],
        [t('homePage.stats.highest'), line.high ? t('homePage.stats.on', { value: reading(line.high[0], line.unit), date: date.format(new Date(line.high[1])) }) : '–']]} />
    } else if (element.style === 'bars') {
      const step = STEP_MS[line.step] ?? 86_400_000
      body = chart({ bars: { points: means(line.points), colour: colourOf(line), step }, from: line.points[0]?.[0] ?? from, to: (line.points.at(-1)?.[0] ?? from) + step })
      foot = <Stats items={[[t('homePage.stats.mean'), reading(line.mean, line.unit)], [t('homePage.stats.low'), reading(line.low?.[0], line.unit)], [t('homePage.stats.high'), reading(line.high?.[0], line.unit)]]} />
    } else if (element.style === 'compare') {
      const week = shownPeriod === 'week'
      const before = line.previous ?? []
      body = line.kind === 'sum'
        ? chart({ bars: { points: means(line.points), colour: COUNTER, step: STEP_MS[line.step] ?? 3_600_000 }, lines: [{ points: means(before), colour: FADED, width: 1.4, dash: true }] })
        : chart({ lines: [{ points: means(before), colour: FADED, width: 1.4, dash: true, label: t(week ? 'homePage.stats.lastWeek' : 'homePage.stats.yesterday') },
          { points: toNow(line), colour: colourOf(line), dot: true, label: t(week ? 'homePage.stats.thisWeek' : 'homePage.stats.today') }] })
      const value = (summary: { mean: number | null; total: number | null } | undefined) => reading(line.kind === 'sum' ? summary?.total : summary?.mean, line.unit)
      const word = line.kind === 'sum' ? 'totalOf' : 'meanOf'
      foot = (
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11.5px] text-muted mt-1.5" data-legend>
          <span><i className="inline-block w-2.5 h-[3px] rounded align-middle mr-1.5" style={{ background: colourOf(line) }} />
            {t(`homePage.stats.${word}`, { label: t(week ? 'homePage.stats.thisWeek' : 'homePage.stats.today'), value: value(line) })}</span>
          <span><i className="inline-block w-2.5 h-[3px] rounded align-middle mr-1.5" style={{ background: FADED }} />
            {t(`homePage.stats.${word}`, { label: t(week ? 'homePage.stats.lastWeek' : 'homePage.stats.yesterday'), value: value(line.previous_summary) })}</span>
        </div>
      )
    } else if (!small) {
      body = chart({ lines: [{ points: toNow(line), colour: colourOf(line), fill: true, dot: true, label: line.name }] })
      foot = <Stats items={[[t('homePage.stats.now'), reading(line.current, line.unit)], [t('homePage.stats.low'), reading(line.low?.[0], line.unit)],
        [t('homePage.stats.high'), reading(line.high?.[0], line.unit)], [t('homePage.stats.mean'), reading(line.mean, line.unit)]]} />
    }
  }

  const tools = arranging && (
    <>
      <span className="home-grip home-grip-corner" data-resize="both" aria-hidden title={t('homePage.stats.dragSize')} />
      <span className="absolute -top-3 -right-3 z-10 flex gap-1" data-element-tool>
        <button type="button" className="btn btn-icon h-6 w-6 rounded-full glass-strong" onClick={() => setChoosing((open) => !open)}
          aria-label={t('homePage.chooseStyle')} title={t('homePage.chooseStyle')} aria-haspopup="menu" aria-expanded={choosing}>
          <Palette size={12} />
        </button>
        <button type="button" className="btn btn-icon h-6 w-6 rounded-full glass-strong" onClick={onSensors} aria-label={t('homePage.stats.chooseSensors')} title={t('homePage.stats.chooseSensors')}>
          <Activity size={12} />
        </button>
        <button type="button" className="btn btn-icon btn-danger h-6 w-6 rounded-full glass-strong" onClick={onRemove} aria-label={t('homePage.stats.remove')} title={t('homePage.stats.remove')}>
          <Trash2 size={12} />
        </button>
      </span>
      {choosing && (
        <div className="absolute left-0 top-full mt-2 z-30 glass-strong rounded-xl p-1.5 shadow-2xl grid grid-cols-2 gap-1 w-64" role="menu" aria-label={t('homePage.chooseStyle')} data-element-tool>
          {STAT_STYLES.map((style) => (
            <button key={style} type="button" role="menuitemradio" aria-checked={element.style === style}
              className={`text-left text-[13px] px-2.5 py-1.5 rounded-lg ${element.style === style ? 'bg-[var(--nd-accent-soft)] text-accent font-medium' : 'hover:bg-[var(--nd-surface-hover)]'}`}
              onClick={() => {
                setChoosing(false)
                onStyle(style)
              }}>
              {t(`homePage.stats.styles.${style}`)}
            </button>
          ))}
        </div>
      )}
    </>
  )

  if (small) {
    const values = line ? means(line.points) : []
    return (
      <div className="relative w-fit">
        <div ref={box} className="stat-card stat-small" style={{ width: wide ? undefined : size.width, height: size.height }} data-stat={element.id} data-style="small">
          {values.length > 1 && (
            <div className="absolute inset-x-0 bottom-0 opacity-90 pointer-events-none">
              <StatChart width={width} height={Math.min(40, Math.round(size.height / 3))} from={answer!.start} to={answer!.end} plain
                lines={[{ points: toNow(line!), colour: colourOf(line!), fill: true, width: 1.6 }]} />
            </div>
          )}
          <div className="relative">
            <div className="text-[11.5px] text-muted truncate">{title}</div>
            {body ?? (
              <>
                <div className="num text-2xl font-semibold leading-tight" data-value>{line ? reading(line.kind === 'sum' ? line.total : line.current, line.unit) : '–'}</div>
                {line && line.kind === 'mean' && <div className="num text-[10px] text-faint">{`24 h ${reading(line.low?.[0], line.unit)} · ${reading(line.high?.[0], line.unit)}`}</div>}
              </>
            )}
          </div>
        </div>
        {tools}
      </div>
    )
  }

  return (
    <div className={`relative ${wide ? 'w-full min-w-0' : 'w-fit'}`}>
      <div ref={box} className="stat-card" style={{ width: wide ? undefined : size.width, height: size.height }} data-stat={element.id} data-style={element.style}>
        <div className="flex items-baseline gap-2 min-w-0">
          <b className="text-[13px] font-semibold truncate">{title}</b>
          {line?.source === 'history' && <small className="text-[11px] text-faint whitespace-nowrap">{t('homePage.stats.fromHistory')}</small>}
          {periods.length > 1 && (
            <span className="ml-auto flex gap-0.5 flex-none" role="radiogroup" aria-label={t('homePage.stats.period')}>
              {periods.map((one) => (
                <button key={one} type="button" role="radio" aria-checked={one === shownPeriod}
                  className={`text-[10.5px] px-2 py-0.5 rounded-full ${one === shownPeriod ? 'bg-[var(--nd-accent-soft)] text-accent font-medium' : 'text-muted hover:text-[var(--nd-text)]'}`}
                  onClick={() => setPeriod(one)} onPointerDown={(event) => event.stopPropagation()}>
                  {t(`homePage.stats.periods.${one}`)}
                </button>
              ))}
            </span>
          )}
        </div>
        <div className="mt-1.5" style={{ height: chartH }}>{body}</div>
        {foot}
      </div>
      {tools}
    </div>
  )
}

function Empty({ title, text }: { title: string; text?: string }) {
  return (
    <div className="h-full grid place-items-center text-center text-xs text-muted px-2" data-empty>
      <div>
        <b className="text-[var(--nd-text)] font-semibold">{title}</b>
        {text && <><br />{text}</>}
      </div>
    </div>
  )
}

function Stats({ items }: { items: [string, string][] }) {
  return (
    <div className="num flex flex-wrap gap-x-4 gap-y-0.5 mt-1.5 text-[11.5px] text-muted" data-stats>
      {items.map(([label, value]) => (
        <span key={label} className="whitespace-nowrap">{label} <b className="text-[var(--nd-text)] font-semibold">{value}</b></span>
      ))}
    </div>
  )
}
