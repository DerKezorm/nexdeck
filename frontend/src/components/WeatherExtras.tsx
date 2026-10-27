/**
 * What the weather card can show beyond today and the next days: an hourly
 * strip and the air (quality, UV, pollen). Loaded only when a card has asked
 * for one of them, so a plain weather card costs nothing more.
 */
import { Sunrise, Sunset } from 'lucide-react'
import { useTranslation } from 'react-i18next'

export interface HourRow {
  at: string
  temperature: number | null
  rain: number | null
  night: boolean
  condition?: string
}

export interface Hourly {
  hours: number
  items: HourRow[]
  sun: { index: number; kind: 'sunrise' | 'sunset'; time: string }[]
}

interface Level {
  value?: number
  level: string
}

export interface Air {
  aqi?: Level
  uv?: Level & { peak?: number | null }
  pollen?: { level: string; items: { kind: string; value: number; level: string }[] }
}

/** "16:00" from "2026-10-27T16:00" in the viewer's language: the place's own clock, never converted. */
export function hourText(at: string, language: string): string {
  const found = /T(\d\d):/.exec(at)
  if (!found) return at
  const hours = Number(found[1])
  return new Date(2000, 0, 1, hours).toLocaleTimeString(language, { hour: 'numeric' })
}

/** "06:55" as the viewer writes a time. */
export function clockText(time: string, language: string): string {
  const [hours, minutes] = time.split(':').map(Number)
  if (!Number.isFinite(hours) || !Number.isFinite(minutes)) return time
  return new Date(2000, 0, 1, hours, minutes).toLocaleTimeString(language, { hour: 'numeric', minute: '2-digit' })
}

/** The key of a level word: "very-poor" is `veryPoor`. */
export function levelKey(level: string): string {
  return level.replace(/-(\w)/g, (_match, letter: string) => letter.toUpperCase())
}

const TONES: Record<string, 'ok' | 'warn' | 'bad'> = {
  none: 'ok',
  good: 'ok',
  fair: 'ok',
  low: 'ok',
  moderate: 'warn',
  poor: 'warn',
  high: 'warn',
  'very-poor': 'bad',
  'very-high': 'bad',
  'extremely-poor': 'bad',
  extreme: 'bad',
}

/** Pollen has a lower threshold for "bad": a high count is already one. */
function toneOf(kind: 'aqi' | 'uv' | 'pollen', level: string): 'ok' | 'warn' | 'bad' {
  if (kind === 'pollen' && level === 'high') return 'bad'
  return TONES[level] ?? 'ok'
}

