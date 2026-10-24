/**
 * Key figures: number cards of a page drawn as tiles of one grid. The card
 * holds them like a group (``options.cards``); each keeps its own settings
 * and its own data, and the grid only draws them.
 */
import { cardStatus } from './cardStatus'
import { heldBy } from './groups'
import { recordedMetrics } from './recorded'
import type { Status, WidgetData, WidgetView } from './types'

/** The renderers whose big number is a measured number, as the server's NUMBER_RENDERERS. */
const NUMBER_RENDERERS = new Set(['value', 'stats', 'gauge'])

/**
 * Whether a card can be a tile: a number it measures, refreshed by the server.
 * The server holds the same rule (``holders.is_number_card``) and has the last word.
 */
export function isNumberCard(card: { renderer: string; client_only?: boolean; metrics?: string[] }): boolean {
  return NUMBER_RENDERERS.has(card.renderer) && !card.client_only && (card.metrics === undefined || card.metrics.length > 0)
}

/** The shape a tile is drawn at its best: wider than tall, as a number with its label is. */
const TILE_SHAPE = 1.6

/**
 * How many tiles across and down: chosen, or worked out so that each is as
 * large as it can be at a good shape. A wide card gets a row, a tall one a
 * column, and an empty place in the last row costs a little.
 */
export function figuresLayout(count: number, width: number, height: number, columns: string): { across: number; down: number } {
  const n = Math.max(1, count)
  const chosen = Number(columns)
  if (Number.isInteger(chosen) && chosen > 0) {
    const across = Math.min(n, chosen)
    return { across, down: Math.ceil(n / across) }
  }
  if (width <= 0 || height <= 0) return { across: Math.min(n, 3), down: Math.ceil(n / Math.min(n, 3)) }
  let best = { across: 1, down: n }
  let score = -Infinity
  for (let across = 1; across <= n; across += 1) {
    const down = Math.ceil(n / across)
    const fit = Math.min(width / across / TILE_SHAPE, height / down)
    const gaps = (across * down - n) * 2
    if (fit - gaps > score) {
      score = fit - gaps
      best = { across, down }
    }
  }
  return best
}

const WEIGHT: Record<Status, number> = { ok: 0, unknown: 0, warn: 1, bad: 2 }

/**
 * The colour of a tile: how its card stands, or the yellow and red lines
 * drawn on its number, whichever is worse.
 *
 * ⚠️ Both. The lines colour only the drawing of a card and never its status
 * (``apply_level``); a tile is that drawing. A service that failed is still
 * red, whatever the lines say.
 */
export function toneOf(card: WidgetView, data: WidgetData | undefined): Status {
  const status = cardStatus(card, data)
  const level = data?.meta?.level
  const drawn: Status = level === 'bad' || level === 'warn' ? level : 'ok'
  return WEIGHT[drawn] > WEIGHT[status] ? drawn : status
}

/** The history drawn behind a tile's number: the metric its number is, else the card's first. */
export function tileMetric(data: WidgetData | undefined): string | undefined {
  const own = data?.primary?.metric
  const recorded = Object.keys(recordedMetrics(data))
  return own && recorded.includes(own) ? own : recorded[0]
}

/** The two lines that colour a tile, which a card in key figures offers whatever its view. */
export const TILE_LINES = new Set(['level_warn', 'level_bad'])

/** Whether a card of the page is a tile of key figures. */
export function inFigures(widgetId: number | undefined, widgets: WidgetView[]): boolean {
  return widgetId !== undefined && widgets.some((one) => one.kind === 'core.figures' && heldBy(one).includes(widgetId))
}
