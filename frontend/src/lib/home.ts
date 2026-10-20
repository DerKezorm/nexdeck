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
  /** A name of the page's own, shown instead of Home Assistant's; it stays when the lamp is renamed there. */
  label?: string
  /** A width of its own, for the styles that have one (``RESIZABLE``); otherwise the style's (``DEFAULT_WIDTH``). */
  width?: number
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

/**
 * The width a control with a name in it has unless it was given one: the
 * same for every pill, chip or slider, whatever its name, so a row of them
 * lines up. A name too long for it runs as a ticker (``Marquee``).
 */
export const DEFAULT_WIDTH = {
  pill: 224, chip: 176, slider: 176, climate: 320, climateChip: 200, climateSlider: 230,
  contact: 264, contactChip: 150, reading: 250, contacts: 300, house: 380, readings: 400, hints: 330,
} as const
/** The bounds of a width dragged by hand; the server keeps the same. */
export const MIN_WIDTH = 96
export const MAX_WIDTH = 640

/** Whether an element has a width to drag: the pill, the chip, the slider and a thermostat. */
export function isResizable(element: HomeElement): element is Sized {
  if (element.type === 'contacts' || element.type === 'readings' || element.type === 'hints') return true
  if (element.type === 'contact') return element.style === 'pill' || element.style === 'chip'
  if (element.type === 'reading') return element.style === 'pill'
  return (element.type === 'light' || element.type === 'climate') && (element.style === 'pill' || element.style === 'chip' || element.style === 'slider')
}

/** The width a control is drawn at on the surface, or null for a style whose size is its drawing. */
export function controlWidth(element: HomeElement): number | null {
  if (!isResizable(element)) return null
  const fallback = element.type === 'climate'
    ? { pill: DEFAULT_WIDTH.climate, chip: DEFAULT_WIDTH.climateChip, slider: DEFAULT_WIDTH.climateSlider }[element.style as 'pill' | 'chip' | 'slider']
    : element.type === 'light' ? DEFAULT_WIDTH[element.style as 'pill' | 'chip' | 'slider']
    : element.type === 'contact' ? (element.style === 'chip' ? DEFAULT_WIDTH.contactChip : DEFAULT_WIDTH.contact)
    : element.type === 'reading' ? DEFAULT_WIDTH.reading
    : element.type === 'contacts' ? (element.style === 'house' ? DEFAULT_WIDTH.house : DEFAULT_WIDTH.contacts)
    : element.type === 'readings' ? DEFAULT_WIDTH.readings
    : DEFAULT_WIDTH.hints
  return Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, element.width ?? fallback))
}

/** The room a thermostat's pill takes: name, reading, minus, target, plus. */
export const CLIMATE_FOOTPRINT = { width: 320, height: 40 }
/** The thermostat styles that read as a row of their own on a phone. */
export const WIDE_CLIMATE_STYLES: ReadonlySet<string> = new Set(['pill', 'chip', 'slider'])

/** Whether an element runs the width of a phone's screen: a thermostat and a lamp by their style, a card unless it is a small one. */
export function isWide(element: HomeItem): boolean {
  if (element.type === 'stat') return element.style !== 'small'
  if (element.type === 'contacts' || element.type === 'readings' || element.type === 'hints') return true
  if (element.type === 'contact' || element.type === 'reading') return element.style === 'pill'
  return element.type === 'climate' ? WIDE_CLIMATE_STYLES.has(element.style) : WIDE_STYLES.has(element.style)
}

const HEADING_HEIGHT = 24

/** How tall an element stands on the surface. */
export function heightOf(element: HomeElement): number {
  if (element.type === 'stat') return statSize(element).height
  if (element.type === 'contact') return (CONTACT_FOOTPRINTS[element.style] ?? CONTACT_FOOTPRINTS.pill).height
  if (element.type === 'reading') return (READING_FOOTPRINTS[element.style] ?? READING_FOOTPRINTS.pill).height
  if (element.type === 'contacts') return element.style === 'house' ? 48 + Math.ceil(roomsOf(element).length / 4) * 56 : 44 + 26 * Math.min(6, element.sensors.length)
  if (element.type === 'readings') return 52 + 33 * element.rows.length
  if (element.type === 'hints') return 156
  if (element.type === 'climate') return (CLIMATE_FOOTPRINTS[element.style] ?? CLIMATE_FOOTPRINT).height
  return element.type === 'light' ? (FOOTPRINT[element.style] ?? FOOTPRINT.pill).height : HEADING_HEIGHT
}

