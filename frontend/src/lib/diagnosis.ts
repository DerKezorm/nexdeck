/**
 * Why is this broken (roadmap M6): one page per service, for administrators.
 * The server puts the page together; here are its shape, the way to it from
 * a card, a row or a line, and how long a trouble lasted in words.
 */
import type { ChronicleLine } from './chronicle'
import type { WidgetView } from './types'

export interface DiagnosisNode {
  ref: string
  kind: string
  name: string
  down: boolean
  detail: string
  state?: string
}

export interface DiagnosisCard {
  id: number
  title: string
  kind: string
  status: string
  reason: string
  board: string
  target?: { board: string; page: string; widget: number }
}

export interface DiagnosisCheck {
  id: number
  card: string
  kind: string
  target: string
  enabled: boolean
  ok: boolean | null
  error: string
  latency_ms: number | null
  down_since: number | null
  checked: number | null
}

export interface DiagnosisButton {
  widget_id: number
  card: string
  item: string
  id: string
  label: string
  icon: string
  params: Record<string, unknown>
  confirm: boolean
  danger: boolean
}

export interface Runbook {
  text: string
  link: string
  updated: number | null
  by: string
}

export interface Diagnosis {
  subject: { ref: string; kind: string; service: string; name: string; detail: string; icon?: string; engine?: string; demo: boolean }
  state: 'now' | 'past' | 'ok'
  level: 'bad' | 'warn' | 'ok'
  since: number | null
  until: number | null
  reason: string
  window: { from: number; to: number }
  cause: { ref: string; name: string; down: boolean; since?: number } | null
  lines: (ChronicleLine & { whose: string; via: string })[]
  above: DiagnosisNode[]
  below: DiagnosisNode[]
  cards: DiagnosisCard[]
  checks: DiagnosisCheck[]
  log: { available: boolean; why?: string; container?: string; engine?: string; ref?: string }
  buttons: DiagnosisButton[]
  runbook: Runbook
}

/** Whom "Why?" on a card asks about: its connection, or an app tile itself. */
export function subjectOf(widget: Pick<WidgetView, 'id' | 'integration_id' | 'renderer'>): string | null {
  if (widget.integration_id) return `integration:${widget.integration_id}`
  if (widget.renderer === 'app') return `tile:${widget.id}`
  return null
}

/** The address of the page; ``at`` (epoch seconds) for a trouble that has ended. */
export function diagnosisPath(ref: string, at?: number): string {
  const query = new URLSearchParams({ ref })
  if (at) query.set('at', String(Math.round(at)))
  return `/diagnosis?${query.toString()}`
}

type Translate = (key: string, options?: Record<string, unknown>) => string

/** "41 min", "6 h 46 min", "2 d 3 h". */
export function lengthOf(seconds: number, t: Translate): string {
  const minutes = Math.max(1, Math.round(seconds / 60))
  if (minutes < 60) return t('diagnosis.length.minutes', { minutes })
  const hours = Math.floor(minutes / 60)
  if (hours < 48) return t('diagnosis.length.hours', { hours, minutes: minutes % 60 })
  return t('diagnosis.length.days', { days: Math.floor(hours / 24), hours: hours % 24 })
}
