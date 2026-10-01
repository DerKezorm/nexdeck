import type { Status, WidgetData, WidgetView } from './types'

/**
 * How a card stands, as its frame shows it.
 *
 * A failed fetch is red. A warning or an alarm the service reports counts
 * only where the card's findings are switched on: a card that shouts by
 * default means a board full of colour nobody reads any more, and a card that
 * is quiet until asked keeps the colour meaningful. Cards made before that
 * carry the old answer, written down by migration 8.
 *
 * The card frame and the background behind the board both ask this, so the
 * room turns red only for what a card shows as red.
 */
export function cardStatus(widget: WidgetView, data: WidgetData | undefined): Status {
  if (data?.error) return 'bad'
  const reported = data?.status ?? 'unknown'
  const showFindings = widget.options?.show_findings === true
  return !showFindings && (reported === 'warn' || reported === 'bad') ? 'ok' : reported
}

/** Whether any card of these is red: what tints the background behind them. */
export function anyCardDown(widgets: WidgetView[], data: Record<number, WidgetData | undefined>): boolean {
  return widgets.some((widget) => cardStatus(widget, data[widget.id]) === 'bad')
}
