/**
 * Cards held by a group or by the side bar of a page, and the arithmetic of
 * putting them somewhere: their size inside, the rows a group needs, a free
 * spot on the board for a card that comes out.
 *
 * A held card keeps its size on itself, as ``options.held_size``: columns of
 * twelve across a group, rows down; in the side bar only the rows count.
 */
import type { LayoutItem, WidgetView } from './types'

export interface HeldSize {
  w: number
  h: number
}

/** The side bar of a card page, as the server keeps it. */
export interface Side {
  place: 'off' | 'left' | 'right'
  width: 'narrow' | 'wide'
  cards: number[]
}

export const NO_SIDE: Side = { place: 'off', width: 'narrow', cards: [] }

/** How wide the side bar is drawn, in pixels. */
export const SIDE_WIDTH: Record<Side['width'], number> = { narrow: 260, wide: 340 }

/** The widths a held card steps through, in twelfths: a quarter, a third, a half, two thirds, all. */
export const HELD_WIDTHS = [3, 4, 6, 8, 12]
/** The heights it steps through, in rows. */
export const MOST_HELD_ROWS = 6

/** The size a card has inside, read from its options, or what a group of ``columns`` gave it before it had one. */
export function heldSizeOf(widget: WidgetView, columns: string | undefined = 'auto'): HeldSize {
  const raw = widget.options?.held_size as Partial<HeldSize> | undefined
  const w = Number(raw?.w)
  const h = Number(raw?.h)
  if (Number.isInteger(w) && Number.isInteger(h) && w >= 1 && w <= 12 && h >= 1 && h <= 12) return { w, h }
  const across = Number(columns)
  return { w: across > 0 ? Math.max(1, Math.round(12 / across)) : 4, h: 2 }
}

/** Whether any card of a group carries a size of its own: then the group lays them out on its own grid. */
export function freeGroup(cards: WidgetView[]): boolean {
  return cards.some((card) => card.options?.held_size !== undefined && card.options?.held_size !== null)
}

/** The size a card from the board takes inside a group: its share of the board's width in twelfths, and its rows. */
export function sizeFromBoard(item: { w: number; h: number }, boardColumns: number): HeldSize {
  return { w: Math.min(12, Math.max(1, Math.round((item.w * 12) / boardColumns))), h: Math.min(12, Math.max(1, item.h)) }
}

/** The size a held card takes on the board: its twelfths in the board's columns, and its rows. */
export function sizeOnBoard(size: HeldSize, boardColumns: number): { w: number; h: number } {
  return { w: Math.min(boardColumns, Math.max(1, Math.round((size.w * boardColumns) / 12))), h: size.h }
}

export interface Packed {
  x: number
  y: number
  w: number
  h: number
}

/**
 * Where each card of a group stands: in order, each in the first place from
 * the top left where it fits, as a grid that fills its gaps would put it.
 * Worked out here rather than left to the browser, so the group knows how
 * many rows it needs.
 */
export function pack(sizes: HeldSize[], columns = 12): Packed[] {
  const taken: boolean[][] = []
  const free = (x: number, y: number, w: number, h: number) => {
    for (let row = y; row < y + h; row += 1) for (let column = x; column < x + w; column += 1) if (taken[row]?.[column]) return false
    return true
  }
  return sizes.map(({ w: wide, h }) => {
    const w = Math.min(columns, wide)
    for (let y = 0; ; y += 1) {
      for (let x = 0; x + w <= columns; x += 1) {
        if (!free(x, y, w, h)) continue
        for (let row = y; row < y + h; row += 1) {
          taken[row] ??= []
          for (let column = x; column < x + w; column += 1) taken[row][column] = true
        }
        return { x, y, w, h }
      }
    }
  })
}

/** The rows a packed group fills. */
export function rowsOf(packed: Packed[]): number {
  return Math.max(0, ...packed.map((one) => one.y + one.h))
}

/** The title of a group with its padding, in pixels. */
export const GROUP_HEAD = 42
/** The room under the last row of a group. */
export const GROUP_FOOT = 12

/** The board rows a group needs for ``rows`` rows of its own, at the board's row height and gap. */
export function boardRowsFor(rows: number, rowHeight: number, gap: number): number {
  const inner = rows > 0 ? rows * rowHeight + (rows - 1) * gap : rowHeight
  return Math.max(2, Math.ceil((GROUP_HEAD + inner + GROUP_FOOT + gap) / (rowHeight + gap)))
}

/**
 * The layout with one card grown or shrunk, the cards under it pushed down
 * when it grows into them, never pulled up when it shrinks.
 */
export function grown(layout: LayoutItem[], id: string, h: number): LayoutItem[] {
  const item = layout.find((one) => one.i === id)
  if (!item || item.h === h) return layout
  const result = layout.map((one) => (one.i === id ? { ...one, h } : { ...one }))
  if (h < item.h) return result
  // Push whatever the new rows cover, and whatever that in turn covers, down.
  const moving = [result.find((one) => one.i === id)!]
  while (moving.length) {
    const above = moving.shift()!
    for (const other of result) {
      if (other.i === above.i || other.y + other.h <= above.y || other.y >= above.y + above.h) continue
      if (other.x + other.w <= above.x || other.x >= above.x + above.w) continue
      if (other.y < above.y) continue
      other.y = above.y + above.h
      moving.push(other)
    }
  }
  return result
}

/** The first spot from ``x``, ``y`` onwards, row by row, where a card of ``w`` by ``h`` overlaps nothing. */
export function freeSpot(layout: LayoutItem[], w: number, h: number, x: number, y: number, columns: number): { x: number; y: number } {
  const width = Math.min(columns, w)
  const overlaps = (cx: number, cy: number) =>
    layout.some((one) => cx < one.x + one.w && one.x < cx + width && cy < one.y + one.h && one.y < cy + h)
  const startX = Math.max(0, Math.min(columns - width, x))
  for (let row = Math.max(0, y); row < y + 200; row += 1) {
    // The column dropped on first, then the others in that row.
    const order = [startX, ...Array.from({ length: columns - width + 1 }, (_, index) => index).filter((one) => one !== startX)]
    for (const column of order) if (!overlaps(column, row)) return { x: column, y: row }
  }
  return { x: 0, y: Math.max(0, ...layout.map((one) => one.y + one.h)) }
}

/** The cell of the board under a point, measured from the board's top left corner. */
export function cellAt(px: number, py: number, width: number, columns: number, rowHeight: number, gap: number): { x: number; y: number } {
  const column = (width - gap * (columns - 1)) / columns
  return {
    x: Math.max(0, Math.min(columns - 1, Math.floor(px / (column + gap)))),
    y: Math.max(0, Math.floor(py / (rowHeight + gap))),
  }
}
