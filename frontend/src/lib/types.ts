import type { Forecast } from './forecast'
import type { Side } from './holding'

/** Mirrors ``WidgetData`` on the server. */
export type Status = 'ok' | 'warn' | 'bad' | 'unknown'

/** A file a row offers to save; the server fetches it and hands it over. */
export interface Saveable {
  path: string
  name: string
  size?: number
}

/** One entry of a pick list a card offers with an action. */
export interface Choice {
  value: string
  label: string
}

/**
 * A parameter of an action that whoever presses it fills in.
 *
 * `choice` picks from `options`, which the card delivered with its answer; the
 * server checks the pressed value against exactly that list. `number` takes a
 * number inside `min` and `max`; the server checks that again.
 */
export interface Ask {
  name: string
  label: string
  kind?: 'text' | 'url' | 'choice' | 'number'
  options?: Choice[]
  placeholder?: string
  max_length?: number
  /** A `number` blank: the lowest and highest value allowed, and the step (a whole step means whole numbers). */
  min?: number
  max?: number
  step?: number
}

/**
 * What pressing an action hands back: nothing, when the sheet opened instead,
 * or the pending request, so that the button can stay shut until the answer is
 * in (a double click goes out once).
 */
export type Pressed = void | Promise<unknown>

export interface Action {
  id: string
  label: string
  icon?: string
  confirm?: boolean
  danger?: boolean
  params?: Record<string, unknown>
  asks?: Ask[]
  /**
   * The texts of this action are the author's own words (a button of a custom card): shown as they are, not put
   * through nexdeck's table of translations. Set on the way to the screen, never by the server.
   */
  verbatim?: boolean
}

export interface Primary {
  label?: string
  value?: number | string | null
  unit?: string
  format?: string
  /** A custom card: what the server wrote out of the value, and the finished text in the viewer's language. */
  text?: string
  display?: string
  /**
   * Which recorded metric this number is, when the card knows.
   *
   * ⚠️ The server has sent this for as long as `Secondary` has had it (n8n's
   * summary, Docker's load, Beszel's host), and this type simply never said
   * so. The chart's legend needs it to call a line "WAN in" rather than
   * "wan_down".
   */
  metric?: string
  /**
   * Which of the card's declared pieces this row is.
   *
   * ⚠️ Also sent since the dial learned to follow a chosen row, and also
   * never written down here. Both holes surfaced the same way: the demo board
   * is the only place that type-checks against literal card data, so a field
   * the server sends and no card in the preview happens to carry stays
   * invisible until somebody writes one out by hand.
   */
  part?: string
}

export interface Secondary {
  label: string
  value?: number | string | null
  unit?: string
  metric?: string
  /** Custom card rows, as {@link Primary.text} and {@link Primary.display}. */
  format?: string
  text?: string
  display?: string
  /** Which of the card's declared pieces this row is; see {@link Primary.part}. */
  part?: string
  /** What the row would say if there were room, shown on hover. */
  hint?: string
  /** False for a percentage that is no share of a whole, such as Docker's CPU per core. */
  share?: boolean
}

export interface WidgetData {
  status: Status
  primary?: Primary | null
  secondary?: Secondary[]
  items?: Record<string, unknown>[]
  actions?: Action[]
  metrics?: Record<string, number>
  link?: string | null
  meta?: Record<string, unknown>
  error?: string | null
  updated_at?: number
  /** Since when the card is yellow or red (epoch seconds), when that is known. */
  since?: number | null
  /** When a volume is full, a number reaches its red, a backup gets slower (roadmap M4). */
  forecast?: Forecast | null
  /** What this card's service hangs on that is down right now (roadmap M5). */
  cause?: string | null
}

export interface LayoutItem {
  i: string
  x: number
  y: number
  w: number
  h: number
  minW?: number
  minH?: number
}

export type Breakpoint = 'lg' | 'md' | 'sm'

/** The app a tile follows (issue #37), as the board shows it. */
export interface TileApp {
  id: number
  name: string
  icon: string
  description: string
  /** The label the tile opens, "auto", or "" for the first address. */
  address: string
  addresses: string[]
  automatic: boolean
}

export interface WidgetView {
  id: number
  kind: string
  /** What the card shows: for a tile that follows an app, the app's name unless it has one of its own. */
  title: string
  icon: string
  /** The tile's own name and icon, which may be empty; only for a tile that follows an app. */
  own_title?: string
  own_icon?: string
  app?: TileApp | null
  link: string
  /** The address of the widget's integration, for cards without a link of their own. */
  service_link?: string
  renderer: string
  options: Record<string, unknown>
  integration_id: number | null
  integration_name?: string
  refresh_seconds: number | null
  beta?: boolean
  client_only?: boolean
  default_size?: [number, number]
  min_size?: [number, number]
  health?: HealthView | null
  /** The running maintenance of the card's connection, or of the app tile itself; `until` is ISO. */
  maintenance?: { id: number; until: string } | null
}

export interface HealthView {
  id: number
  kind: string
  target: string
  /** ⚠️ These four were left out of the type, so the settings sheet could not
   * read them back and wrote factory values over them on every save. */
  interval_seconds: number
  timeout_seconds: number
  expect_status: number
  insecure: boolean
  enabled: boolean
  last_ok: boolean | null
  last_latency_ms: number | null
  down_since: string | null
  last_error: string
  bars?: (number | null)[]
  /** What the tile hangs on that is down right now (roadmap M5). */
  cause?: string
}

export interface PageView {
  id: number
  name: string
  slug: string
  icon: string
  position: number
  layouts: Record<Breakpoint, LayoutItem[]>
  /** What the server counted up to. Sent back when an arrangement is saved. */
  layout_version?: number
  widgets: WidgetView[]
  /** "topology": a network plan instead of cards (components/topology); "home": a surface of Home Assistant controls (components/home). */
  kind?: 'cards' | 'topology' | 'home'
  topology?: { integration_id: number | null } | null
  home?: { integration_id: number | null } | null
  /** Card pages: the column beside the grid (lib/holding). */
  side?: Side
}

export interface BoardView {
  id: number
  slug: string
  name: string
  icon: string
  owner_id: number | null
  background: { kind: string; value?: string; blur?: number; dim?: number }
  settings: Record<string, unknown>
  provisioned: boolean
  permission: 'view' | 'edit' | 'act' | 'owner'
  pages: PageView[]
}
