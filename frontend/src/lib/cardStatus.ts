import type { Status, WidgetData, WidgetView } from './types'

/** The attention card keeps its old kind, from the time it was called Problems. */
const ATTENTION = 'core.problems'

/**
 * How a card stands, as its frame shows it.
 *
 * A failed fetch is red. A warning or an alarm the service reports counts
 * only where the card's findings are switched on: a card that shouts by
 * default means a board full of colour nobody reads any more, and a card that
 * is quiet until asked keeps the colour meaningful. Cards made before that
 * carry the old answer, written down by migration 8.
 *
 * The attention card is the exception: saying what is yellow and red is all
 * it is for, so its colour always shows.
 *
 * The card frame and the background behind the board both ask this, so the
 * room turns red only for what a card shows as red.
 */
export function cardStatus(widget: WidgetView, data: WidgetData | undefined): Status {
  if (data?.error) return 'bad'
  const reported = data?.status ?? 'unknown'
  const showFindings = widget.options?.show_findings === true || widget.kind === ATTENTION
  return !showFindings && (reported === 'warn' || reported === 'bad') ? 'ok' : reported
}

/**
 * Whether any card of these is red: what tints the background behind them.
 * Not the attention card: it repeats the others, and a card that stays quiet
 * on its own would turn the room red through it.
 */
export function anyCardDown(widgets: WidgetView[], data: Record<number, WidgetData | undefined>): boolean {
  return widgets.some((widget) => widget.kind !== ATTENTION && cardStatus(widget, data[widget.id]) === 'bad')
}
