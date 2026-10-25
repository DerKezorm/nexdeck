/**
 * The texts of a custom card, and its finished values in the language of whoever looks.
 *
 * A text in a card definition is the author's own: one string, or one string per
 * language (`{ en: 'Queue', de: 'Warteschlange' }`). The viewer gets their language,
 * else English, else the first one written. nexdeck's own table of translations is
 * never applied to it (KARTEN-1 AC-5, AC-6): a card that says "Queue" in German
 * says "Queue", because the author wrote it so.
 */
import { tLabel } from '../i18n/texts'

export type CardText = string | Record<string, string>

/** What the server hands over for one value of a custom card (the pipeline's `Shown`). */
export interface CardShown {
  value: number | string | boolean | null
  text: string
  format: string
  digits?: number | null
  label?: CardText | null
  unit?: CardText | null
  status?: string | null
}

const NOTHING = '–'

function written(text: string | undefined): string | null {
  return text !== undefined && text.trim() !== '' ? text : null
}

/** The text in `lang` (`de`, `de-AT`), else English, else the first text that is not empty; `''` when there is none. */
export function pickText(text: CardText | null | undefined, lang: string): string {
  if (text === null || text === undefined) return ''
  if (typeof text === 'string') return text
  const byCode = new Map(Object.entries(text).map(([code, value]) => [code.toLowerCase(), value]))
  const wanted = lang.toLowerCase()
  return (
    written(byCode.get(wanted)) ??
    written(byCode.get(wanted.split('-')[0])) ??
    written(byCode.get('en')) ??
    [...byCode.values()].map(written).find((value) => value !== null) ??
    ''
  )
}

/**
 * A text on a card. A card of the author's own (`custom`) shows exactly what the author wrote in the viewer's
 * language; every other card passes its English wording through the table of translations.
 */
export function cardLabel(text: CardText | null | undefined, lang: string, custom: boolean): string {
  const picked = pickText(text, lang)
  return custom ? picked : tLabel(picked)
}

const SECOND = 1000

function agoText(moment: Date, lang: string, now: number): string {
  const seconds = Math.round((moment.getTime() - now) / SECOND)
  const format = new Intl.RelativeTimeFormat(lang, { numeric: 'auto' })
  const minutes = Math.round(seconds / 60)
  if (Math.abs(minutes) < 60) return format.format(minutes, 'minute')
  const hours = Math.round(minutes / 60)
  if (Math.abs(hours) < 48) return format.format(hours, 'hour')
  return format.format(Math.round(hours / 24), 'day')
}

/**
 * A finished value as the viewer reads it: numbers and times in the format of their language and zone (KARTEN-5 EC-10).
 * What the server already wrote out (bytes, rates, durations, plain text) is kept as it is. The unit of the card follows.
 */
export function formatShown(shown: CardShown, lang: string, options: { zone?: string; now?: number } = {}): string {
  const { value } = shown
  let text = shown.text
  if (value !== null && value !== undefined) {
    if ((shown.format === 'number' || shown.format === 'percent') && typeof value === 'number') {
      const digits = shown.digits ?? undefined
      const style = shown.format === 'percent' ? 'percent' : 'decimal'
      text = new Intl.NumberFormat(lang, {
        style,
        minimumFractionDigits: digits ?? 0,
        maximumFractionDigits: digits ?? 2,
      }).format(style === 'percent' ? value / 100 : value)
    } else if (['date', 'datetime', 'time', 'ago'].includes(shown.format) && typeof value === 'string') {
      const moment = new Date(value)
      if (!Number.isNaN(moment.getTime())) {
        const timeZone = options.zone
        if (shown.format === 'ago') text = agoText(moment, lang, options.now ?? Date.now())
        else if (shown.format === 'date') text = new Intl.DateTimeFormat(lang, { dateStyle: 'medium', timeZone }).format(moment)
        else if (shown.format === 'time') text = new Intl.DateTimeFormat(lang, { timeStyle: 'short', timeZone }).format(moment)
        else text = new Intl.DateTimeFormat(lang, { dateStyle: 'medium', timeStyle: 'short', timeZone }).format(moment)
      }
    }
  } else {
    text = NOTHING
  }
  const unit = pickText(shown.unit, lang)
  return unit && value !== null && value !== undefined && shown.format !== 'percent' ? `${text} ${unit}` : text
}
