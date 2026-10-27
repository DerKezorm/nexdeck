/**
 * The blocks of a card put together from blocks, for the builder in the Look step (KARTEN-7): which blocks there are,
 * how the tree of them is read, and how one is added, moved and taken out.
 *
 * Everything is written into the card's one document (`blocks:`), so the YAML view shows what the builder shows and
 * every comment the author wrote stays: a block that moves is the same node of the document.
 */
import { isSeq, type Document } from 'yaml'

import { deleteAt, readAt, readIn, setAt, type CardDoc, type CardPath } from '../../lib/cardDocument'
import { BLOCK_COLORS } from '../../lib/blocks'
import { freeId } from './buttons'

export type BlockType = 'row' | 'column' | 'divider' | 'text' | 'value' | 'badge' | 'symbol' | 'image' | 'progress' | 'sparkline' | 'list' | 'button'
export type BlockGroup = 'layout' | 'content' | 'data' | 'action'

/** The twelve blocks in their four groups, in the order the list shows them (AC-1). */
export const GROUPS: { group: BlockGroup; types: BlockType[] }[] = [
  { group: 'layout', types: ['row', 'column', 'divider'] },
  { group: 'content', types: ['text', 'value', 'badge', 'symbol', 'image'] },
  { group: 'data', types: ['progress', 'sparkline', 'list'] },
  { group: 'action', types: ['button'] },
]
export const BLOCK_TYPES: BlockType[] = GROUPS.flatMap((one) => one.types)

/** At most this many blocks on a card, counted all the way down (the server refuses more, AC-5). */
export const MAX_BLOCKS = 100
/** At most this deep: a block on the top is level 1. */
export const MAX_DEPTH = 6
/** The fixed steps a setting is chosen from (AC-3). */
export const SIZES = ['xs', 's', 'm', 'l', 'xl'] as const
export const GAPS = ['none', 's', 'm', 'l'] as const
export const ALIGNS = ['start', 'center', 'end', 'between'] as const
export const WEIGHTS = ['normal', 'bold'] as const
export const HEIGHTS = ['s', 'm', 'l'] as const
export { BLOCK_COLORS }

/** The key under which a block holds the blocks inside it: a row and a column their children, a list its template. */
export function childKey(type: unknown): 'children' | 'item' | null {
  if (type === 'row' || type === 'column') return 'children'
  if (type === 'list') return 'item'
  return null
}

type Plain = Record<string, unknown>
const asBlock = (value: unknown): Plain => (value && typeof value === 'object' && !Array.isArray(value) ? (value as Plain) : {})

/** The blocks inside one block, as plain data. */
function innerOf(block: Plain): unknown[] {
  const key = childKey(block.type)
  const list = key ? block[key] : undefined
  return Array.isArray(list) ? list : []
}

/** One block of the tree as the builder lists it. */
export interface BlockNode {
  path: CardPath
  /** The level: a block on the top is 1. */
  depth: number
  type: string
  block: Plain
}

/** The blocks of the card in the order they are drawn, each with where it stands (the tree, flattened). */
export function flatten(card: CardDoc | null): BlockNode[] {
  const top = card ? readAt(card, ['blocks']) : undefined
  const out: BlockNode[] = []
  const walk = (list: unknown[], path: CardPath, depth: number) =>
    list.forEach((one, index) => {
      const block = asBlock(one)
      const here = [...path, index]
      out.push({ path: here, depth, type: String(block.type ?? ''), block })
      const key = childKey(block.type)
      if (key) walk(innerOf(block), [...here, key], depth + 1)
    })
  if (Array.isArray(top)) walk(top, ['blocks'], 1)
  return out
}

/** How many blocks a block is, itself and everything inside it: what removing it takes away (EC-6). */
export function countOf(block: unknown): number {
  const plain = asBlock(block)
  return 1 + innerOf(plain).reduce<number>((sum, one) => sum + countOf(one), 0)
}

/** How many blocks the card has (AC-5). */
export function totalOf(card: CardDoc | null): number {
  const top = card ? readAt(card, ['blocks']) : undefined
  return Array.isArray(top) ? top.reduce<number>((sum, one) => sum + countOf(one), 0) : 0
}

/** How many levels a block is deep inside, itself included. */
function heightOf(block: unknown): number {
  return 1 + Math.max(0, ...innerOf(asBlock(block)).map(heightOf))
}

/** The level of the block at `path`: the number of places in the path that count blocks. */
function depthAt(path: CardPath): number {
  return path.filter((part) => typeof part === 'number').length
}

/** Whether the block at `path` stands inside a list's template (a list may not hold another list). */
function insideList(path: CardPath): boolean {
  return path.includes('item')
}

/** Whether a block can take other blocks. */
export const isContainer = (type: unknown): boolean => childKey(type) !== null

