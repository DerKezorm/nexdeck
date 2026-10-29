/**
 * The arithmetic behind the calendar card's week and month grid: which days a
 * view shows, where a week starts, how the entries sit on their days.
 *
 * Days travel as "YYYY-MM-DD" text, the server's own days, and are turned into
 * a ``Date`` only to count with. ⚠️ Always through the local constructor
 * (`new Date(y, m, d)`) and never by adding milliseconds: a day is not 24 hours
 * long twice a year, and a week that begins on Monday must not drift to
 * Sunday night after the clocks change.
 */

import { isoOf } from './calendarDay'

export { isoOf }

export type GridView = 'week' | 'month'

export interface Entry {
  date: string
  title?: unknown
  time?: unknown
  /** The moment of a timed entry with its offset; `date` is then already the viewer's day (see `calendarDay`). */
  at?: unknown
  subtitle?: unknown
  source?: unknown
  slot?: unknown
  status?: unknown
  appointment?: unknown
  [key: string]: unknown
}

export interface Range {
  from: string
  to: string
}

/** A `Date` on the local midnight of a written day; an unreadable day is `null`. */
export function dayOf(iso: string): Date | null {
  const found = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  return found ? new Date(Number(found[1]), Number(found[2]) - 1, Number(found[3])) : null
}

export function addDays(date: Date, days: number): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days)
}

/**
 * The first day of the week as `Date.getDay()` counts it: 0 is Sunday, 1 Monday.
 *
 * German, Spanish, French and Italian weeks begin on Monday. English depends
 * on where the reader is (the United States begins on Sunday, Britain on
 * Monday), so it asks the browser's own region; a browser that cannot say
 * gets Monday, the ISO week.
 */
export function firstWeekday(language: string, browser: string = typeof navigator === 'undefined' ? '' : navigator.language): number {
  const locale = language.startsWith('en') ? browser || language : language
  try {
    const place = new Intl.Locale(locale) as Intl.Locale & { getWeekInfo?: () => { firstDay: number }; weekInfo?: { firstDay: number } }
    const info = place.getWeekInfo?.() ?? place.weekInfo
    if (info?.firstDay) return info.firstDay % 7
    if (language.startsWith('en')) return /-(US|CA)\b/.test(locale) ? 0 : 1
  } catch {
    // An odd locale tag: the ISO week below.
  }
  return 1
}

/** Seven days from the one on which the week of `anchor` begins. */
export function weekOf(anchor: Date, first: number): Date[] {
  const back = (anchor.getDay() - first + 7) % 7
  const start = addDays(anchor, -back)
  return Array.from({ length: 7 }, (_unused, index) => addDays(start, index))
}

/** The weeks that cover the month of `anchor`, whole weeks, four to six of them. */
export function monthWeeks(anchor: Date, first: number): Date[][] {
  const begin = new Date(anchor.getFullYear(), anchor.getMonth(), 1)
  const days = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0).getDate()
  const lead = (begin.getDay() - first + 7) % 7
  const rows = Math.ceil((lead + days) / 7)
  const start = addDays(begin, -lead)
  return Array.from({ length: rows }, (_row, row) => Array.from({ length: 7 }, (_day, day) => addDays(start, row * 7 + day)))
}

/** One page on: a month from the first of the month, a week from the day of the week. */
export function pageBy(view: GridView, anchor: Date, direction: 1 | -1): Date {
  return view === 'month' ? new Date(anchor.getFullYear(), anchor.getMonth() + direction, 1) : addDays(anchor, 7 * direction)
}

/** The first and the last day a page shows. */
export function spanOf(view: GridView, anchor: Date, first: number): [Date, Date] {
  if (view === 'month') {
    const weeks = monthWeeks(anchor, first)
    return [weeks[0][0], weeks[weeks.length - 1][6]]
  }
  const days = weekOf(anchor, first)
  return [days[0], days[6]]
}

/**
 * Whether a page reaches into what the server fetched. The arrows stop where
 * the entries stop: a month past that would show nothing and say nothing.
 * Without a range (an older server) every page is allowed.
 */
export function inRange(view: GridView, anchor: Date, first: number, range?: Range): boolean {
  if (!range) return true
  const [begin, end] = spanOf(view, anchor, first)
  return isoOf(end) >= range.from && isoOf(begin) <= range.to
}

/** The entries by day, each day's all-day entries first, then by the clock. */
export function byDay(entries: Entry[]): Map<string, Entry[]> {
  const days = new Map<string, Entry[]>()
  for (const entry of entries) {
    const key = String(entry.date ?? '').slice(0, 10)
    if (!days.has(key)) days.set(key, [])
    days.get(key)!.push(entry)
  }
  for (const list of days.values()) list.sort((a, b) => String(a.time ?? '').localeCompare(String(b.time ?? '')))
  return days
}

/** The colours a source can wear, in the order of the card's list of sources. */
const COLOURS = ['var(--nd-accent)', 'var(--nd-c-violet)', 'var(--nd-c-orange)', 'var(--nd-c-pink)', 'var(--nd-c-blue)', 'var(--nd-ok)']

export function colourOf(entry: Entry): string {
  const slot = typeof entry.slot === 'number' && entry.slot >= 0 ? Math.floor(entry.slot) : 0
  return COLOURS[slot % COLOURS.length]
}

/** The title of a page, in the language of the interface: "October 2026", or the days of a week with the year. */
export function titleOf(view: GridView, anchor: Date, first: number, language: string): string {
  if (view === 'month') return new Intl.DateTimeFormat(language, { month: 'long', year: 'numeric' }).format(anchor)
  const [begin, end] = spanOf(view, anchor, first)
  const format = new Intl.DateTimeFormat(language, { day: 'numeric', month: 'short', year: 'numeric' })
  return format.formatRange(begin, end)
}

/** "18:30" from the server in the way the interface's language writes a time. */
export function timeText(value: string, language: string): string {
  const [hours, minutes] = value.split(':').map(Number)
  if (!Number.isFinite(hours) || !Number.isFinite(minutes)) return value
  return new Date(2000, 0, 1, hours, minutes).toLocaleTimeString(language, { hour: 'numeric', minute: '2-digit' })
}
