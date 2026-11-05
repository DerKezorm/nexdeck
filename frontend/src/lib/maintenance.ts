import type { WidgetView } from './types'

/** Who the maintenance of a card is for: an app tile itself, any other card its connection. */
export function maintenanceTarget(widget: WidgetView): { integration_id: number } | { widget_id: number } | null {
  if (widget.kind === 'core.app') return widget.health ? { widget_id: widget.id } : null
  return widget.integration_id != null ? { integration_id: widget.integration_id } : null
}

/** A weekly maintenance as the server keeps it (``/api/v1/maintenance/plans``). Days run from Monday 0 to Sunday 6. */
export interface MaintenancePlan {
  id: number
  integration_id: number | null
  widget_id: number | null
  name: string
  days: number[]
  starts: string
  minutes: number
  zone: string
  next_starts_at: string | null
  next_ends_at: string | null
}

/** The path that lists the weekly maintenance of a connection or a tile. */
export function plansPath(target: { integration_id: number } | { widget_id: number }): string {
  return 'integration_id' in target ? `/maintenance/plans?integration_id=${target.integration_id}` : `/maintenance/plans?widget_id=${target.widget_id}`
}

/** The short names of the weekdays, Monday first, in the language of the page. */
export function weekdayNames(language: string): string[] {
  const format = new Intl.DateTimeFormat(language, { weekday: 'short' })
  // 2 November 2026 is a Monday.
  return Array.from({ length: 7 }, (_, day) => format.format(new Date(2026, 10, 2 + day, 12)))
}

/** "03:00" plus a length, as the clock shows the end. */
export function endOnTheClock(starts: string, minutes: number): string {
  const [hour, minute] = starts.split(':').map(Number)
  const total = (hour * 60 + minute + minutes) % (24 * 60)
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
}

/** The time zone of this browser, which a weekly maintenance keeps to. */
export function browserZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || ''
  } catch {
    return ''
  }
}