/** What a new block starts as. `field` is a field of the data to read, `button` the id of a button of the card. */
export function newBlock(type: BlockType, taken: string[], field = '@', button = ''): Plain {
  switch (type) {
    case 'row':
      return { type, gap: 'm', children: [] }
    case 'column':
      return { type, gap: 'm', children: [] }
    case 'divider':
      return { type }
    case 'text':
      return { type, text: 'Text', size: 'm' }
    case 'value':
      return { type, path: field, size: 'l' }
    case 'badge':
      return { type, value: { path: field }, color: 'accent' }
    case 'symbol':
      return { type, icon: 'server', color: 'accent', size: 'm' }
    case 'image':
      return { type, src: { path: field }, height: 'm' }
    case 'progress':
      return { type, value: { path: field }, max: 100, color: 'accent' }
    case 'sparkline':
      return { type, id: freeId(taken, 'trend'), value: { path: field } }
    case 'list':
      return { type, item: [] }
    case 'button':
      return { type, button }
  }
}

/** Every `id` a block of the card has, to hand out a free one. */
export function idsOf(card: CardDoc | null): string[] {
  return flatten(card)
    .map((node) => node.block.id)
    .filter((id): id is string => typeof id === 'string')
}

/** The value blocks that have an `id`: the ones that can be the main value of the card (AC-8). */
export function mainChoices(card: CardDoc | null): string[] {
  return flatten(card)
    .filter((node) => node.type === 'value' && typeof node.block.id === 'string' && node.block.id !== '')
    .map((node) => String(node.block.id))
}

// -- where a new block goes --------------------------------------------------------------------------------------

/** Whether a block of this type can be added under the selected block: the room for it, the levels and the lists. */
export function canAdd(card: CardDoc | null, selected: CardPath | null, type: BlockType): boolean {
  if (totalOf(card) >= MAX_BLOCKS) return false
  const target = whereToAdd(card, selected)
  if (type === 'list' && insideList(target.parent)) return false
  // A container is added empty, so its own level is all that counts.
  return depthAt(target.parent) + 1 <= MAX_DEPTH
}

/** The id of the first button that suits where a block added under `selected` would stand: one of each row inside a list, else one of the card. `''` when there is none. */
export function buttonFor(card: CardDoc | null, selected: CardPath | null, buttons: { id: string; where: string }[]): string {
  const inside = insideList(whereToAdd(card, selected).parent)
  return buttons.find((one) => (inside ? one.where === 'row' : one.where !== 'row'))?.id ?? ''
}

/** The list a block added with `selected` chosen goes into, and at which place. */
function whereToAdd(card: CardDoc | null, selected: CardPath | null): { parent: CardPath; index: number } {
  const top = card ? readAt(card, ['blocks']) : undefined
  const count = Array.isArray(top) ? top.length : 0
  if (!card || !selected) return { parent: ['blocks'], index: count }
  const block = asBlock(readAt(card, selected))
  const key = childKey(block.type)
  // Into a row, a column or a list; behind any other block.
  if (key) return { parent: [...selected, key], index: innerOf(block).length }
  return { parent: selected.slice(0, -1), index: Number(selected[selected.length - 1]) + 1 }
}

/** Put `block` into the seq at `parent` at `index`, making the seq when it is not there yet. */
function insertInto(doc: Document, parent: CardPath, index: number, block: unknown): void {
  const list = doc.getIn(parent as (string | number)[], true)
  if (isSeq(list)) {
    list.items.splice(index, 0, doc.createNode(block))
    return
  }
  setAt(doc, parent, [block])
}

/**
 * Add a block under the selected one: into a row, a column or a list, behind any other block, at the end of the card
 * when nothing is selected. Says where it went, or `null` when it did not (full, too deep).
 */
export function addBlock(doc: Document, card: CardDoc, selected: CardPath | null, type: BlockType, options: { field?: string; button?: string; lists?: string[] } = {}): CardPath | null {
  if (!canAdd(card, selected, type)) return null
  const { parent, index } = whereToAdd(card, selected)
  insertInto(doc, parent, index, newBlock(type, idsOf(card), options.field, options.button))
  // A list reads its rows from `rows`; a card without any takes the first list of the data.
  if (type === 'list' && options.lists?.[0] && typeof readIn(doc, ['rows', 'select']) !== 'string') setAt(doc, ['rows', 'select'], options.lists[0])
  return [...parent, index]
}

// -- taking out and moving ---------------------------------------------------------------------------------------

function seqAt(doc: Document, path: CardPath) {
  const list = doc.getIn(path as (string | number)[], true)
  return isSeq(list) ? list : null
}