/** How wide an element stands, as far as placing is concerned; a heading reaches as far as a pill. */
export function widthOf(element: HomeElement): number {
  if (element.type === 'stat') return statSize(element).width
  if (element.type === 'contact') return controlWidth(element) ?? (CONTACT_FOOTPRINTS[element.style] ?? CONTACT_FOOTPRINTS.pill).width
  if (element.type === 'reading') return controlWidth(element) ?? (READING_FOOTPRINTS[element.style] ?? READING_FOOTPRINTS.pill).width
  if (element.type === 'contacts' || element.type === 'readings' || element.type === 'hints') return controlWidth(element) ?? DEFAULT_WIDTH.hints
  if (isResizable(element) && element.width !== undefined) return controlWidth(element) ?? FOOTPRINT.pill.width
  if (element.type === 'climate') return (CLIMATE_FOOTPRINTS[element.style] ?? CLIMATE_FOOTPRINT).width
  return element.type === 'light' ? (FOOTPRINT[element.style] ?? FOOTPRINT.pill).width : FOOTPRINT.pill.width
}

/** Where the lowest element ends: new things go below it. */
function bottomOf(elements: HomeElement[]): number {
  return Math.max(...elements.map((element) => element.y + heightOf(element)))
}

/** The sensor a thermostat reads its room by, kept as a lamp is: by registry id, with the name it had. */
export interface ClimateSensor {
  rid: string
  entity_id: string
  name: string
}

/** A thermostat, kept like a lamp; ``sensor`` null reads the room by the thermostat itself. */
export interface HomeClimate {
  id: string
  type: 'climate'
  x: number
  y: number
  rid: string
  entity_id: string
  name: string
  style: ClimateStyle
  sensor: ClimateSensor | null
  /** A name of the page's own, as a lamp has one. */
  label?: string
  /** A width of its own; otherwise ``DEFAULT_WIDTH.climate``. */
  width?: number
}

/**
 * How a thermostat is drawn, the ten of its board of sketches (``heizung.html``,
 * 20.10.2026): A pill, B round, C chip, D tile, E slider, F dial, G valve head,
 * H thermometer, I radiator, J big digits. The server keeps the same list.
 */
export const CLIMATE_STYLES = ['pill', 'round', 'chip', 'tile', 'slider', 'dial', 'valve', 'thermometer', 'radiator', 'digits'] as const
export type ClimateStyle = (typeof CLIMATE_STYLES)[number]

/** The room each thermostat style takes on the surface, caption included. */
export const CLIMATE_FOOTPRINTS: Record<ClimateStyle, { width: number; height: number }> = {
  pill: { width: 320, height: 40 },
  round: { width: 84, height: 104 },
  chip: { width: 200, height: 28 },
  tile: { width: 96, height: 96 },
  slider: { width: 230, height: 40 },
  dial: { width: 100, height: 124 },
  valve: { width: 84, height: 104 },
  thermometer: { width: 100, height: 132 },
  radiator: { width: 96, height: 112 },
  digits: { width: 150, height: 84 },
}

/**
 * The step a tap, a swipe or an arrow key moves a target by: the device's own,
 * but at least half a degree (a degree in Fahrenheit). Nine of 26 thermostats
 * measured on 20.10.2026 step in tenths, and a degree warmer was ten taps.
 * The slider in the details keeps the device's own step for the fine tuning.
 */
export function handStep(info: Pick<ClimateInfo, 'step' | 'unit'>): number {
  return Math.max(info.step > 0 ? info.step : 0.5, info.unit === '°F' ? 1 : 0.5)
}

/** The thermostat as a hand sets it: with ``handStep`` instead of its own step. */
export function byHand<T extends Pick<ClimateInfo, 'step' | 'unit'>>(info: T): T {
  return { ...info, step: handStep(info) }
}

/** How many pixels a finger travels sideways for one step of a thermostat's target. */
export const STEP_PX = 12

/**
 * The target at a share of a thermostat's range, for a dial turned by a
 * finger: on its step and inside its bounds, as ``stepTarget``.
 */
export function targetAt(info: Pick<ClimateInfo, 'step' | 'min' | 'max'>, share: number): number {
  return stepTarget(info, info.min + Math.min(1, Math.max(0, share)) * (info.max - info.min), 0)
}

/** Where a value stands in a thermostat's range, from 0 at its minimum to 1 at its maximum. */
export function shareOf(info: Pick<ClimateInfo, 'min' | 'max'>, value: number | null | undefined): number {
  if (value === null || value === undefined || info.max <= info.min) return 0
  return Math.min(1, Math.max(0, (value - info.min) / (info.max - info.min)))
}

/** What stands on a page and is switched or set: a lamp or a thermostat. */
export type HomeDevice = HomeLight | HomeClimate

/**
 * A statistics card: one to six sensors, drawn from what Home Assistant
 * remembers of them (``hass_stats``), in a style of its board of sketches
 * (``statistik.html``, 20.10.2026). Its size is its own, dragged at the corner.
 */
export interface HomeStat {
  id: string
  type: 'stat'
  x: number
  y: number
  style: StatStyle
  sensors: ClimateSensor[]
  /** What the card is called; empty for the first sensor's name. */
  title: string
  width?: number
  height?: number
}

