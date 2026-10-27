/**
 * The buttons of a card for the Buttons step (KARTEN-8): which buttons the card has, how one is added, moved and
 * removed, how the content of one is read as rows of a form, and where a field of the data goes as a placeholder.
 *
 * Everything is written into the card's one document (`buttons:` list), so the YAML view shows what the step shows and
 * every comment the author wrote stays.
 */
import { create } from 'zustand'
import { isSeq, type Document } from 'yaml'

import { deleteAt, readAt, readIn, setAt, type CardDoc, type CardPath } from '../../lib/cardDocument'

/** At most this many buttons on a card (the server refuses more). */
export const MAX_BUTTONS = 10
/** At most this many inputs on a button (the server refuses more). */
export const MAX_ASKS = 5
export const METHODS = ['POST', 'PUT', 'PATCH', 'DELETE'] as const
export const ASK_TYPES = ['number', 'text', 'choice'] as const
export type AskType = (typeof ASK_TYPES)[number]

/** A button or a blank is named by a short word the server checks against this. */
export const BUTTON_ID = /^[a-z][a-z0-9_]{0,29}$/
/** What may stand in braces: a field of the data, or a blank of the button as `ask.name`. */
export const PLACEHOLDER_PATH = /^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,4}$/

/** Names for the symbol field to offer; any other symbol name of the icon set can be typed. */
export const SYMBOLS = ['play', 'pause', 'square', 'rotate-cw', 'refresh-cw', 'search', 'power', 'trash', 'download', 'upload', 'gauge', 'bell', 'check', 'x', 'lock', 'unlock', 'zap', 'eye', 'sun', 'moon']

/** The buttons of the card as plain data; an empty list when there is no `buttons:` or it is not a list. */
export function buttonsOf(card: CardDoc | null): Record<string, unknown>[] {
  const list = card ? readAt(card, ['buttons']) : undefined
  return Array.isArray(list) ? list.map((one) => (one && typeof one === 'object' && !Array.isArray(one) ? (one as Record<string, unknown>) : {})) : []
}

/** The first of `base`, `base_2`, `base_3` … that is not taken. */
export function freeId(taken: string[], base: string): string {
  if (!taken.includes(base)) return base
  for (let number = 2; ; number += 1) {
    const one = `${base}_${number}`
    if (!taken.includes(one)) return one
  }
}

/** A new button as the step first writes it: it asks for nothing and does one thing, which the author then sets. */
export function newButton(taken: string[]): Record<string, unknown> {
  return { id: freeId(taken, 'button'), label: 'New button', where: 'card', method: 'POST', path: '/' }
}

/** Add a button at the end of the list. Says nothing when the card already has the most there may be. */
export function addButton(doc: Document): void {
  const list = readIn(doc, ['buttons'])
  const have = Array.isArray(list) ? list : []
  if (have.length >= MAX_BUTTONS) return
  const taken = have.map((one) => String((one as Record<string, unknown> | null)?.id ?? ''))
  setAt(doc, ['buttons', have.length], newButton(taken))
}

/** Take a button out; the last one takes the whole `buttons:` with it. */
export function removeButton(doc: Document, index: number): void {
  deleteAt(doc, ['buttons', index])
  const left = readIn(doc, ['buttons'])
  if (Array.isArray(left) && left.length === 0) deleteAt(doc, ['buttons'])
}

/** Swap a button with its neighbour; the nodes move, so every comment goes along. */
export function moveButton(doc: Document, index: number, by: -1 | 1): void {
  const list = doc.getIn(['buttons'], true)
  if (!isSeq(list)) return
  const other = index + by
  if (other < 0 || other >= list.items.length) return
  const held = list.items[index]
  list.items[index] = list.items[other]
  list.items[other] = held
}

// -- Content of a button ----------------------------------------------------------------------------------------

/** One line of the content: a name and what is sent under it. */
export type BodyRow = readonly [key: string, value: string]

/** Whether the content has names inside names (or lists), which the rows cannot show and must leave alone. */
export function isNestedBody(body: unknown): boolean {
  return body !== null && typeof body === 'object' && !Array.isArray(body) && Object.values(body as Record<string, unknown>).some((value) => value !== null && typeof value === 'object')
}

/** The content as rows of text. */
export function bodyRows(body: unknown): BodyRow[] {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return []
  return Object.entries(body as Record<string, unknown>).map(([key, value]) => [key, value === null || value === undefined ? '' : String(value)] as const)
}

/**
 * What the rows send. In JSON a number or true/false typed in a row is sent as that (a placeholder stays text, the
 * server gives it the type of the value it stands for); in a form everything is text.
 */
export function bodyFromRows(rows: readonly BodyRow[], send: string): Record<string, unknown> {
  return Object.fromEntries(
    rows.map(([key, value]) => {
      if (send === 'form') return [key, value]
      const trimmed = value.trim()
      if (trimmed === 'true') return [key, true]
      if (trimmed === 'false') return [key, false]
      if (trimmed !== '' && /^-?\d+(\.\d+)?$/.test(trimmed) && trimmed === String(Number(trimmed))) return [key, Number(trimmed)]
      return [key, value]
    }),
  )
}

/** A name for a new line of the content that no other line has. */
export function freeKey(rows: readonly BodyRow[]): string {
  return freeId(
    rows.map((row) => row[0]),
    'field',
  )
}

// -- Placeholders -----------------------------------------------------------------------------------------------

/** Where a field of the data goes when "Use in button" is chosen: the button and the field of it last worked in. */
export type ButtonTarget = { index: number; part: 'path' } | { index: number; part: 'body'; key: string }

interface TargetState {
  target: ButtonTarget | null
  /** The field that last had the cursor, remembered by the field itself. */
  set: (target: ButtonTarget | null) => void
}

/** The path or content field last worked in. ⚠️ Memory only: it belongs to the visit, not to the card. */
export const useButtonTarget = create<TargetState>((set) => ({ target: null, set: (target) => set({ target }) }))

/** The path of a field as the button names it, in braces. `null` when braces cannot hold it. */
export function placeholderText(path: string): string | null {
  return PLACEHOLDER_PATH.test(path) ? `{${path}}` : null
}

/** `{name}` put at the end of what stands in the field, or alone when it is empty. */
export function withPlaceholder(current: string, placeholder: string): string {
  return current ? `${current}${placeholder}` : placeholder
}

/** Put a placeholder into the field the target names. Says whether anything was written. */
export function putPlaceholder(doc: Document, target: ButtonTarget, placeholder: string): boolean {
  if (target.part === 'path') {
    const path: CardPath = ['buttons', target.index, 'path']
    const now = readIn(doc, path)
    setAt(doc, path, withPlaceholder(typeof now === 'string' ? now : '', placeholder))
    return true
  }
  const body = readIn(doc, ['buttons', target.index, 'body'])
  if (isNestedBody(body) || !body || typeof body !== 'object') return false
  const rows = bodyRows(body)
  const at = rows.findIndex((row) => row[0] === target.key)
  if (at < 0) return false
  const send = readIn(doc, ['buttons', target.index, 'send'])
  const next = rows.map((row, index) => (index === at ? ([row[0], withPlaceholder(row[1], placeholder)] as const) : row))
  setAt(doc, ['buttons', target.index, 'body'], bodyFromRows(next, typeof send === 'string' ? send : 'json'))
  return true
}