/** Take the block at `path` out, and its main value with it when that is the one inside. */
export function removeBlock(doc: Document, path: CardPath): void {
  const main = readIn(doc, ['main'])
  const gone = readIn(doc, path)
  if (typeof main === 'string' && main !== '') {
    const ids: unknown[] = []
    const collect = (one: unknown) => {
      const plain = asBlock(one)
      if (plain.type === 'value') ids.push(plain.id)
      innerOf(plain).forEach(collect)
    }
    collect(gone)
    if (ids.includes(main)) deleteAt(doc, ['main'])
  }
  deleteAt(doc, path)
}

/**
 * Move the block at `path` one place up or down among its neighbours. At the end of its row, column or list it steps
 * out in front of or behind the one that holds it, so that every place can be reached with the two arrows. Says where
 * the block is now, or `null` when it cannot move.
 */
export function moveBlock(doc: Document, path: CardPath, by: -1 | 1): CardPath | null {
  const parentPath = path.slice(0, -1)
  const list = seqAt(doc, parentPath)
  if (!list) return null
  const index = Number(path[path.length - 1])
  const other = index + by
  if (other >= 0 && other < list.items.length) {
    const held = list.items[index]
    list.items[index] = list.items[other]
    list.items[other] = held
    return [...parentPath, other]
  }
  // Out of the row, column or list: the holder stands two places up (`…, index, 'children'`).
  if (parentPath.length < 3) return null
  const holder = parentPath.slice(0, -1)
  const outer = seqAt(doc, holder.slice(0, -1))
  if (!outer) return null
  const holderIndex = Number(holder[holder.length - 1])
  const node = list.items[index]
  // A list's template may not hold a list; leaving it is fine, entering one is not asked here.
  list.items.splice(index, 1)
  const at = by === -1 ? holderIndex : holderIndex + 1
  outer.items.splice(at, 0, node)
  return [...holder.slice(0, -1), at]
}

/** The path `target` has once the block at `removed` is taken out of the card. */
function shiftedBy(target: CardPath, removed: CardPath): CardPath {
  const parent = removed.slice(0, -1)
  if (target.length <= parent.length || !parent.every((part, at) => target[at] === part)) return target
  const index = Number(removed[removed.length - 1])
  const there = Number(target[parent.length])
  if (there < index) return target
  return [...target.slice(0, parent.length), there - 1, ...target.slice(parent.length + 1)]
}

/** Whether `inner` is `outer` or stands inside it. */
function within(outer: CardPath, inner: CardPath): boolean {
  return outer.length <= inner.length && outer.every((part, at) => inner[at] === part)
}

/** Where the dragged block would go when dropped on `onto`: into a row, column or list, behind any other block. */
function dropPlace(card: CardDoc, onto: CardPath): { parent: CardPath; index: number } {
  return whereToAdd(card, onto)
}

/** Whether the block at `from` can be dropped on the block at `onto`: not onto itself or into itself, and within the levels. */
export function canDrop(card: CardDoc, from: CardPath, onto: CardPath): boolean {
  if (within(from, onto)) return false
  const place = dropPlace(card, onto)
  const moving = readAt(card, from)
  if (depthAt(place.parent) + heightOf(moving) > MAX_DEPTH) return false
  const holdsList = JSON.stringify(moving).includes('"type":"list"')
  return !(holdsList && insideList(place.parent))
}

/** Drag the block at `from` onto the block at `onto` (into it if it can hold blocks, else behind it). Says where it is now. */
export function dropBlock(doc: Document, card: CardDoc, from: CardPath, onto: CardPath): CardPath | null {
  if (!canDrop(card, from, onto)) return null
  const place = dropPlace(card, onto)
  const source = seqAt(doc, from.slice(0, -1))
  if (!source) return null
  const node = source.items[Number(from[from.length - 1])]
  const parent = shiftedBy(place.parent, from)
  const sameList = place.parent.length === from.length - 1 && place.parent.every((part, at) => part === from[at])
  const index = sameList && Number(from[from.length - 1]) < place.index ? place.index - 1 : place.index
  source.items.splice(Number(from[from.length - 1]), 1)
  const target = seqAt(doc, parent)
  if (!target) return null
  target.items.splice(index, 0, node)
  return [...parent, index]
}

/** Drop a new block of `type` on the block at `onto`, as tapping would with that block selected. */
export function dropNew(doc: Document, card: CardDoc, onto: CardPath | null, type: BlockType, options: { field?: string; button?: string; lists?: string[] } = {}): CardPath | null {
  return addBlock(doc, card, onto, type, options)
}

/** Change the `id` of the block at `path`; the main value follows its block, and goes with an id taken away. */
export function setBlockId(doc: Document, path: CardPath, id: string): void {
  const old = readIn(doc, [...path, 'id'])
  const main = readIn(doc, ['main'])
  if (id === '') deleteAt(doc, [...path, 'id'])
  else setAt(doc, [...path, 'id'], id)
  if (typeof main === 'string' && main !== '' && main === old) {
    if (id === '') deleteAt(doc, ['main'])
    else setAt(doc, ['main'], id)
  }
}