/** A: one sensor as a line, B: rooms on one axis, C: a band of low to high, D: bars of a counter, E: small, F: today over yesterday. */
export const STAT_STYLES = ['line', 'rooms', 'band', 'bars', 'small', 'compare'] as const
export type StatStyle = (typeof STAT_STYLES)[number]
/** The periods a card switches between, by style; the first is where it starts. The server keeps the same (``hass_stats``). */
export type StatPeriod = '24h' | '7d' | '30d' | '1y' | 'day' | 'week'
export const STAT_PERIODS: Record<StatStyle, StatPeriod[]> = {
  line: ['24h', '7d', '30d'],
  rooms: ['24h', '7d', '30d'],
  band: ['7d', '30d', '1y'],
  bars: ['7d', '30d', '1y'],
  small: ['24h'],
  compare: ['day', 'week'],
}
/** The period a card starts in, as on the board of sketches: a day of one room, a week of several, a month of a band. */
export const STAT_START: Record<StatStyle, StatPeriod> = { line: '24h', rooms: '7d', band: '30d', bars: '7d', small: '24h', compare: 'day' }
/** The size of each style unless it was given one, as on the board of sketches. */
export const STAT_SIZES: Record<StatStyle, { width: number; height: number }> = {
  line: { width: 360, height: 190 },
  rooms: { width: 520, height: 210 },
  band: { width: 360, height: 190 },
  bars: { width: 360, height: 190 },
  small: { width: 170, height: 104 },
  compare: { width: 360, height: 190 },
}
/** The bounds of a card's size; the server keeps the same (``STAT_WIDTHS``, ``STAT_HEIGHTS``). */
export const STAT_WIDTHS = [150, 1200] as const
export const STAT_HEIGHTS = [80, 800] as const
/** How many sensors a card shows at most, and the styles that show one. */
export const MAX_SENSORS = 6
export const ONE_SENSOR: ReadonlySet<StatStyle> = new Set(['line', 'band', 'bars', 'small', 'compare'])

/** The size a card is drawn at. */
export function statSize(element: HomeStat): { width: number; height: number } {
  const fallback = STAT_SIZES[element.style] ?? STAT_SIZES.line
  const clamp = (value: number | undefined, [low, high]: readonly [number, number], or: number) => Math.min(high, Math.max(low, value ?? or))
  return { width: clamp(element.width, STAT_WIDTHS, fallback.width), height: clamp(element.height, STAT_HEIGHTS, fallback.height) }
}

/** Anything on the surface that is not a heading: what a phone lists under one. */
export type HomeItem = HomeDevice | HomeStat | HomeSensorElement

export type HomeElement = HomeHeading | HomeLight | HomeClimate | HomeStat | HomeSensorElement

/** What has a width to drag. */
export type Sized = HomeDevice | HomeContact | HomeReading | HomeContacts | HomeReadings | HomeHints

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

/** A thermostat as Home Assistant reports it (``hass_registry.climate_state``). */
export interface ClimateInfo {
  rid: string
  entity_id: string
  name: string
  area: string
  device: string
  unavailable: boolean
  on: boolean
  mode: string | null
  modes: string[]
  /** What it is doing, only when the device says: heating, cooling, idle, off. */
  action: string | null
  current: number | null
  target: number | null
  target_low: number | null
  target_high: number | null
  /** It takes a single target temperature. */
  settable: boolean
  min: number
  max: number
  step: number
  preset: string | null
  presets: string[]
  unit: string
}

/** A placed thermostat as the page shows it: the room read by its sensor where that one answers (``climate_view``). */
export interface ClimateView extends ClimateInfo {
  reading: number | null
  /** The sensor it reads its room by: ``ok``, or ``missing``/``unavailable`` while the thermostat's own reading stands in. */
  sensor: { name: string; state: 'ok' | 'missing' | 'unavailable' } | null
}

/** A temperature sensor a thermostat may read its room by (``pick_temperature_sensors``). */
export interface SensorInfo {
  rid: string
  entity_id: string
  name: string
  area: string
  device: string
  current: number | null
  unit: string
  unavailable: boolean
}

export interface ClimateOffer {
  climates: ClimateInfo[]
  sensors: SensorInfo[]
  problem: HomeProblem | null
}

export interface HomeAnswer {
  layout: HomeLayout
  version: number
  problem: HomeProblem | null
  /** How each placed lamp stands, by element id; ``missing`` when Home Assistant no longer offers it. */
  lights?: Record<string, (LampInfo & { missing: false }) | { missing: true }>
  /** How each placed thermostat stands, by element id. */
  climates?: Record<string, (ClimateView & { missing: false }) | { missing: true }>
  /** How each sensor of the page's doors, windows and readings stands, by the entity id it was placed with. */
  sensors?: Record<string, SensorState>
}

