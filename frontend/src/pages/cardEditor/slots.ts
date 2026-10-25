/**
 * The places of a card (KARTEN-9 AC-4 to AC-6): what each form has room for, how a field of the probe's answer is put
 * on one of them, and which fields of the answer the card already uses.
 *
 * Paths of the probe start at the top of one answer. A card with one request reads its paths from that answer; a
 * card with several reads them from all answers by request id (`queue.records`), so the id goes in front. The fields
 * of a row are paths inside the row, and `rows.select` says which list the rows are (AC-5).
 */
import type { Document } from 'yaml'

import { deleteAt, readAt, readIn, setAt, type CardDoc, type CardPath } from '../../lib/cardDocument'
import type { CardForm } from '../../lib/customCards'

export const FORMS: CardForm[] = ['value', 'stats', 'list', 'posters']
export const MAX_STATS = 6
export const MIN_STATS = 2

/** One place a field can go: a value of the card, or a cell of each row. */
export interface Slot {
  id: string
  path: CardPath
  /** A cell of each row: its path is read inside the row. */
  row: boolean
  /** The words that name it, and the number of a value among several. */
  label: { key: string; number?: number }
  required?: boolean
}

const ROW_SLOTS: Record<'list' | 'posters', { key: string; required?: boolean }[]> = {
  list: [{ key: 'title', required: true }, { key: 'subtitle' }, { key: 'value' }, { key: 'link' }, { key: 'image' }],
  posters: [{ key: 'image', required: true }, { key: 'title', required: true }, { key: 'subtitle' }, { key: 'link' }],
}

/** What the card's form has room for, in the order the card shows it. A card of numbers offers one more, up to six. */
export function slotsOf(card: CardDoc | null): Slot[] {
  if (!card) return []
  const form = readAt(card, ['form'])
  if (form === 'value') return [{ id: 'value', path: ['value'], row: false, label: { key: 'editor.slot.value' }, required: true }]
  if (form === 'stats') {
    const stats = readAt(card, ['stats'])
    const count = Array.isArray(stats) ? stats.length : 0
    const slots: Slot[] = Array.from({ length: count }, (_, index) => ({
      id: `stats.${index}`,
      path: ['stats', index],
      row: false,
      label: { key: 'editor.slot.stat', number: index + 1 },
      required: index < MIN_STATS,
    }))
    if (count < MAX_STATS) slots.push({ id: `stats.${count}`, path: ['stats', count], row: false, label: { key: 'editor.slot.newStat', number: count + 1 } })
    return slots
  }
  if (form === 'list' || form === 'posters') {
    return ROW_SLOTS[form].map(({ key, required }) => ({ id: `item.${key}`, path: ['item', key], row: true, label: { key: `editor.slot.${key}` }, required }))
  }
  return []
}

/** The request ids of the card, in order. */
export function requestIds(card: CardDoc | null): string[] {
  const requests = card ? readAt(card, ['requests']) : undefined
  return Array.isArray(requests) ? requests.map((one) => (one && typeof one === 'object' ? String((one as { id?: unknown }).id ?? '') : '')) : []
}

/** A path of one answer as the card reads it: as it is with one request, behind the request id with several. */
export function cardPath(card: CardDoc | null, requestId: string, probePath: string): string {
  if (requestIds(card).length <= 1) return probePath
  if (probePath === '@' || probePath === '') return requestId
  return probePath.startsWith('[') ? `${requestId}${probePath}` : `${requestId}.${probePath}`
}

/**
 * A path inside one row of the list `select`: `series.title` for `records[3].series.title` in `records`. `@` for the
 * row itself; `null` when the path is not inside a row of that list.
 */
export function insideRow(select: string, path: string): string | null {
  const list = select.trim()
  const rest = list === '@' ? path : path.startsWith(list) ? path.slice(list.length) : null
  if (rest === null) return null
  const row = /^\[\d+\]/.exec(rest)
  if (!row) return null
  const inner = rest.slice(row[0].length)
  if (inner === '') return '@'
  if (inner.startsWith('.')) return inner.slice(1)
  if (inner.startsWith('[')) return inner
  return null
}

/** The value at `path` as a short path (`value: a.b`) or the path of its long form; `null` for a formula and the rest. */
function pathOfValue(value: unknown): string | null {
  if (typeof value === 'string') return value
  if (value && typeof value === 'object' && typeof (value as { path?: unknown }).path === 'string') return (value as { path: string }).path
  return null
}

/** Names in braces of a formula or a template (`{disk.used}`), each a path. */
export function referencesOf(text: string): string[] {
  return [...text.matchAll(/\{([^{}]+)\}/g)].map((match) => match[1].trim()).filter(Boolean)
}

/** Every path a value reads: its path, or the names in its formula or template. */
export function pathsOfValue(value: unknown): string[] {
  const plain = pathOfValue(value)
  if (plain !== null) return [plain]
  if (!value || typeof value !== 'object') return []
  const { formula, template } = value as { formula?: unknown; template?: unknown }
  return [formula, template].flatMap((text) => (typeof text === 'string' ? referencesOf(text) : []))
}

