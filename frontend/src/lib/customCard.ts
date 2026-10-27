/**
 * A custom card's finished values, made readable in the language of whoever looks (KARTEN-6).
 *
 * The server sends what the author wrote, language by language (`label`, `unit`), and the values with the text it
 * worked out (`text`, `format`). Numbers, dates and times are written the way the viewer's language writes them, and
 * a text is picked from the languages written. After this the renderers read plain strings, and `labelOf` keeps
 * every one of them out of nexdeck's own table of translations (KARTEN-1 AC-5, AC-6).
 */
import i18next from 'i18next'

import { tLabel } from '../i18n/texts'
import type { Block, BlockRow } from './blocks'
import { formatShown, pickText, type CardShown, type CardText } from './cardText'
import type { Action, Primary, Secondary, WidgetData } from './types'

/** Whether the data belongs to a card the administrator described (the server says so in `meta.custom`). */
export function isCustom(data: WidgetData | null | undefined): boolean {
  return data?.meta?.custom === true
}

/** The function that turns a text on the card into words: the table of translations for nexdeck's own, the identity for an author's. */
export function labelOf(data: WidgetData | null | undefined): (text: string | number | null | undefined) => string {
  return isCustom(data) ? (text) => (text === null || text === undefined ? '' : String(text)) : tLabel
}

interface Cell {
  value?: number | string | null
  text?: string
  format?: string
  digits?: number | null
  unit?: CardText | null
  label?: CardText | null
}

function shownOf(cell: Cell): CardShown {
  return {
    value: cell.value ?? null,
    text: cell.text ?? String(cell.value ?? ''),
    format: cell.format ?? 'text',
    digits: cell.digits,
    unit: null,
  }
}

/** The value as the viewer reads it, without its unit: the unit has a place of its own on a card. */
function display(cell: Cell, lang: string, zone?: string): string {
  const shown = shownOf(cell)
  // A percentage is drawn as a number with the % beside it, the way every card with a % draws it.
  if (shown.format === 'percent') shown.format = 'number'
  return formatShown(shown, lang, { zone })
}

function primaryOf(primary: Primary, lang: string, zone?: string): Primary {
  const cell = primary as unknown as Cell
  return {
    ...primary,
    label: pickText(cell.label as CardText, lang),
    unit: pickText(cell.unit as CardText, lang),
    display: display(cell, lang, zone),
  }
}

function rowOf(row: Secondary, lang: string, zone?: string): Secondary {
  const cell = row as unknown as Cell
  return { ...row, label: pickText(cell.label as CardText, lang), unit: pickText(cell.unit as CardText, lang), display: display(cell, lang, zone) }
}

/** A cell of a list row with its unit, as the viewer reads it. */
function inRow(cell: Cell, lang: string, zone?: string): string {
  const shown = { ...shownOf(cell), unit: cell.unit ?? null }
  return formatShown(shown, lang, { zone })
}

/** A text of an action as it is shown: the author's own words as they stand, nexdeck's own through the table. */
export function actionText(action: Pick<Action, 'verbatim'>, text: string): string {
  return action.verbatim ? text : tLabel(text)
}

/**
 * The buttons of a custom card with their texts in the viewer's language. The server sends what the author wrote,
 * one text or one per language (KARTEN-8); after this the label of a button, of its blanks and of their choices are
 * plain strings, marked `verbatim` so that no table of translations touches them.
 */
function actionsOf(actions: Action[] | undefined, lang: string): Action[] | undefined {
  return actions?.map((action) => ({
    ...action,
    label: pickText(action.label as CardText, lang),
    verbatim: true,
    asks: action.asks?.map((ask) => ({
      ...ask,
      label: pickText(ask.label as CardText, lang),
      options: ask.options?.map((one) => ({ ...one, label: pickText(one.label as CardText, lang) })),
    })),
  }))
}

/**
 * The blocks of a card put together from blocks, with every text in the viewer's language: the label of a value, the
 * words of an empty list, the buttons (on the card and on each row of a list). Nothing else is touched.
 */
function blocksIn(blocks: Block[], lang: string): Block[] {
  return blocks.map((block): Block => {
    if (block.type === 'row' || block.type === 'column') return { ...block, children: blocksIn(block.children ?? [], lang) }
    if (block.type === 'value') return { ...block, label: block.label === undefined ? undefined : pickText(block.label as CardText, lang) }
    if (block.type === 'button') return { ...block, action: block.action ? (actionsOf([block.action], lang) as [Action])[0] : null }
    if (block.type === 'list') {
      const rows: BlockRow[] = (block.rows ?? []).map((row) => ({ ...row, blocks: blocksIn(row.blocks ?? [], lang), actions: actionsOf(row.actions, lang) }))
      return { ...block, rows, empty: block.empty === undefined ? undefined : pickText(block.empty as CardText, lang) }
    }
    return block
  })
}

/**
 * The data of a custom card with every text in the viewer's language. Data of any other card comes back untouched.
 * Safe to apply twice: what is already plain text stays plain text.
 */
export function localizeCustom(data: WidgetData | undefined, lang: string = i18next.language, zone?: string): WidgetData | undefined {
  if (!data || !isCustom(data)) return data
  const items = data.items?.map((item) => {
    const cells = item.shown as Record<string, Cell> | undefined
    const actions = Array.isArray(item.actions) ? { actions: actionsOf(item.actions as Action[], lang) } : {}
    if (!cells) return Array.isArray(item.actions) ? { ...item, ...actions } : item
    const { shown: _shown, ...rest } = item
    const made: Record<string, unknown> = { ...rest, ...actions }
    for (const [name, cell] of Object.entries(cells)) made[name] = inRow(cell, lang, zone)
    return made
  })
  const empty = data.meta?.empty
  const blocks = Array.isArray(data.meta?.blocks) ? { blocks: blocksIn(data.meta.blocks as Block[], lang) } : {}
  return {
    ...data,
    primary: data.primary ? primaryOf(data.primary, lang, zone) : data.primary,
    secondary: data.secondary?.map((row) => rowOf(row, lang, zone)),
    actions: actionsOf(data.actions as Action[] | undefined, lang) ?? data.actions,
    items,
    meta: { ...data.meta, ...blocks, empty: empty ? pickText(empty as CardText, lang) : undefined },
  }
}
