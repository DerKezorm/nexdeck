import { cardStatus } from './cardStatus'
import type { WidgetData, WidgetView } from './types'

/**
 * Whether a card is left out of the phone's stack.
 *
 * Only where the board stacks its cards: the wide board, a tablet and a wall
 * display keep every card. A card switched off for the phone comes back while
 * it is red, unless that is switched off too: a phone is where one looks when
 * something is wrong, and the card that says so must not be the one missing.
 * Red is what its frame shows (``cardStatus``), so a card with its findings
 * switched off stays away as long as its frame stays quiet.
 */
export function hiddenOnPhone(widget: WidgetView, data: WidgetData | undefined): boolean {
  if (widget.options?.phone_hide !== true) return false
  if (widget.options?.phone_show_red === false) return true
  return cardStatus(widget, data) !== 'bad'
}
