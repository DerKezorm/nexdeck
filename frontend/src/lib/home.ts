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

/**
 * A lamp, kept by its registry id; the entity id and name are as they were
 * when it was placed, for when Home Assistant cannot be asked.
 */
export interface HomeLight {
  id: string
  type: 'light'
  x: number
  y: number
  rid: string
  entity_id: string
  name: string
  style: 'pill'
}

export type HomeElement = HomeHeading | HomeLight

export interface HomeLayout {
  integration_id: number | null
  elements: HomeElement[]
}

export interface HomeProblem {
  code: string
  message: string
  hint: string
}

/** A lamp as Home Assistant reports it (``hass_registry.pick_lights``). */
export interface LampInfo {
  rid: string
  entity_id: string
  name: string
  area: string
  device: string
  group: boolean
  on: boolean
  unavailable: boolean
  pct: number | null
  rgb: [number, number, number] | null
  kelvin: number | null
  dims: boolean
  temperature: boolean
  colour: boolean
}

export interface HomeAnswer {
  layout: HomeLayout
  version: number
  problem: HomeProblem | null
  /** How each placed lamp stands, by element id; ``missing`` when Home Assistant no longer offers it. */
  lights?: Record<string, (LampInfo & { missing: false }) | { missing: true }>
}

export interface LightOffer {
  lights: LampInfo[]
  problem: HomeProblem | null
}

/** The colour a lit lamp gives off: its own colour, its white, or a warm white when it says neither. */
export function lampColour(info: Pick<LampInfo, 'on' | 'rgb' | 'kelvin'> | null | undefined): string | null {
  if (!info?.on) return null
  if (info.rgb) return `rgb(${info.rgb[0]}, ${info.rgb[1]}, ${info.rgb[2]})`
  if (info.kelvin) {
    const t = Math.min(1, Math.max(0, (info.kelvin - 2200) / (6500 - 2200)))
    const warm = [255, 176, 96]
    const cool = [226, 236, 255]
    return `rgb(${warm.map((channel, index) => Math.round(channel + (cool[index] - channel) * t)).join(', ')})`
  }
  return 'rgb(255, 196, 120)'
}

/** How far apart lamps added together stand, and how many share a row. */
/** A pill is at most 256 pixels wide (``max-w`` in HomePage), so lamps placed together never overlap. */
export const LAMP_PITCH = 272
export const LAMPS_PER_ROW = 4

/** Where lamps added together go: side by side in rows, below everything that stands already. */
export function lampSpots(elements: HomeElement[], count: number): { x: number; y: number }[] {
  const top = elements.length === 0 ? 16 : snap(Math.max(...elements.map((element) => element.y)) + 56)
  return Array.from({ length: count }, (_, index) => ({ x: 16 + (index % LAMPS_PER_ROW) * LAMP_PITCH, y: top + Math.floor(index / LAMPS_PER_ROW) * 56 }))
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
