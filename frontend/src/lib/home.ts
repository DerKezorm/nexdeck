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
  style: LampStyle
}

/**
 * How a lamp is drawn, the ten of the board of sketches (``knoepfe.html``,
 * 19.10.2026): A pill, B round, C chip, D tile, E slider, F ring, G rocker,
 * H dots, I bulb, J knob. The server keeps the same list (``home.STYLES``).
 */
export const LAMP_STYLES = ['pill', 'round', 'chip', 'tile', 'slider', 'ring', 'rocker', 'dots', 'bulb', 'knob'] as const
export type LampStyle = (typeof LAMP_STYLES)[number]

/**
 * The room each style takes on the surface, caption included, in pixels; the
 * sizes of the board of sketches, the pill and the chip at their longest.
 * Placing, the phone and the space below all reckon with it.
 */
export const FOOTPRINT: Record<LampStyle, { width: number; height: number }> = {
  pill: { width: 256, height: 40 },
  round: { width: 72, height: 72 },
  chip: { width: 200, height: 28 },
  tile: { width: 84, height: 84 },
  slider: { width: 176, height: 40 },
  ring: { width: 72, height: 80 },
  rocker: { width: 72, height: 82 },
  dots: { width: 72, height: 96 },
  bulb: { width: 72, height: 90 },
  knob: { width: 72, height: 82 },
}

/** The styles that read as a row of their own on a phone; the others stand side by side. */
export const WIDE_STYLES: ReadonlySet<LampStyle> = new Set(['pill', 'chip', 'slider'])

const HEADING_HEIGHT = 24

/** How tall an element stands on the surface. */
export function heightOf(element: HomeElement): number {
  return element.type === 'light' ? (FOOTPRINT[element.style] ?? FOOTPRINT.pill).height : HEADING_HEIGHT
}

/** How wide an element stands, as far as placing is concerned; a heading reaches as far as a pill. */
export function widthOf(element: HomeElement): number {
  return element.type === 'light' ? (FOOTPRINT[element.style] ?? FOOTPRINT.pill).width : FOOTPRINT.pill.width
}

/** Where the lowest element ends: new things go below it. */
function bottomOf(elements: HomeElement[]): number {
  return Math.max(...elements.map((element) => element.y + heightOf(element)))
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
  /** Hue in degrees and saturation in percent, while lit in a colour. */
  hs?: [number, number] | null
  dims: boolean
  temperature: boolean
  colour: boolean
  /** The whites this lamp has, when it has whites. */
  kelvin_min?: number | null
  kelvin_max?: number | null
}

export interface HomeAnswer {
  layout: HomeLayout
  version: number
  problem: HomeProblem | null
  /** How each placed lamp stands, by element id; ``missing`` when Home Assistant no longer offers it. */
  lights?: Record<string, (LampInfo & { missing: false }) | { missing: true }>
}

/** How a lamp stands, as a switch answers it or the board's stream says it (``home_control``). */
export type LampState = (Partial<LampInfo> & { missing: false }) | { missing: true }

/** The server's answer to a switch: ``confirmed`` when Home Assistant named the lamp among what changed. */
export interface SwitchAnswer {
  ok: true
  confirmed: boolean
  light: LampInfo & { missing: false }
}

/**
 * The page's answer with news of some of its lamps put in. What the news does
 * not say (a name, a room) stays as the page last heard it; a lamp the page
 * does not know is left out, it belongs to a layout this browser has not seen.
 */
export function withLamps(answer: HomeAnswer, news: Record<string, LampState>): HomeAnswer {
  const known = new Set(answer.layout.elements.map((element) => element.id))
  const lights = { ...(answer.lights ?? {}) }
  for (const [id, state] of Object.entries(news)) {
    if (!known.has(id)) continue
    const before = lights[id]
    lights[id] = state.missing ? state : ({ ...(before && !before.missing ? before : {}), ...state } as LampInfo & { missing: false })
  }
  return { ...answer, lights }
}

export interface LightOffer {
  lights: LampInfo[]
  problem: HomeProblem | null
}

// -- what is asked of a lamp ---------------------------------------------------