/** How a thermostat stands, as an answer or the board's stream says it. */
export type ClimateState = (Partial<ClimateView> & { missing: false }) | { missing: true }

/** The server's answer to a thermostat being set; ``confirmed`` as with a lamp. */
export interface ClimateAnswer {
  ok: true
  confirmed: boolean
  climate: ClimateView & { missing: false }
}

/** What a thermostat is asked: one thing at a time (``HomeClimateBody``). */
export type ClimateWish = { target: number } | { mode: string } | { preset: string }

/** The news the board's stream brings of a home page (``home_control.HomeLive``). */
export interface HomeNews {
  page_id: number
  lights?: Record<string, LampState>
  climates?: Record<string, ClimateState>
  sensors?: Record<string, SensorState>
}

/** The page's answer with news of its thermostats put in, the way ``withLamps`` does for lamps. */
export function withClimates(answer: HomeAnswer, news: Record<string, ClimateState>): HomeAnswer {
  const known = new Set(answer.layout.elements.map((element) => element.id))
  const climates = { ...(answer.climates ?? {}) }
  for (const [id, state] of Object.entries(news)) {
    if (!known.has(id)) continue
    const before = climates[id]
    climates[id] = state.missing ? state : ({ ...(before && !before.missing ? before : {}), ...state } as ClimateView & { missing: false })
  }
  return { ...answer, climates }
}

/** Everything the stream says of a page, put into its answer. */
export function withNews(answer: HomeAnswer, news: HomeNews): HomeAnswer {
  const lit = news.lights ? withLamps(answer, news.lights) : answer
  const warm = news.climates ? withClimates(lit, news.climates) : lit
  return news.sensors ? withSensors(warm, news.sensors) : warm
}

/**
 * A thermostat's target moved by some steps of its own, on its step and
 * inside its bounds, as its own buttons move it; the server does the same.
 */
export function stepTarget(info: Pick<ClimateInfo, 'step' | 'min' | 'max'>, from: number, steps: number): number {
  const step = info.step > 0 ? info.step : 0.5
  const places = from / step
  const onStep = Math.abs(places - Math.round(places)) < 1e-6
  // Off the step (21.3 on halves), the first step goes to the next mark in its direction: 21.5 up, 21 down.
  const moved = onStep || steps === 0
    ? Math.round((from + steps * step) / step) * step
    : (steps > 0 ? Math.ceil(places) + steps - 1 : Math.floor(places) + steps + 1) * step
  return Math.round(Math.min(info.max, Math.max(info.min, moved)) * 100) / 100
}

/** A temperature as a page writes it: one decimal where it has one, the unit's degree sign. */
export function temperature(value: number | null | undefined): string {
  if (value === null || value === undefined) return '–'
  const shown = Number.isInteger(value) ? String(value) : value.toFixed(1)
  return `${shown}°`
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
  return spotsFor(elements, count, FOOTPRINT[style])
}

/** Where thermostats added together go, as lamps do. */
export function climateSpots(elements: HomeElement[], count: number, style: ClimateStyle = 'pill'): { x: number; y: number }[] {
  return spotsFor(elements, count, CLIMATE_FOOTPRINTS[style])
}

