/** Mirrors ``WidgetData`` on the server. */
export type Status = 'ok' | 'warn' | 'bad' | 'unknown'

/** A file a row offers to save; the server fetches it and hands it over. */
export interface Saveable {
  path: string
  name: string
  size?: number
}

/** The one parameter of an action that whoever presses it types in. */
export interface Ask {
  name: string
  label: string
  kind?: 'text' | 'url'
  placeholder?: string
  max_length?: number
}

export interface Action {
  id: string
  label: string
  icon?: string
  confirm?: boolean
  danger?: boolean
  params?: Record<string, unknown>
  ask?: Ask | null
}

export interface Primary {
  label?: string
  value?: number | string | null
  unit?: string
  format?: string
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
  /** Which of the card's declared pieces this row is; see {@link Primary.part}. */
  part?: string
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

export interface WidgetView {
  id: number
  kind: string
  title: string
  icon: string
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