/** What a lamp is asked to do, in the words the server takes (``HomeSwitchBody``). */
export interface LampWish {
  on?: boolean
  brightness_pct?: number
  kelvin?: number
  hs?: [number, number]
}

/**
 * Two wishes as one, the later one winning. Off is off and takes nothing
 * with it; anything after an off switches on again. A white and a colour
 * take each other's place, as they do in Home Assistant.
 */
export function mergeWish(before: LampWish, after: LampWish): LampWish {
  if (after.on === false) return { on: false }
  const merged: LampWish = before.on === false ? { ...after } : { ...before, ...after }
  if (after.kelvin !== undefined) delete merged.hs
  if (after.hs !== undefined) delete merged.kelvin
  if (merged.on === undefined && before.on === false) merged.on = true
  return merged
}

/** The colour of a hue and saturation at full value, as Home Assistant and Python's ``colorsys`` reckon it. */
export function hsToRgb(hue: number, saturation: number): [number, number, number] {
  const h = (((hue % 360) + 360) % 360) / 60
  const s = Math.min(100, Math.max(0, saturation)) / 100
  const sector = Math.floor(h)
  const f = h - sector
  const [p, q, t] = [1 - s, 1 - s * f, 1 - s * (1 - f)]
  const [r, g, b] = [[1, t, p], [q, 1, p], [p, 1, t], [p, q, 1], [t, p, 1], [1, p, q]][sector % 6]
  return [Math.round(r * 255), Math.round(g * 255), Math.round(b * 255)]
}

/** Hue and saturation of a colour, the way back from ``hsToRgb``: for a lamp that names its colour only in rgb. */
export function rgbToHs([red, green, blue]: [number, number, number]): [number, number] {
  const [r, g, b] = [red / 255, green / 255, blue / 255]
  const high = Math.max(r, g, b)
  const span = high - Math.min(r, g, b)
  if (high === 0 || span === 0) return [0, 0]
  const sector = high === r ? ((g - b) / span + 6) % 6 : high === g ? (b - r) / span + 2 : (r - g) / span + 4
  return [Math.round(sector * 60 * 10) / 10, Math.round((span / high) * 1000) / 10]
}

/** A lamp as it will stand once the wish is done: what the pill and the panel show while it travels. */
export function withWish(info: LampInfo, wish: LampWish | undefined): LampInfo {
  if (!wish) return info
  const on = wish.on ?? (wish.brightness_pct !== undefined || wish.kelvin !== undefined || wish.hs !== undefined ? true : info.on)
  if (!on) return { ...info, on: false, pct: null }
  const shown: LampInfo = { ...info, on: true, pct: wish.brightness_pct ?? info.pct ?? (info.dims ? 100 : null) }
  if (wish.kelvin !== undefined) return { ...shown, kelvin: wish.kelvin, rgb: null, hs: null }
  if (wish.hs !== undefined) return { ...shown, hs: wish.hs, rgb: hsToRgb(wish.hs[0], wish.hs[1]), kelvin: null }
  return shown
}

/**
 * How long a lamp shows what was asked when Home Assistant has not named it
 * among what changed, before it shows what the server knows: a lamp that
 * never came is taken back, one that comes late arrives over the stream first.
 */
export const SETTLE_MS = 2500

/**
 * Sends one lamp's wishes, the newest winning: while one is on its way, what
 * comes after is gathered into the next, and two leave at least ``gap``
 * apart. Dragging a slider asks a hundred times a second; Home Assistant
 * hears about three times, and always the last.
 */