function spotsFor(elements: HomeElement[], count: number, { width, height }: { width: number; height: number }): { x: number; y: number }[] {
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

/** A box on the surface: where it stands and how big it is drawn. */
export interface Box {
  x: number
  y: number
  width: number
  height: number
}

/** A guide line while dragging: along x (a vertical line) or y (a horizontal one), from where to where. */
export interface Guide {
  axis: 'x' | 'y'
  at: number
  from: number
  to: number
}

/** How close an edge or a middle has to come to another's before it snaps there, in pixels. */
export const ALIGN_PX = 6

/**
 * Where a dragged box goes when it comes close to lining up with another:
 * its left edge, middle or right edge onto another's left edge, middle or
 * right edge, and the same for top, middle and bottom. Each axis takes the
 * nearest match within ``ALIGN_PX`` of where the pointer put it; without one,
 * that axis stays where the step of the surface put it. The lines say what
 * lines up, for the page to draw.
 */
export function alignTo(raw: Box, stepped: { x: number; y: number }, others: Box[], near = ALIGN_PX): { x: number; y: number; guides: Guide[] } {
  const marks = (box: Box, axis: 'x' | 'y') =>
    axis === 'x' ? [box.x, box.x + box.width / 2, box.x + box.width] : [box.y, box.y + box.height / 2, box.y + box.height]
  const settle = (axis: 'x' | 'y'): { at: number | null; line: number | null; with: Box[] } => {
    let best: { shift: number; line: number } | null = null
    const own = marks(raw, axis)
    for (const other of others) {
      for (const theirs of marks(other, axis)) {
        for (const mine of own) {
          const shift = theirs - mine
          if (Math.abs(shift) <= near && (best === null || Math.abs(shift) < Math.abs(best.shift))) best = { shift, line: theirs }
        }
      }
    }
    if (best === null) return { at: null, line: null, with: [] }
    const line = best.line
    const placed = { ...raw, [axis]: raw[axis] + best.shift }
    // Every other box on that line, so the guide runs from the first to the last of them.
    const lined = others.filter((other) => marks(other, axis).some((mark) => Math.abs(mark - line) < 0.5))
    return { at: Math.round(placed[axis]), line, with: [placed, ...lined] }
  }
  const across = settle('x')
  const down = settle('y')
  const x = across.at ?? stepped.x
  const y = down.at ?? stepped.y
  const guides: Guide[] = []
  if (across.line !== null) {
    const boxes = across.with.map((box, index) => (index === 0 ? { ...box, y } : box))
    guides.push({ axis: 'x', at: across.line, from: Math.min(...boxes.map((box) => box.y)), to: Math.max(...boxes.map((box) => box.y + box.height)) })
  }
  if (down.line !== null) {
    const boxes = down.with.map((box, index) => (index === 0 ? { ...box, x } : box))
    guides.push({ axis: 'y', at: down.line, from: Math.min(...boxes.map((box) => box.x)), to: Math.max(...boxes.map((box) => box.x + box.width)) })
  }
  return { x: Math.max(0, x), y: Math.max(0, y), guides }
}

/**
 * The width a control dragged at its edge settles on: on the step of the
 * surface, inside ``MIN_WIDTH`` and ``MAX_WIDTH``, and, near enough, as wide
 * as another one or ending where another one ends or begins.
 */
export function resizeTo(box: Box, raw: number, others: Box[], near = ALIGN_PX): { width: number; guides: Guide[] } {
  const bounded = (width: number) => Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.round(width)))
  let best: { width: number; edge: number | null; same: Box | null } | null = null
  for (const other of others) {
    const candidates: { width: number; edge: number | null; same: Box | null }[] = [
      { width: other.width, edge: null, same: other },
      ...[other.x, other.x + other.width / 2, other.x + other.width].map((edge) => ({ width: edge - box.x, edge, same: null })),
    ]
    for (const candidate of candidates) {
      if (candidate.width < MIN_WIDTH || Math.abs(candidate.width - raw) > near) continue
      if (best === null || Math.abs(candidate.width - raw) < Math.abs(best.width - raw)) best = candidate
    }
  }
  if (best === null) return { width: bounded(snap(raw)), guides: [] }
  const width = bounded(best.width)
  if (best.same) {
    // As wide as another: a line under each of the two.
    const mark = (target: Box, size: number): Guide => ({ axis: 'y', at: target.y + target.height + 4, from: target.x, to: target.x + size })
    return { width, guides: [mark(box, width), mark(best.same, best.same.width)] }
  }
  const lined = others.filter((other) => [other.x, other.x + other.width / 2, other.x + other.width].some((mark) => Math.abs(mark - (box.x + width)) < 0.5))
  const all = [box, ...lined]
  return { width, guides: [{ axis: 'x', at: box.x + width, from: Math.min(...all.map((one) => one.y)), to: Math.max(...all.map((one) => one.y + one.height)) }] }
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

/** A heading of the phone's list and the lamps and thermostats under it; the first group has none, for those above every heading. */
export interface PhoneGroup {
  heading: HomeHeading | null
  devices: HomeItem[]
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
  const lamps = readingOrder(elements.filter((element): element is HomeItem => element.type !== 'heading'))
  const groups: PhoneGroup[] = [{ heading: null, devices: [] }, ...headings.map((heading) => ({ heading, devices: [] as HomeItem[] }))]
  for (const lamp of lamps) {
    const middle = lamp.x + widthOf(lamp) / 2
    let owner: PhoneGroup = groups[0]
    for (const group of groups.slice(1)) {
      const heading = group.heading as HomeHeading
      if (heading.y > lamp.y + STEP || heading.x > middle) continue
      const best = owner.heading
      if (!best || heading.y > best.y + ROW || (Math.abs(heading.y - best.y) <= ROW && heading.x > best.x)) owner = group
    }
    owner.devices.push(lamp)
  }
  return groups.filter((group) => group.heading || group.devices.length)
}

// ---------------------------------------------------------------------------
// Statistics
// ---------------------------------------------------------------------------

/** A sensor a statistics card can show (``hass_stats.pick_sensors``). */
export interface StatSensorInfo extends SensorInfo {
  device_class: string
  /** ``sum`` for a counter (its change per step), ``mean`` for a measurement. */
  kind: 'mean' | 'sum'
  /** Long-term statistics reach back as far as Home Assistant keeps them; a history only its ten days or so. */
  source: 'statistics' | 'history'
}

export interface StatOffer {
  sensors: StatSensorInfo[]
  problem: HomeProblem | null
}

