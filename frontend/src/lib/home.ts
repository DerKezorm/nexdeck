/**
 * Home pages: a free surface of Home Assistant controls. What the server
 * answers, and the arithmetic of the surface: the step things snap to, where
 * a new element lands, the order a phone reads them in.
 */

export interface HomeHeading {
  id: string
  type: 'heading'
  x: number
  y: number
  text: string
}

export type HomeElement = HomeHeading

export interface HomeLayout {
  integration_id: number | null
  elements: HomeElement[]
}

export interface HomeProblem {
  code: string
  message: string
  hint: string
}

export interface HomeAnswer {
  layout: HomeLayout
  version: number
  problem: HomeProblem | null
}

/** Everything on the surface snaps to this many pixels, so rows line up by themselves. */
export const STEP = 8
/** How far from the corner an element may stand; the server keeps the same bound. */
export const MAX_COORD = 20000
/** How long a heading may be; the server cuts at the same length. */
export const MAX_TEXT = 60
/** Room left below the lowest element, so there is always somewhere to drop the next one. */
export const ROOM_BELOW = 160

export function snap(value: number): number {
  return Math.min(MAX_COORD, Math.max(0, Math.round(value / STEP) * STEP))
}

/** An id no element on the page has yet; short, and of the characters the server keeps. */
export function freshId(elements: HomeElement[], random: () => number = Math.random): string {
  const taken = new Set(elements.map((element) => element.id))
  for (;;) {
    const id = `h${Math.floor(random() * 36 ** 6).toString(36)}`
    if (!taken.has(id)) return id
  }
}

/** Where a new element goes: on the left, a row below the lowest one, or in the corner of an empty page. */
export function nextSpot(elements: HomeElement[]): { x: number; y: number } {
  if (elements.length === 0) return { x: 16, y: 16 }
  const lowest = Math.max(...elements.map((element) => element.y))
  return { x: 16, y: snap(lowest + 56) }
}

/** How far apart two elements may stand and still be read as one row. */
export const ROW = 40

/**
 * The order a narrow screen shows the elements in: row by row, left to right.
 * ⚠️ Rows, not pixels: three headings placed side by side by hand stand a few
 * pixels apart, and sorted by the pixel the one a little lower came last.
 */
export function readingOrder(elements: HomeElement[]): HomeElement[] {
  const sorted = [...elements].sort((a, b) => a.y - b.y || a.x - b.x)
  const rows: HomeElement[][] = []
  for (const element of sorted) {
    const row = rows.at(-1)
    if (row && element.y - row[0].y < ROW) row.push(element)
    else rows.push([element])
  }
  return rows.flatMap((row) => row.sort((a, b) => a.x - b.x))
}

/** How tall the surface has to be to hold everything with room to spare. */
export function surfaceHeight(elements: HomeElement[]): number {
  return Math.max(0, ...elements.map((element) => element.y)) + ROOM_BELOW
}