export function lampSender(send: (wish: LampWish) => Promise<unknown>, gap = 300, now: () => number = () => Date.now()) {
  let waiting: LampWish | null = null
  let travelling = false
  let last = -Infinity
  let timer: ReturnType<typeof setTimeout> | undefined
  const pump = () => {
    if (travelling || !waiting || timer !== undefined) return
    const wait = last + gap - now()
    if (wait > 0) {
      timer = setTimeout(() => {
        timer = undefined
        pump()
      }, wait)
      return
    }
    const wish = waiting
    waiting = null
    travelling = true
    last = now()
    void send(wish).finally(() => {
      travelling = false
      pump()
    })
  }
  return {
    ask(wish: LampWish) {
      waiting = waiting ? mergeWish(waiting, wish) : wish
      pump()
    },
    /** Something is on its way or waiting to go. */
    busy: () => travelling || waiting !== null,
    /** A wish waits behind the one on its way; asked from inside ``send``, where that one still travels. */
    queued: () => waiting !== null,
  }
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

/** The room between two lamps placed together. */
export const LAMP_GAP = 16
/** How wide a row of lamps placed together may grow: four pills, a dozen rounds. */
export const ROW_WIDTH = 1088

/**
 * Where lamps added together go: side by side in rows, below everything that
 * stands already, as far apart as their style is wide, so they never overlap.
 */
export function lampSpots(elements: HomeElement[], count: number, style: LampStyle = 'pill'): { x: number; y: number }[] {
  const { width, height } = FOOTPRINT[style]
  const top = elements.length === 0 ? 16 : snap(bottomOf(elements) + LAMP_GAP)
  // Up to the next step, never down: a pitch rounded down would eat into the gap.
  const pitchX = Math.ceil((width + LAMP_GAP) / STEP) * STEP
  const pitchY = Math.ceil((height + LAMP_GAP) / STEP) * STEP
  const across = Math.max(1, Math.floor((ROW_WIDTH - width) / pitchX) + 1)
  return Array.from({ length: count }, (_, index) => ({ x: 16 + (index % across) * pitchX, y: top + Math.floor(index / across) * pitchY }))
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
  return { x: 16, y: snap(bottomOf(elements) + LAMP_GAP) }
}

/** How far apart two elements may stand and still be read as one row. */
export const ROW = 40

/**
 * The order a narrow screen shows the elements in: row by row, left to right.
 * ⚠️ Rows, not pixels: three headings placed side by side by hand stand a few
 * pixels apart, and sorted by the pixel the one a little lower came last.
 */
export function readingOrder<T extends HomeElement>(elements: T[]): T[] {
  const sorted = [...elements].sort((a, b) => a.y - b.y || a.x - b.x)
  const rows: T[][] = []
  for (const element of sorted) {
    const row = rows.at(-1)
    if (row && element.y - row[0].y < ROW) row.push(element)
    else rows.push([element])
  }
  return rows.flatMap((row) => row.sort((a, b) => a.x - b.x))
}

/** How tall the surface has to be to hold everything with room to spare. */
export function surfaceHeight(elements: HomeElement[]): number {
  return Math.max(0, ...elements.map((element) => element.y + heightOf(element))) + ROOM_BELOW
}

/** A heading of the phone's list and the lamps under it; the first group has none, for lamps above every heading. */
export interface PhoneGroup {
  heading: HomeHeading | null
  lamps: HomeLight[]
}

/**
 * The page read on a phone: each heading with the lamps that stand under it
 * on the surface. A lamp belongs to the lowest heading above it whose
 * column it stands in, that is the heading furthest to the right that
 * starts left of the lamp's middle. Lamps above every heading come first.
 *
 * ⚠️ Read row by row instead, three headings side by side came first and all
 * their lamps after them, every room's lamps under the last room's name.
 */
export function phoneGroups(elements: HomeElement[]): PhoneGroup[] {
  const headings = readingOrder(elements.filter((element): element is HomeHeading => element.type === 'heading'))
  const lamps = readingOrder(elements.filter((element): element is HomeLight => element.type === 'light'))
  const groups: PhoneGroup[] = [{ heading: null, lamps: [] }, ...headings.map((heading) => ({ heading, lamps: [] as HomeLight[] }))]
  for (const lamp of lamps) {
    const middle = lamp.x + widthOf(lamp) / 2
    let owner: PhoneGroup = groups[0]
    for (const group of groups.slice(1)) {
      const heading = group.heading as HomeHeading
      if (heading.y > lamp.y + STEP || heading.x > middle) continue
      const best = owner.heading
      if (!best || heading.y > best.y + ROW || (Math.abs(heading.y - best.y) <= ROW && heading.x > best.x)) owner = group
    }
    owner.lamps.push(lamp)
  }
  return groups.filter((group) => group.heading || group.lamps.length)
}