export function HourlyStrip({ hourly }: { hourly: Hourly }) {
  const { t, i18n } = useTranslation()
  const language = i18n.language
  const rows = hourly.items
  const temperatures = rows.map((row) => row.temperature).filter((value): value is number => value !== null)
  const low = Math.min(...temperatures)
  const span = Math.max(...temperatures) - low || 1
  const step = rows.length > 12 ? 3 : 2
  // Every hour's temperature on a wide card, every few hours on a narrow one.
  const wide = rows.length > 12 ? 'hidden @2xl/card:inline' : 'hidden @md/card:inline'
  const rains = rows.filter((row) => row.rain !== null)
  const peak = rains.reduce<HourRow | null>((best, row) => (best === null || (row.rain ?? 0) > (best.rain ?? 0) ? row : best), null)
  const sunAt = new Map(hourly.sun.map((event) => [event.index, event]))
  return (
    <div className="pt-1" data-testid="hourly-strip">
      <div role="img" aria-label={t('weather.hourlyLabel', { hours: rows.length })} className="flex gap-px h-[84px]">
        {rows.map((row, index) => {
          const event = sunAt.get(index)
          const shown = index % step === 0
          const label = row.temperature === null ? '' : `${Math.round(row.temperature)}°`
          const tip = `${hourText(row.at, language)}${label ? ` · ${label}` : ''}${row.rain !== null ? ` · ${Math.round(row.rain)} %` : ''}`
          return (
            <div
              key={row.at}
              data-testid="hourly-hour"
              data-night={row.night ? 'true' : 'false'}
              title={tip}
              className={`flex-1 min-w-0 flex flex-col items-center justify-end rounded-[5px] ${row.night ? 'bg-ink/[0.07]' : ''}`}
            >
              <span className="h-3 flex items-center text-warn" aria-hidden="true">
                {event?.kind === 'sunrise' ? <Sunrise size={11} data-testid="sun-sunrise" /> : event?.kind === 'sunset' ? <Sunset size={11} data-testid="sun-sunset" /> : null}
              </span>
              <span className={`num text-[9px] leading-none h-3 text-muted ${shown ? '' : wide}`} aria-hidden="true">
                {label}
              </span>
              <div className="w-full flex-1 min-h-0 flex items-end justify-center">
                {row.temperature !== null && (
                  <i
                    className={`block w-[70%] max-w-[18px] rounded-t-[3px] ${row.night ? 'bg-accent/45' : 'bg-accent/85'}`}
                    style={{ height: `${18 + (82 * (row.temperature - low)) / span}%` }}
                  />
                )}
              </div>
              <div className="w-full h-[14px] flex items-end justify-center pt-px">
                {row.rain !== null && row.rain > 0 && (
                  <i className="block w-[70%] max-w-[18px] rounded-[2px]" style={{ height: `${Math.max(2, (row.rain / 100) * 12)}px`, background: 'var(--nd-c-blue)', opacity: 0.35 + row.rain / 160 }} />
                )}
              </div>
            </div>
          )
        })}
      </div>
      <div className="flex gap-px" aria-hidden="true">
        {rows.map((row, index) => (
          <span key={row.at} className="flex-1 min-w-0 text-center text-[9px] text-faint leading-4 whitespace-nowrap overflow-visible">
            {index % step === 0 ? hourText(row.at, language) : ''}
          </span>
        ))}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-muted pt-1">
        {hourly.sun.map((event) => (
          <span key={`${event.kind}${event.index}`} className="inline-flex items-center gap-1">
            {event.kind === 'sunrise' ? <Sunrise size={11} className="text-warn" /> : <Sunset size={11} className="text-warn" />}
            {t(`weather.${event.kind}`)} {clockText(event.time, language)}
          </span>
        ))}
        {peak && (peak.rain ?? 0) >= 20 ? (
          <span>{t('weather.rainUpTo', { percent: Math.round(peak.rain ?? 0), time: hourText(peak.at, language) })}</span>
        ) : rains.length > 0 ? (
          <span>{t('weather.noRain')}</span>
        ) : null}
      </div>
    </div>
  )
}

export function AirChips({ air, unavailable }: { air?: Air; unavailable?: boolean }) {
  const { t, i18n } = useTranslation()
  const level = (word: string) => t(`weather.level.${levelKey(word)}`)
  const chips: { key: string; kind: 'aqi' | 'uv' | 'pollen'; level: string; text: string }[] = []
  if (air?.aqi) chips.push({ key: 'aqi', kind: 'aqi', level: air.aqi.level, text: `${t('weather.aqi')} ${air.aqi.value} · ${level(air.aqi.level)}` })
  if (air?.uv) {
    const peak = air.uv.peak != null ? ` · ${t('weather.uvPeak', { value: air.uv.peak.toLocaleString(i18n.language) })}` : ''
    chips.push({ key: 'uv', kind: 'uv', level: air.uv.level, text: `${t('weather.uv')} ${air.uv.value?.toLocaleString(i18n.language)} · ${level(air.uv.level)}${peak}` })
  }
  if (air?.pollen) {
    const named = air.pollen.items.map((item) => `${t(`weather.pollenKinds.${item.kind}`)} ${item.value}`).join(', ')
    chips.push({ key: 'pollen', kind: 'pollen', level: air.pollen.level, text: `${t('weather.pollen')} ${named || level('none')}` })
  }
  if (!chips.length && !unavailable) return null
  return (
    <div className="flex flex-wrap gap-1.5 pt-1.5" data-testid="air-chips">
      {chips.map((chip) => (
        <span className="chip" key={chip.key} data-kind={chip.key} data-level={chip.level}>
          <span className="dot self-center" data-status={toneOf(chip.kind, chip.level)} />
          {chip.text}
        </span>
      ))}
      {unavailable && <span className="text-[10px] text-faint self-center">{t('weather.airUnavailable')}</span>}
    </div>
  )
}

export default function WeatherExtras({ hourly, air, unavailable }: { hourly?: Hourly; air?: Air; unavailable?: boolean }) {
  return (
    <>
      {hourly && hourly.items.length > 0 && <HourlyStrip hourly={hourly} />}
      <AirChips air={air} unavailable={unavailable} />
    </>
  )
}
