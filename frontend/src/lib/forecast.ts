/**
 * Forecasts (roadmap M4): when a volume is full, when a number reaches its
 * red line, whether a backup gets slower. Worked out by the server once an
 * hour; the card only words it.
 */
import type { TFunction } from 'i18next'

export interface Forecast {
  kind: 'full' | 'level' | 'slower'
  metric: string
  row?: string | null
  /** Days until the limit (``full``, ``level``). */
  days?: number
  /** When the limit is reached, epoch seconds. */
  at?: number
  limit?: number
  /** Which line a ``level`` forecast reaches. */
  line?: 'bad' | 'warn'
  /** Change per day of the fitted line, and its value now. */
  slope?: number
  now?: number
  /** Seconds more a week (``slower``). */
  per_week?: number
  /** Told through the bell and the channels (under 14 days). */
  told?: boolean
}

/** Under this many days a forecast is red, as it is told. */
export const TELL_WITHIN_DAYS = 14

export type ForecastTone = 'bad' | 'warn' | 'quiet'

export function forecastTone(forecast: Forecast): ForecastTone {
  if (forecast.kind === 'slower') return 'quiet'
  if ((forecast.days ?? Infinity) < TELL_WITHIN_DAYS) return 'bad'
  return forecast.kind === 'level' ? 'warn' : 'quiet'
}

/** The sentence and, where there is one, the day it comes to. */
export function forecastWords(forecast: Forecast, t: TFunction, language: string): { text: string; when: string } {
  const count = Math.max(1, Math.round(forecast.days ?? 0))
  const row = forecast.row ?? ''
  const when = forecast.at ? t('forecast.around', { date: new Date(forecast.at * 1000).toLocaleDateString(language, { day: 'numeric', month: 'short' }) }) : ''
  if (forecast.kind === 'slower') {
    return { text: t('forecast.slower', { row, minutes: Math.max(1, Math.round((forecast.per_week ?? 0) / 60)) }), when: '' }
  }
  if (forecast.kind === 'full') return { text: row ? t('forecast.fullRow', { row, count }) : t('forecast.full', { count }), when }
  return { text: t(forecast.line === 'warn' ? 'forecast.warn' : 'forecast.bad', { count }), when }
}

/** Whether a chart line is the series the forecast was worked out on, and so can be carried on to its limit. */
export function carriesOn(forecast: Forecast | null | undefined, metric: string): forecast is Forecast {
  return Boolean(forecast && forecast.kind !== 'slower' && forecast.metric === metric && typeof forecast.limit === 'number' && typeof forecast.slope === 'number')
}