/** ``[start, mean, low, high]`` of a measurement, ``[start, change]`` of a counter; times in milliseconds. */
export type StatPoint = [number, number, number, number] | [number, number]

export interface StatSummary {
  low: [number, number] | null
  high: [number, number] | null
  mean: number | null
  total: number | null
}

export type StatLine = {
  missing: false
  rid: string
  entity_id: string
  name: string
  unit: string
  kind: 'mean' | 'sum'
  source: 'statistics' | 'history'
  current: number | null
  unavailable: boolean
  step: string
  points: StatPoint[]
  /** A comparison's period before, its times moved onto this one. */
  previous?: StatPoint[]
  previous_summary?: StatSummary
  /** A counter's last step, today's so far. */
  latest?: number
} & StatSummary

export type StatSeries = StatLine | { missing: true }

export interface StatAnswer {
  period: StatPeriod
  start: number
  end: number
  now: number
  zone: string
  series: StatSeries[]
  problem: HomeProblem | null
}

/** A thermostat's day or week (``hass_stats.climate_history``). */
export interface ClimateHistory {
  period: '24h' | '7d'
  start: number
  end: number
  zone: string
  step: string
  room: StatPoint[]
  /** Its target as it changed, null while it was off. */
  target: [number, number | null][]
  /** When it heated; null for a thermostat that never says. */
  heating: [number, number][] | null
  today: { low: number | null; high: number | null; heated: number | null }
  yesterday: { heated: number | null }
  sensor: string | null
  problem: HomeProblem | null
}

/** A value as a card writes it: a degree with one decimal, anything else with its unit. */
export function reading(value: number | null | undefined, unit: string): string {
  if (value === null || value === undefined) return '–'
  if (unit === '°C' || unit === '°F' || unit === '°') return temperature(Math.round(value * 10) / 10)
  const rounded = Math.abs(value) >= 100 ? Math.round(value) : Math.round(value * 10) / 10
  return unit === '%' ? `${rounded} %` : unit ? `${rounded} ${unit}` : String(rounded)
}

/** How long, as a card writes heating times: "3 h 20", "45 min". */
export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '–'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min`
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, '0')}`
}

/**
 * The range a chart's axis spans: the values with a little room, on whole
 * numbers, never flat. A counter's bars stand on zero.
 */
export function axisRange(values: number[], fromZero = false): [number, number] {
  const finite = values.filter((value) => Number.isFinite(value))
  if (finite.length === 0) return [0, 1]
  let low = Math.min(...finite)
  let high = Math.max(...finite)
  if (fromZero) low = Math.min(0, low)
  const room = Math.max((high - low) * 0.12, 0.5)
  low = fromZero && low >= 0 ? 0 : Math.floor(low - room)
  high = Math.ceil(high + room)
  return high > low ? [low, high] : [low, low + 1]
}

/** Where new cards go: below everything, side by side as lamps are. */
export function statSpots(elements: HomeElement[], count: number, style: StatStyle): { x: number; y: number }[] {
  return spotsFor(elements, count, STAT_SIZES[style])
}

// ---------------------------------------------------------------------------
// Sensors: doors and windows, temperature and humidity (``hass_sensors``)
// ---------------------------------------------------------------------------

/**
 * The styles of the board of sketches (``sensoren.html``, 20.10.2026): a
 * door or window as A pill, B chip, C tile, D window, E door; several on one
 * card as F list or G house; a reading as H pill, I tile, J thermometer,
 * K ring; L a list of rooms; M hints. The server keeps the same lists.
 */
export const CONTACT_STYLES = ['pill', 'chip', 'tile', 'window', 'door'] as const
export type ContactStyle = (typeof CONTACT_STYLES)[number]
export const CONTACTS_STYLES = ['list', 'house'] as const
export type ContactsStyle = (typeof CONTACTS_STYLES)[number]
export const READING_STYLES = ['pill', 'tile', 'thermometer', 'ring'] as const
export type ReadingStyle = (typeof READING_STYLES)[number]
/** What a hints card looks for: a window open while the heating of its room runs, a room that wants airing. */
export const CHECKS = ['heating', 'humid'] as const
export type Check = (typeof CHECKS)[number]
/** From how much humidity a room wants airing, and the band that feels right. */
export const HUMID_PCT = 65
export const COMFORT = [40, 60] as const
/**
 * Words that put a sensor outdoors, in the five languages of the page: an
 * outdoor humidity of 91 % is weather, not a room that wants airing.
 */
export const OUTDOORS = ['outdoor', 'outside', 'exterior', 'garden', 'balcony', 'terrace', 'patio', 'weather', 'außen', 'aussen', 'draußen', 'draussen', 'garten',
  'balkon', 'terrasse', 'wetter', 'jardín', 'jardin', 'balcón', 'terraza', 'extérieur', 'exterieur', 'balcon', 'météo', 'esterno', 'giardino', 'balcone',
  'terrazza', 'meteo']