/** What the card uses of the answers: paths of its values, and the list its rows come from with the paths of a row. */
export interface Used {
  values: Map<string, Slot[]>
  rows: { select: string; fields: Map<string, Slot[]> } | null
}

export function usedOf(card: CardDoc | null): Used {
  const used: Used = { values: new Map(), rows: null }
  if (!card) return used
  const add = (map: Map<string, Slot[]>, path: string, slot: Slot) => map.set(path, [...(map.get(path) ?? []), slot])
  const select = readAt(card, ['rows', 'select'])
  if (typeof select === 'string') used.rows = { select: select.trim(), fields: new Map() }
  for (const slot of slotsOf(card)) {
    const value = readAt(card, slot.path)
    if (value === undefined) continue
    for (const path of pathsOfValue(value)) {
      if (slot.row && used.rows) add(used.rows.fields, path, slot)
      else if (!slot.row) add(used.values, path, slot)
    }
  }
  return used
}

/** The places a node of the answer stands on now (EditorSource: the field marked, its place beside it). */
export function placesOf(used: Used, path: string): Slot[] {
  const found = [...(used.values.get(path) ?? [])]
  if (used.rows) {
    const inner = insideRow(used.rows.select, path)
    if (inner !== null) found.push(...(used.rows.fields.get(inner) ?? []))
  }
  return found
}

/**
 * Put a path on a place of the card. A value written short stays short (`value: a.b`); a long one keeps its label,
 * unit and format, and loses the formula, template or total it had instead. A cell of each row first makes the list
 * the rows of the card when it is another one (AC-5).
 */
export function assign(doc: Document, slot: Slot, path: string, list?: string): void {
  if (slot.row && list !== undefined) {
    const select = readIn(doc, ['rows', 'select'])
    if (typeof select !== 'string' || select.trim() !== list) setAt(doc, ['rows', 'select'], list)
  }
  const now = readIn(doc, slot.path)
  if (now && typeof now === 'object' && !Array.isArray(now)) {
    for (const other of ['formula', 'template', 'total']) deleteAt(doc, [...slot.path, other])
    setAt(doc, [...slot.path, 'path'], path)
  } else {
    setAt(doc, slot.path, path)
  }
}

/** What a place reads from instead of a path, which a path put on it takes away: a formula, a text with fields or a total. */
export type Replaced = 'formula' | 'template' | 'total'

export function replacedAt(card: CardDoc | null, slot: Slot): Replaced | null {
  const now = card ? readAt(card, slot.path) : undefined
  if (!now || typeof now !== 'object' || Array.isArray(now)) return null
  const own = now as Record<string, unknown>
  return (['formula', 'template', 'total'] as const).find((kind) => own[kind] !== undefined) ?? null
}

/** What a change of form would take away: the parts of the card the new form has no room for. */
export function lostByForm(card: CardDoc, to: CardForm): CardPath[] {
  const from = readAt(card, ['form'])
  if (from === to) return []
  const lost: CardPath[] = []
  const has = (path: CardPath) => readAt(card, path) !== undefined
  const rowsKept = to === 'list' || to === 'posters'
  if (has(['value']) && to !== 'stats') lost.push(['value'])
  const stats = readAt(card, ['stats'])
  if (Array.isArray(stats)) stats.forEach((_, index) => (to !== 'value' || index > 0) && lost.push(['stats', index]))
  if (!rowsKept) for (const part of ['rows', 'item', 'empty']) if (has([part])) lost.push([part])
  if (to === 'posters') for (const part of ['value', 'status']) if (has(['item', part])) lost.push(['item', part])
  return lost
}

/**
 * Change the card's form. What the new form can take goes along: the value becomes the first of several numbers and
 * back, the rows and their cells stay between a list and a wall of pictures. The rest goes, which `lostByForm` names
 * before (the editor asks first).
 */
export function changeForm(doc: Document, to: CardForm, list?: string): void {
  const from = readIn(doc, ['form'])
  if (from === to) {
    if (list !== undefined) setAt(doc, ['rows', 'select'], list)
    return
  }
  const value = readIn(doc, ['value'])
  const stats = readIn(doc, ['stats'])
  if (to === 'stats' && value !== undefined && stats === undefined) setAt(doc, ['stats'], [value])
  if (to === 'value' && Array.isArray(stats) && stats.length && value === undefined) setAt(doc, ['value'], stats[0])
  if (to !== 'value') deleteAt(doc, ['value'])
  if (to !== 'stats') deleteAt(doc, ['stats'])
  if (to === 'list' || to === 'posters') {
    if (to === 'posters') for (const part of ['value', 'status']) deleteAt(doc, ['item', part])
    if (list !== undefined) setAt(doc, ['rows', 'select'], list)
  } else {
    for (const part of ['rows', 'item', 'empty']) deleteAt(doc, [part])
  }
  setAt(doc, ['form'], to)
}
