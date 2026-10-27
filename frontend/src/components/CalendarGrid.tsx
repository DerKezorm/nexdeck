/**
 * The calendar card as a week or a month grid. Loaded only for a card that
 * chose one of them, so the list, which every calendar card starts as, costs
 * nothing more at the first load.
 *
 * The viewer pages and picks a day for themselves: neither is stored, and a
 * second browser on the same card is on its own page.
 */
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import {
  byDay,
  colourOf,
  dayOf,
  firstWeekday,
  inRange,
  isoOf,
  monthWeeks,
  pageBy,
  spanOf,
  timeText,
  titleOf,
  weekOf,
  type Entry,
  type GridView,
  type Range,
} from '../lib/calendarGrid'

export interface CalendarGridProps {
  items: Entry[]
  view: GridView
  range?: Range
  /** What the entry is called and where it is, already through showcase mode. */
  nameOf: (entry: Entry) => string
  placeOf: (entry: Entry) => string
  /** The name of the entry's source for the key; empty where showcase mode keeps it back. */
  sourceOf: (entry: Entry) => string
}

/** Entries on a month day: three dots on a narrow card, two bars with their titles on a wide one. */
const DOTS = 3
const BARS = 2

function startOfToday(): Date {
  const now = new Date()
  return new Date(now.getFullYear(), now.getMonth(), now.getDate())
}

