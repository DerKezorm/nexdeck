/**
 * What the probes tell the Look and Rules steps (KARTEN-9 AC-6, AC-7, EditorLook): the fields to pick from without
 * typing a path, the lists rows can come from, the fields of one row, and which placed fields the answer lacks.
 */
import { readAt, type CardDoc } from '../../lib/cardDocument'
import { everyNode, listsOf, pathFinds, rowFieldsOf, splitPath, type ProbeNode, type ProbeState } from './probe'
import { cardPath, pathsOfValue, requestIds, slotsOf, type Slot } from './slots'

export interface Hints {
  /** Paths of values in the answers, as the card writes them. */
  fields: string[]
  /** Paths of lists. */
  lists: string[]
  /** Paths inside one row of the card's rows. */
  rowFields: string[]
  /** The list the card's rows come from, if a probe showed it. */
  rows: ProbeNode | null
}

type Trees = { requestId: string; tree: ProbeNode }[]

export function treesOf(probes: Record<string, ProbeState>): Trees {
  return Object.entries(probes).flatMap(([requestId, probe]) => (probe.status === 'done' ? [{ requestId, tree: probe.answer.tree }] : []))
}

export function hintsOf(card: CardDoc | null, trees: Trees): Hints {
  const hints: Hints = { fields: [], lists: [], rowFields: [], rows: null }
  if (!card) return hints
  const select = readAt(card, ['rows', 'select'])
  for (const { requestId, tree } of trees) {
    for (const node of everyNode(tree)) {
      if (node.key === null && requestIds(card).length <= 1) continue
      const path = cardPath(card, requestId, node.path)
      // A field inside the second row and on is the same field as in the first: offered once.
      if (/\[[1-9]\d*\]/.test(node.path)) continue
      if (node.type !== 'object') hints.fields.push(path)
    }
    for (const list of listsOf(tree)) {
      const path = cardPath(card, requestId, list.path)
      if (!/\[[1-9]\d*\]/.test(list.path)) hints.lists.push(path)
      if (typeof select === 'string' && select.trim() === path && !hints.rows) hints.rows = list
    }
  }
  if (hints.rows) hints.rowFields = rowFieldsOf(hints.rows).map((field) => field.path)
  return hints
}

/** Whether a path of the card finds something in the answers: `null` when no probe can tell. */
export function findsInAnswers(card: CardDoc, trees: Trees, path: string): boolean | null {
  const ids = requestIds(card)
  const parts = splitPath(path)
  if (parts === null) return null
  if (ids.length <= 1) {
    const tree = trees.find((one) => one.requestId === ids[0])?.tree
    if (!tree) return null
    const found = pathFinds(tree, path)
    // A card with one request reads `queue.total` in the answer and, failing that, in {queue: answer}.
    if (found === false && parts[0] === ids[0]) return pathFinds(tree, path.slice(String(ids[0]).length).replace(/^\./, '') || '@')
    return found
  }
  const tree = trees.find((one) => one.requestId === parts[0])?.tree
  if (!tree) return null
  return pathFinds(tree, path.slice(String(parts[0]).length).replace(/^\./, '') || '@')
}

/** A placed field the probe's answer does not have: on a value, or in a row, with the first row that lacks it. */
export interface Missing {
  slot: Slot
  path: string
  /** The row that lacks it, counted from 1; `null` for a value of the card. */
  row: number | null
}

export function missingOf(card: CardDoc | null, trees: Trees, hints: Hints): Missing[] {
  if (!card || !trees.length) return []
  const missing: Missing[] = []
  for (const slot of slotsOf(card)) {
    const value = readAt(card, slot.path)
    if (value === undefined) continue
    for (const path of pathsOfValue(value)) {
      if (slot.row) {
        if (!hints.rows) continue
        const row = (hints.rows.children ?? []).findIndex((one) => pathFinds(one, path) === false)
        if (row >= 0) missing.push({ slot, path, row: row + 1 })
      } else if (findsInAnswers(card, trees, path) === false) {
        missing.push({ slot, path, row: null })
      }
    }
  }
  return missing
}

