/**
 * The day a calendar entry belongs to for whoever looks at the card.
 *
 * An entry with a time of day may carry `at`, its moment with an offset. The
 * server cannot know the viewer's zone, so its `date` is the day on its own
 * clock; the browser puts the moment on its own calendar instead. A show at
 * seven in the evening in Chicago is past midnight in UTC, and was listed
 * under the next day (#56). Entries without `at` (a release date, an all-day
 * appointment, a time written without a zone) keep the day they came with.
 */

const pad = (value: number) => String(value).padStart(2, '0')

/** The day as the server writes it, from the local calendar of a `Date`. */
export function isoOf(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** The entry on the viewer's own day, and its time on the viewer's clock when it shows one. */
export function onViewersDay<T extends Record<string, unknown>>(entry: T): T {
  if (typeof entry.at !== 'string') return entry
  const moment = new Date(entry.at)
  if (Number.isNaN(moment.getTime())) return entry
  const time = typeof entry.time === 'string' ? { time: `${pad(moment.getHours())}:${pad(moment.getMinutes())}` } : {}
  return { ...entry, date: isoOf(moment), ...time }
}

const dayKey = (entry: Record<string, unknown>) => String(entry.date ?? '').slice(0, 10)

/**
 * What the list shows: from the viewer's today on, by day, each day's all-day
 * entries first, then by the clock. The server sends from its own today; a
 * viewer whose day has already turned leaves out what is yesterday for them.
 */
export function upcomingByDay<T extends Record<string, unknown>>(entries: T[], now: Date = new Date()): T[] {
  const today = isoOf(now)
  return entries
    .map(onViewersDay)
    .filter((entry) => dayKey(entry) >= today)
    .sort((a, b) => dayKey(a).localeCompare(dayKey(b)) || String(a.time ?? '').localeCompare(String(b.time ?? '')))
}
