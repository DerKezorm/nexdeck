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
import { formatShown, pickText, type CardShown, type CardText } from './cardText'
import type { Primary, Secondary, WidgetData } from './types'

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

/**
 * The data of a custom card with every text in the viewer's language. Data of any other card comes back untouched.
 * Safe to apply twice: what is already plain text stays plain text.
 */
export function localizeCustom(data: WidgetData | undefined, lang: string = i18next.language, zone?: string): WidgetData | undefined {
  if (!data || !isCustom(data)) return data
  const items = data.items?.map((item) => {
    const cells = item.shown as Record<string, Cell> | undefined
    if (!cells) return item
    const { shown: _shown, ...rest } = item
    const made: Record<string, unknown> = { ...rest }
    for (const [name, cell] of Object.entries(cells)) made[name] = inRow(cell, lang, zone)
    return made
  })
  const empty = data.meta?.empty
  return {
    ...data,
    primary: data.primary ? primaryOf(data.primary, lang, zone) : data.primary,
    secondary: data.secondary?.map((row) => rowOf(row, lang, zone)),
    items,
    meta: { ...data.meta, empty: empty ? pickText(empty as CardText, lang) : undefined },
  }
}
