/**
 * Putting a field of a probe's answer on the card (KARTEN-9 AC-4, AC-5): from "Use as …" in the tree and from a
 * field dragged onto a place of the card. Both end here, so a click and a drop do the same.
 */
import { readAt, setAt } from '../../lib/cardDocument'
import type { CardForm } from '../../lib/customCards'
import { enclosingList, nodeAt, rowFieldsOf, type ProbeNode } from './probe'
import { assign, cardPath, changeForm, insideRow, lostByForm, replacedAt, type Slot } from './slots'
import { useCardEditor } from './store'

/** What a dragged field carries: the request whose answer it is in, and its path there. */
export const FIELD_TYPE = 'application/x-nexdeck-field'

export interface DraggedField {
  requestId: string
  path: string
}

/** The tree of a request's answer, when it has been probed. */
export function treeOf(requestId: string): ProbeNode | null {
  const probe = useCardEditor.getState().probes[requestId]
  return probe?.status === 'done' ? probe.answer.tree : null
}

/** Whether a field can go on this place: a cell of each row needs a field inside a list. */
export function fits(tree: ProbeNode, node: ProbeNode, slot: Slot): boolean {
  if (!slot.row) return true
  return enclosingList(tree, node) !== null
}

/** Put the field on the place. Says whether anything changed. */
export function place(requestId: string, node: ProbeNode, slot: Slot): boolean {
  const editor = useCardEditor.getState()
  const tree = treeOf(requestId)
  if (!editor.card || !tree) return false
  const before = editor.text
  const replaced = replacedAt(editor.card, slot)
  let put: string
  if (slot.row) {
    const list = enclosingList(tree, node)
    const inner = list ? insideRow(list.path, node.path) : null
    if (!list || inner === null) return false
    const rows = cardPath(editor.card, requestId, list.path)
    put = inner
    editor.change((doc) => assign(doc, slot, inner, rows))
  } else {
    const path = cardPath(editor.card, requestId, node.path)
    put = path
    editor.change((doc) => assign(doc, slot, path))
  }
  const changed = useCardEditor.getState().text !== before
  // ⚠️ The formula, text or total on the place is gone from the card: say so, and the way back is one click.
  if (changed && replaced) useCardEditor.setState({ replaced: { place: slot.label, what: replaced, path: put } })
  return changed
}

/** A dropped field, looked up in its answer. */
export function placeDropped(field: DraggedField, slot: Slot): boolean {
  const tree = treeOf(field.requestId)
  const node = tree ? nodeAt(tree, field.path) : null
  return node ? place(field.requestId, node, slot) : false
}

export function readDragged(data: DataTransfer | null): DraggedField | null {
  try {
    const raw = data?.getData(FIELD_TYPE)
    const field = raw ? (JSON.parse(raw) as DraggedField) : null
    return field && typeof field.requestId === 'string' && typeof field.path === 'string' ? field : null
  } catch {
    return null
  }
}

/**
 * Show a list of the answer as the card's rows, as a list or as pictures (AC-5). The first text field of a row
 * becomes the title when the card has none, so that the preview shows the rows at once. What the new form has no
 * room for is named by `lostByForm` first; the caller asks before.
 */
export function showListAs(requestId: string, list: ProbeNode, form: Extract<CardForm, 'list' | 'posters'>): void {
  const editor = useCardEditor.getState()
  if (!editor.card) return
  const rows = cardPath(editor.card, requestId, list.path)
  const title = readAt(editor.card, ['item', 'title'])
  const text = rowFieldsOf(list).find((field) => field.type === 'string')
  editor.change((doc) => {
    changeForm(doc, form, rows)
    if (title === undefined && text) setAt(doc, ['item', 'title'], text.path)
  })
}

/** What showing a list as this form would take away from the card. */
export function lostIfShownAs(form: CardForm) {
  const card = useCardEditor.getState().card
  return card ? lostByForm(card, form) : []
}