/** Whether a sensor stands outdoors, by its name, its room or its entity id. */
export function outdoors(...names: (string | undefined)[]): boolean {
  const text = names.filter(Boolean).join(' ').toLowerCase().replace(/_/g, ' ')
  return OUTDOORS.some((word) => text.includes(word))
}
/** Below this a device's battery is said beside it. */
export const LOW_BATTERY = 15

export const CONTACT_FOOTPRINTS: Record<ContactStyle, { width: number; height: number }> = {
  pill: { width: 264, height: 40 },
  chip: { width: 150, height: 28 },
  tile: { width: 120, height: 104 },
  window: { width: 96, height: 128 },
  door: { width: 96, height: 128 },
}
export const READING_FOOTPRINTS: Record<ReadingStyle, { width: number; height: number }> = {
  pill: { width: 250, height: 40 },
  tile: { width: 150, height: 118 },
  thermometer: { width: 88, height: 156 },
  ring: { width: 120, height: 124 },
}

/** A door or window, kept like a lamp. */
export interface HomeContact {
  id: string
  type: 'contact'
  x: number
  y: number
  rid: string
  entity_id: string
  name: string
  style: ContactStyle
  /** A name of the page's own, as a lamp has one. */
  label?: string
  width?: number
}

/** Several doors and windows on one card. */
export interface HomeContacts {
  id: string
  type: 'contacts'
  x: number
  y: number
  style: ContactsStyle
  sensors: ClimateSensor[]
  title: string
  width?: number
}

/** A temperature with the humidity of the same device, either of them left out. */
export interface HomeReading {
  id: string
  type: 'reading'
  x: number
  y: number
  style: ReadingStyle
  name: string
  temperature: ClimateSensor | null
  humidity: ClimateSensor | null
  width?: number
}

export interface ReadingRow {
  name: string
  temperature: ClimateSensor | null
  humidity: ClimateSensor | null
}

/** A list of rooms, each with its temperature and humidity. */
export interface HomeReadings {
  id: string
  type: 'readings'
  x: number
  y: number
  title: string
  rows: ReadingRow[]
  width?: number
}

/** Hints drawn from what else stands on the page. */
export interface HomeHints {
  id: string
  type: 'hints'
  x: number
  y: number
  title: string
  checks: Check[]
  width?: number
}

export type HomeSensorElement = HomeContact | HomeContacts | HomeReading | HomeReadings | HomeHints

/** A door or window as Home Assistant reports it (``hass_sensors.pick_contacts``); ``open`` null while it cannot be read. */
export interface ContactInfo {
  rid: string
  entity_id: string
  name: string
  area: string
  device: string
  device_id: string
  device_class: string
  battery: number | null
  open: boolean | null
  /** When it last changed, in milliseconds. */
  since: number | null
  unavailable: boolean
}

/** A temperature or humidity sensor (``hass_sensors.pick_readings``); ``trend`` is the change of the last hour, where there is one. */
export interface ReadingInfo {
  rid: string
  entity_id: string
  name: string
  area: string
  device: string
  device_id: string
  device_class: string
  battery: number | null
  current: number | null
  unit: string
  unavailable: boolean
  trend?: number
}

/** How a placed sensor stands, by the entity id it was placed with. */
export type SensorState = (Partial<ContactInfo> & Partial<ReadingInfo> & { missing: false }) | { missing: true }

export interface ContactOffer {
  contacts: ContactInfo[]
  problem: HomeProblem | null
}

export interface ReadingOffer {
  readings: ReadingInfo[]
  problem: HomeProblem | null
}

/** The page's answer with news of its sensors put in; what only the registry knows (name, room, battery) stays. */
export function withSensors(answer: HomeAnswer, news: Record<string, SensorState>): HomeAnswer {
  const sensors = { ...(answer.sensors ?? {}) }
  for (const [id, state] of Object.entries(news)) {
    const before = sensors[id]
    sensors[id] = state.missing ? state : ({ ...(before && !before.missing ? before : {}), ...state } as SensorState)
  }
  return { ...answer, sensors }
}

/** The rooms of a card of contacts, in the order its contacts come, those without a room last. */
export function roomsOf(element: HomeContacts, sensors: Record<string, SensorState> = {}): { area: string; contacts: ClimateSensor[] }[] {
  const rooms = new Map<string, ClimateSensor[]>()
  for (const contact of element.sensors) {
    const said = sensors[contact.entity_id]
    const area = said && !said.missing ? (said.area ?? '') : ''
    rooms.set(area, [...(rooms.get(area) ?? []), contact])
  }
  return [...rooms.entries()].sort(([a], [b]) => Number(a === '') - Number(b === '')).map(([area, contacts]) => ({ area, contacts }))
}

