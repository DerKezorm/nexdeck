/**
 * Arranging a page by the handful rather than card by card: several cards
 * moved as one, the gaps closed, a card put to a size by name, and the last
 * steps taken back.
 *
 * All of it works on the wide arrangement, the only one that is kept, and
 * none of it changes a card's width or height unless that is what was asked.
 */
import type { LayoutItem } from './types'

export function overlaps(one: LayoutItem, other: LayoutItem): boolean {
  return one.x < other.x + other.w && other.x < one.x + one.w && one.y < other.y + other.h && other.y < one.y + one.h
}

/**
 * The cards named in `fixed` stay where they are; every other card that now
 * overlaps one above it moves down until it does not, and pushes on what is
 * under it in turn. A card that overlaps nothing does not move.
 */
export function settle(items: LayoutItem[], fixed: Set<string> = new Set()): LayoutItem[] {
  const placed: LayoutItem[] = items.filter((item) => fixed.has(item.i)).map((item) => ({ ...item }))
  const rest = items.filter((item) => !fixed.has(item.i)).sort((a, b) => a.y - b.y || a.x - b.x)
  for (const item of rest) {
    const spot = { ...item }
    while (placed.some((other) => overlaps(spot, other))) spot.y += 1
    placed.push(spot)
  }
  return inOrder(placed, items)
}

/**
 * Every card as far up as it goes without touching another, read from the
 * top. Columns stay as they were arranged: a card never moves sideways, so a
 * board laid out in columns keeps them and only the holes close.
 */
export function closeGaps(items: LayoutItem[]): LayoutItem[] {
  const placed: LayoutItem[] = []
  for (const item of [...items].sort((a, b) => a.y - b.y || a.x - b.x)) {
    const spot = { ...item }
    while (spot.y > 0 && !placed.some((other) => overlaps({ ...spot, y: spot.y - 1 }, other))) spot.y -= 1
    placed.push(spot)
  }
  return inOrder(placed, items)
}

/**
 * The cards in `ids` moved by the same step, or null when the step would take
 * one of them off the board or onto a card that is not moving. A drop onto
 * an occupied cell is refused for a group just as the grid refuses it for a
 * single card.
 */
export function shiftGroup(items: LayoutItem[], ids: Set<string>, dx: number, dy: number, columns: number): LayoutItem[] | null {
  const moved = items.map((item) => (ids.has(item.i) ? { ...item, x: item.x + dx, y: item.y + dy } : item))
  const group = moved.filter((item) => ids.has(item.i))
  if (group.some((item) => item.x < 0 || item.y < 0 || item.x + item.w > columns)) return null
  const others = moved.filter((item) => !ids.has(item.i))
  if (group.some((item) => others.some((other) => overlaps(item, other)))) return null
  return moved
}

/** The layout in the order of `reference`, so a save does not look like a change of order. */
function inOrder(placed: LayoutItem[], reference: LayoutItem[]): LayoutItem[] {
  const byId = new Map(placed.map((item) => [item.i, item]))
  return reference.map((item) => byId.get(item.i) ?? item)
}

export type SizeName = 'S' | 'M' | 'L' | 'XL'

/**
 * Four sizes by name: the smallest the card can be drawn at, the size it is
 * made at, and one and a half and twice that. Sizes that come out the same
 * are offered once, under the smaller name, so a card whose floor is its
 * default does not show two buttons that do the same.
 */
export function namedSizes(floor: [number, number], made: [number, number], columns: number): { name: SizeName; w: number; h: number }[] {
  const fit = (w: number, h: number) => ({ w: Math.min(columns, Math.max(floor[0], Math.round(w))), h: Math.max(floor[1], Math.round(h)) })
  const all: { name: SizeName; w: number; h: number }[] = [
    { name: 'S', ...fit(floor[0], floor[1]) },
    { name: 'M', ...fit(made[0], made[1]) },
    { name: 'L', ...fit(made[0] * 1.5, made[1] * 1.5) },
    { name: 'XL', ...fit(made[0] * 2, made[1] * 2) },
  ]
  return all.filter((size, index) => all.findIndex((other) => other.w === size.w && other.h === size.h) === index)
}

/**
 * A card put to a size: it stays where it is, pulled in from the right edge
 * if it would reach past it, and whatever it now covers moves down.
 */
export function resized(items: LayoutItem[], id: string, w: number, h: number, columns: number): LayoutItem[] {
  const changed = items.map((item) => (item.i === id ? { ...item, w, h, x: Math.max(0, Math.min(item.x, columns - w)) } : item))
  return settle(changed, new Set([id]))
}

/**
 * The steps of one page, to go back and forth through.
 *
 * Kept per page and in memory only: a reload starts afresh, which is what one
 * expects of an undo. Fifty steps are more than anyone takes back.
 */
export class Steps {
  private back: LayoutItem[][] = []
  private forth: LayoutItem[][] = []

  constructor(private readonly limit = 50) {}

  /** Remember the arrangement as it was before a change. A new change ends what could be redone. */
  record(before: LayoutItem[]): void {
    const last = this.back[this.back.length - 1]
    if (last && same(last, before)) return
    this.back.push(before)
    if (this.back.length > this.limit) this.back.shift()
    this.forth = []
  }

  undo(current: LayoutItem[]): LayoutItem[] | null {
    const previous = this.back.pop()
    if (!previous) return null
    this.forth.push(current)
    return previous
  }

  redo(current: LayoutItem[]): LayoutItem[] | null {
    const next = this.forth.pop()
    if (!next) return null
    this.back.push(current)
    return next
  }

  get canUndo(): boolean {
    return this.back.length > 0
  }

  get canRedo(): boolean {
    return this.forth.length > 0
  }
}

function same(one: LayoutItem[], other: LayoutItem[]): boolean {
  return one.length === other.length && one.every((item, index) => {
    const spot = other[index]
    return spot.i === item.i && spot.x === item.x && spot.y === item.y && spot.w === item.w && spot.h === item.h
  })
}
