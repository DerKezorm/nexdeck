/**
 * Lines of the chronicle (roadmap M2) as the reader reads them. The server
 * keeps the facts (what, name, before, after, detail); the words are made
 * here, in the reader's language.
 */
import { tLabel } from '../i18n/texts'

export interface ChronicleLine {
  id?: number
  at?: string
  /** Epoch seconds. */
  when: number
  kind: string
  level: 'ok' | 'warn' | 'bad' | 'info' | string
  name: string
  before: string
  after: string
  detail: string
  board: string
  user?: string
  target?: { board: string; page: string; widget: number }
}

type Translate = (key: string, options?: Record<string, unknown>) => string

/** A moment as short as it can be said: the time today, "yesterday 22:10", or the date. */
export function momentOf(seconds: number, language: string, t: Translate, now = new Date()): string {
  const moment = new Date(seconds * 1000)
  const time = moment.toLocaleTimeString(language, { hour: '2-digit', minute: '2-digit' })
  const key = (one: Date) => `${one.getFullYear()}-${one.getMonth()}-${one.getDate()}`
  if (key(moment) === key(now)) return time
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (key(moment) === key(yesterday)) return t('attention.yesterday', { time })
  return `${moment.toLocaleDateString(language, { day: 'numeric', month: 'numeric' })} ${time}`
}

export function clockOf(seconds: number, language: string): string {
  return new Date(seconds * 1000).toLocaleTimeString(language, { hour: '2-digit', minute: '2-digit' })
}

/** What happened, in one sentence. */
export function lineText(line: ChronicleLine, t: Translate, language: string): string {
  const values = { name: line.name, before: line.before, after: line.after, detail: line.detail, user: line.user ?? '' }
  if (line.kind === 'card') return t(`chronicle.kind.card_${['warn', 'bad'].includes(line.after) ? line.after : 'ok'}`, values)
  // Roadmap M4: what will be full, or reach its red line, within two weeks.
  if (line.kind === 'forecast') return t(`chronicle.kind.forecast_${['full', 'warn'].includes(line.before) ? line.before : 'bad'}`, { ...values, count: Number(line.after) || 1 })
  if (line.kind === 'maintenance') {
    const until = line.after ? new Date(line.after) : null
    const time = until && !Number.isNaN(until.getTime()) ? until.toLocaleTimeString(language, { hour: '2-digit', minute: '2-digit' }) : ''
    return t('chronicle.kind.maintenance', { ...values, until: time })
  }
  return t(`chronicle.kind.${line.kind}`, { ...values, defaultValue: line.name })
}

/** The second line: why, or what it was before, when that says more than the sentence. */
export function lineDetail(line: ChronicleLine, t: Translate): string {
  if (line.kind === 'card' || line.kind === 'outage') return line.detail ? tLabel(line.detail) : ''
  if (line.kind === 'container_recreated') return line.before && line.before !== line.after ? `${line.before} → ${line.after}` : ''
  if (line.kind === 'signed_in') return [t(`chronicle.way.${line.after}`, { defaultValue: line.after }), line.detail].filter(Boolean).join(' · ')
  if (line.kind === 'sign_in_refused' || line.kind === 'connection_changed' || line.kind === 'card_definition_changed') return line.detail
  return ''
}

/** "Today", "Yesterday" or the date: the heading of a day on the page. */
export function dayOf(seconds: number, t: Translate, language: string, now = new Date()): string {
  const moment = new Date(seconds * 1000)
  const key = (one: Date) => `${one.getFullYear()}-${one.getMonth()}-${one.getDate()}`
  if (key(moment) === key(now)) return t('chronicle.today')
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (key(moment) === key(yesterday)) return t('chronicle.yesterday')
  return moment.toLocaleDateString(language, { weekday: 'long', day: 'numeric', month: 'long' })
}

/** The colour of a line's dot: the card's own for card lines, grey for the rest of what is merely news. */
export function lineStatus(line: ChronicleLine): string {
  return line.level === 'info' ? 'unknown' : line.level
}