/** A temperature and a humidity of one device, as the picker offers them. */
export interface ReadingPair {
  key: string
  name: string
  area: string
  temperature: ReadingInfo | null
  humidity: ReadingInfo | null
}

/**
 * The readings of a house, two of one device as one: 20 devices in a house
 * of 55 temperature and 21 humidity sensors had both. A sensor without a
 * device stands alone.
 */
export function pairReadings(readings: ReadingInfo[]): ReadingPair[] {
  const pairs = new Map<string, ReadingPair>()
  for (const reading of readings) {
    const key = reading.device_id || reading.entity_id
    const pair = pairs.get(key) ?? { key, name: reading.device || reading.name, area: reading.area, temperature: null, humidity: null }
    if (reading.device_class === 'temperature' && !pair.temperature) pair.temperature = reading
    else if (reading.device_class === 'humidity' && !pair.humidity) pair.humidity = reading
    else {
      // A second temperature of one device stands as its own.
      pairs.set(reading.entity_id, { key: reading.entity_id, name: reading.name, area: reading.area, temperature: reading.device_class === 'temperature' ? reading : null,
        humidity: reading.device_class === 'humidity' ? reading : null })
      continue
    }
    pairs.set(key, pair)
  }
  return [...pairs.values()].sort((a, b) => (a.area || a.name).localeCompare(b.area || b.name) || a.name.localeCompare(b.name))
}

/** How long ago, as a page writes "open for": "12 min", "2 h 05", "3 d". */
export function since(from: number | null | undefined, now: number): string {
  if (from === null || from === undefined) return ''
  const seconds = Math.max(0, (now - from) / 1000)
  if (seconds >= 2 * 86_400) return `${Math.floor(seconds / 86_400)} d`
  return duration(seconds < 60 ? 60 : seconds)
}

export interface Hint {
  kind: Check
  /** What it is about: the window, or the room that wants airing. */
  name: string
  /** For a window: since when it is open, and the target of the heating; for a room: its humidity. */
  since?: number | null
  target?: number | null
  value?: number
  key: string
}

/**
 * What a hints card says, from what stands on the same page: a door or
 * window open in a room whose thermostat heats (room from Home Assistant's
 * areas), and a humidity of ``HUMID_PCT`` or more. Nothing is asked of Home
 * Assistant for it; a page without thermostats has no heating hints.
 */
export function pageHints(elements: HomeElement[], answer: HomeAnswer | undefined, checks: readonly Check[]): Hint[] {
  const sensors = answer?.sensors ?? {}
  const found: Hint[] = []
  const seen = new Set<string>()
  const placed = elements.flatMap((element) => sensorsOf(element))
  if (checks.includes('heating')) {
    const heating = new Map<string, number | null>()
    for (const element of elements) {
      if (element.type !== 'climate') continue
      const info = answer?.climates?.[element.id]
      if (info && !info.missing && info.area && (info.action === 'heating' || info.action === 'preheating')) heating.set(info.area, info.target ?? null)
    }
    for (const sensor of placed) {
      const said = sensors[sensor.entity_id]
      if (!sensor.entity_id.startsWith('binary_sensor.') || !said || said.missing || said.open !== true || !said.area || !heating.has(said.area)) continue
      if (seen.has(`heating:${sensor.entity_id}`)) continue
      seen.add(`heating:${sensor.entity_id}`)
      found.push({ kind: 'heating', key: `heating:${sensor.entity_id}`, name: (sensor as { label?: string }).label || said.name || sensor.name, since: said.since ?? null, target: heating.get(said.area) ?? null })
    }
  }
  if (checks.includes('humid')) {
    for (const sensor of placed) {
      const said = sensors[sensor.entity_id]
      if (!said || said.missing || said.device_class !== 'humidity' || said.current === null || said.current === undefined || said.current < HUMID_PCT) continue
      if (outdoors(said.name, said.area, said.device, said.entity_id)) continue
      if (seen.has(`humid:${sensor.entity_id}`)) continue
      seen.add(`humid:${sensor.entity_id}`)
      found.push({ kind: 'humid', key: `humid:${sensor.entity_id}`, name: said.area || said.name || sensor.name, value: said.current })
    }
  }
  return found
}

/** Every sensor an element names (``home_control.sensors_of`` on the server). */
export function sensorsOf(element: HomeElement): ClimateSensor[] {
  if (element.type === 'contact') return [element]
  if (element.type === 'contacts') return element.sensors
  if (element.type === 'reading') return [element.temperature, element.humidity].filter((one): one is ClimateSensor => Boolean(one))
  if (element.type === 'readings') return element.rows.flatMap((row) => [row.temperature, row.humidity].filter((one): one is ClimateSensor => Boolean(one)))
  return []
}

/** Where new sensor elements go: below everything, side by side. */
export function sensorSpots(elements: HomeElement[], count: number, size: { width: number; height: number }): { x: number; y: number }[] {
  return spotsFor(elements, count, size)
}