export default function CalendarGrid({ items, view, range, nameOf, placeOf, sourceOf }: CalendarGridProps) {
  const { t, i18n } = useTranslation()
  const language = i18n.language
  const first = firstWeekday(language)
  const today = startOfToday()
  const [anchor, setAnchor] = useState(today)
  const [picked, setPicked] = useState<string | null>(null)
  const days = useMemo(() => byDay(items), [items])
  const todayIso = isoOf(today)
  const [begin, end] = spanOf(view, anchor, first)
  // The month the viewer is on, not the days its grid borrows from the next one: November's grid starts on a day in October.
  const here = view === 'month' ? anchor.getFullYear() === today.getFullYear() && anchor.getMonth() === today.getMonth() : isoOf(begin) <= todayIso && todayIso <= isoOf(end)
  const earlier = pageBy(view, anchor, -1)
  const later = pageBy(view, anchor, 1)
  const weekdays = weekOf(today, first)
  const dayName = new Intl.DateTimeFormat(language, { weekday: 'short' })
  const dayLong = new Intl.DateTimeFormat(language, { weekday: 'long', day: 'numeric', month: 'long' })

  function go(next: Date) {
    setAnchor(next)
    setPicked(null)
  }

  function pick(iso: string) {
    setPicked((current) => (current === iso ? null : iso))
  }

  function describe(date: Date): string {
    return t('calendar.dayEvents', { date: dayLong.format(date), count: days.get(isoOf(date))?.length ?? 0 })
  }

  const seen = new Map<number, Entry>()
  for (const entry of items) {
    const slot = typeof entry.slot === 'number' ? entry.slot : 0
    if (!seen.has(slot) && sourceOf(entry)) seen.set(slot, entry)
  }
  const legend = [...seen.entries()].sort(([a], [b]) => a - b).map(([, entry]) => entry)

  return (
    <div className="flex-1 min-h-0 flex flex-col px-2 pb-2 gap-1" data-testid="calendar-grid" data-view={view}>
      <div className="flex items-center gap-1">
        <button type="button" className="btn btn-xs btn-icon" aria-label={t('calendar.previous')} disabled={!inRange(view, earlier, first, range)} onClick={() => go(earlier)}>
          <ChevronLeft size={14} />
        </button>
        <div className="flex-1 min-w-0 text-center text-xs font-medium truncate capitalize" aria-live="polite" data-testid="calendar-title">
          {titleOf(view, anchor, first, language)}
        </div>
        {!here && (
          <button type="button" className="btn btn-xs" onClick={() => go(today)}>
            {t('card.today')}
          </button>
        )}
        <button type="button" className="btn btn-xs btn-icon" aria-label={t('calendar.next')} disabled={!inRange(view, later, first, range)} onClick={() => go(later)}>
          <ChevronRight size={14} />
        </button>
      </div>

      {view === 'month' ? (
        <>
          <div className="grid grid-cols-7 text-center text-[10px] uppercase tracking-wide text-faint" aria-hidden="true">
            {weekdays.map((day) => (
              <span key={day.getDay()} className="truncate">
                {dayName.format(day)}
              </span>
            ))}
          </div>
          <div className="flex-1 min-h-0 scroll grid grid-cols-7 gap-px [grid-auto-rows:minmax(34px,1fr)] @lg/card:[grid-auto-rows:minmax(58px,1fr)]" role="group" aria-label={titleOf(view, anchor, first, language)}>
            {monthWeeks(anchor, first).flat().map((day) => {
              const iso = isoOf(day)
              const entries = days.get(iso) ?? []
              const inMonth = day.getMonth() === anchor.getMonth()
              const isToday = iso === todayIso
              return (
                <button
                  type="button"
                  key={iso}
                  data-testid="calendar-day"
                  data-day={iso}
                  data-today={isToday ? 'true' : undefined}
                  aria-pressed={picked === iso}
                  aria-label={describe(day)}
                  onClick={() => pick(iso)}
                  className={`min-w-0 rounded-md p-0.5 flex flex-col items-center text-left border transition-colors ${
                    picked === iso ? 'border-accent bg-accent-soft' : isToday ? 'border-accent/60' : 'border-transparent hover:bg-surface-hover'
                  } ${inMonth ? '' : 'opacity-45'}`}
                >
                  <span className={`num text-[11px] leading-[18px] min-w-[18px] text-center rounded-full ${isToday ? 'bg-accent text-on-accent font-semibold' : 'text-muted'}`}>{day.getDate()}</span>
                  {entries.length > 0 && (
                    <>
                      <span className="flex flex-wrap justify-center gap-[3px] pt-0.5 @lg/card:hidden" data-testid="calendar-dots">
                        {entries.slice(0, DOTS).map((entry, index) => (
                          <i key={index} className="block w-[6px] h-[6px] rounded-full" style={{ background: colourOf(entry) }} />
                        ))}
                        {entries.length > DOTS && <b className="text-[9px] leading-[6px] font-medium text-muted">+{entries.length - DOTS}</b>}
                      </span>
                      <span className="hidden @lg/card:flex flex-col gap-px w-full pt-0.5 min-w-0" data-testid="calendar-bars">
                        {entries.slice(0, BARS).map((entry, index) => (
                          <span
                            key={index}
                            className="block truncate rounded-[3px] px-1 text-[10px] leading-[14px] text-ink"
                            style={{ background: `color-mix(in srgb, ${colourOf(entry)} 26%, transparent)`, borderLeft: `2px solid ${colourOf(entry)}` }}
                          >
                            {nameOf(entry)}
                          </span>
                        ))}
                        {entries.length > BARS && <b className="text-[10px] leading-[12px] font-medium text-muted px-1">+{entries.length - BARS}</b>}
                      </span>
                    </>
                  )}
                </button>
              )
            })}
          </div>
        </>
      ) : (
        <div className="flex-1 min-h-0 scroll grid grid-cols-1 @md/card:grid-cols-7 gap-1 content-start @md/card:content-stretch" role="group" aria-label={titleOf(view, anchor, first, language)}>
          {weekOf(anchor, first).map((day) => {
            const iso = isoOf(day)
            const entries = days.get(iso) ?? []
            const isToday = iso === todayIso
            return (
              <div key={iso} data-testid="calendar-day" data-day={iso} data-today={isToday ? 'true' : undefined} className={`min-w-0 rounded-md border p-1 flex @md/card:flex-col gap-1.5 ${picked === iso ? 'border-accent bg-accent-soft' : isToday ? 'border-accent/60' : 'border-line'}`}>
                <button
                  type="button"
                  aria-pressed={picked === iso}
                  aria-label={describe(day)}
                  onClick={() => pick(iso)}
                  className="flex-none w-11 @md/card:w-full flex @md/card:flex-col items-center gap-0.5 text-center cursor-pointer"
                >
                  <span className="text-[10px] uppercase tracking-wide text-faint">{dayName.format(day)}</span>
                  <span className={`num text-[12px] leading-[20px] min-w-[20px] rounded-full ${isToday ? 'bg-accent text-on-accent font-semibold' : 'text-ink'}`}>{day.getDate()}</span>
                </button>
                <div className="flex-1 min-w-0 flex flex-col gap-0.5">
                  {entries.map((entry, index) => (
                    <div
                      key={index}
                      className="rounded-[4px] px-1 py-0.5 text-[11px] leading-snug min-w-0"
                      style={{ background: `color-mix(in srgb, ${colourOf(entry)} 20%, transparent)`, borderLeft: `2px solid ${colourOf(entry)}` }}
                    >
                      {typeof entry.time === 'string' && <time className="num block text-[10px] text-muted tabular-nums">{timeText(entry.time, language)}</time>}
                      <span className="line-clamp-2 break-words font-medium">{nameOf(entry)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {picked && (
        <div className="flex-none max-h-[42%] scroll rounded-md border border-line px-2 py-1" data-testid="calendar-picked">
          <div className="text-[10px] uppercase tracking-wide text-faint mb-0.5">{dayLong.format(dayOf(picked) ?? today)}</div>
          {(days.get(picked) ?? []).length === 0 ? (
            <div className="text-xs text-faint py-1">{t('calendar.noEventsOnDay')}</div>
          ) : (
            (days.get(picked) ?? []).map((entry, index) => (
              <div key={index} className="flex items-center gap-2 py-0.5">
                <i className="block w-[8px] h-[8px] rounded-full flex-none" style={{ background: colourOf(entry) }} />
                {typeof entry.time === 'string' && <time className="num text-[11px] text-muted shrink-0 tabular-nums">{timeText(entry.time, language)}</time>}
                <span className="text-[13px] font-medium truncate flex-1">{nameOf(entry)}</span>
                <span className="text-[11px] text-muted truncate max-w-[45%]">{placeOf(entry)}</span>
              </div>
            ))
          )}
        </div>
      )}

      {legend.length > 1 && (
        <div className="hidden @md/card:flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-muted" data-testid="calendar-legend">
          {legend.map((entry) => (
            <span key={sourceOf(entry)} className="inline-flex items-center gap-1">
              <i className="block w-[7px] h-[7px] rounded-full" style={{ background: colourOf(entry) }} />
              {sourceOf(entry)}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
