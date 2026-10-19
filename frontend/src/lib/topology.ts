/**
 * The topology page: what the server sends (``services/topology.py``), and the
 * arithmetic of the plan: the tree it starts as, a free spot for a device that
 * joins later, the curves of the links and which value labels may stand.
 */

export type NodeKind = 'internet' | 'gateway' | 'switch' | 'ap' | 'client'
export type ClientKind = 'nas' | 'tv' | 'printer' | 'camera' | 'server' | 'computer' | 'phone' | 'other'

export interface PortRef {
  index: number | null
  name: string
}

export interface TopoNode {
  id: string
  name: string
  model: string
  kind: NodeKind
  status: 'ok' | 'offline'
  /** Seconds between two new values from this device, once known. */
  every: number | null
  facts: Record<string, string | number>
  wired_clients?: number
  wifi_clients?: number
  /** Clients only: what it probably is, for its icon. */
  client_kind?: ClientKind
}

export interface TopoLink {
  id: string
  a: string
  b: string
  port_a: PortRef
  port_b: PortRef
  kind: 'wan' | 'wire' | 'wifi'
  state: 'up' | 'down'
  /** bit/s; null while not known. */
  speed: number | null
  down: number | null
  up: number | null
  /** The device whose counters this link is measured at. */
  meter: string
  /** Seconds since the value was measured; null while nothing is known. */
  age: number | null
  every: number | null
  history: { down: number[]; up: number[] }
}

export interface TopoClient {
  id: string
  name: string
  kind: ClientKind
  ip: string
  at: string
  port: PortRef
  speed: number | null
}

export interface TopoData {
  nodes: TopoNode[]
  links: TopoLink[]
  clients: TopoClient[]
  client_links: TopoLink[]
}

export interface TopoLayout {
  integration_id: number | null
  start: 'all' | 'empty'
  seeded: boolean
  placed: string[]
  clients: string[]
  hidden: string[]
  positions: Record<string, [number, number]>
}

export interface TopoProblem {
  code: string
  message: string
  hint: string
}

export interface TopoAnswer {
  layout: TopoLayout
  version: number
  data: TopoData | null
  problem: TopoProblem | null
}

export const CARD_H = 58
export const MIN_CARD_W = 150
const GAP_X = 24
const ROW = 150

/** Throughput the way UniFi shows it: bits per second, with the reader's decimal mark. */
export function formatBits(bits: number | null | undefined, language = 'en'): string {
  if (bits === null || bits === undefined || !Number.isFinite(bits)) return '–'
  const fmt = (value: number, digits: number) => value.toLocaleString(language, { minimumFractionDigits: digits, maximumFractionDigits: digits })
  if (bits < 1e3) return `${Math.round(bits)} bit/s`
  if (bits < 1e6) return `${fmt(bits / 1e3, bits < 1e4 ? 1 : 0)} kbit/s`
  if (bits < 1e9) return `${fmt(bits / 1e6, bits < 1e7 ? 1 : 0)} Mbit/s`
  return `${fmt(bits / 1e9, 2)} Gbit/s`
}

export function formatSpeed(bits: number | null | undefined, language = 'en'): string {
  if (!bits) return '–'
  if (bits >= 1e9) return `${(bits / 1e9).toLocaleString(language, { maximumFractionDigits: 1 })} Gbit/s`
  return `${Math.round(bits / 1e6)} Mbit/s`
}

/** The fuller of the two directions against what the link can carry; null when not known. */
export function utilisation(link: Pick<TopoLink, 'down' | 'up' | 'speed'>): number | null {
  if (!link.speed || (link.down === null && link.up === null)) return null
  return Math.max(link.down ?? 0, link.up ?? 0) / link.speed
}

export type Level = 'calm' | 'busy' | 'full'
export function levelOf(share: number | null): Level {
  if (share === null) return 'calm'
  return share >= 0.8 ? 'full' : share >= 0.5 ? 'busy' : 'calm'
}

/**
 * Where everything stands when nothing has been placed by hand: a tree from
 * the internet down, leaves side by side by their own width, each parent over
 * the middle of its children and never over the subtree to its left.
 */
export function treeLayout(ids: string[], links: Pick<TopoLink, 'a' | 'b'>[], widthOf: (id: string) => number): Record<string, [number, number]> {
  const present = new Set(ids)
  const kids = new Map<string, string[]>()
  const hasParent = new Set<string>()
  for (const link of links) {
    if (!present.has(link.a) || !present.has(link.b) || link.a === link.b) continue
    kids.set(link.a, [...(kids.get(link.a) ?? []), link.b])
    hasParent.add(link.b)
  }
  const spot: Record<string, { x: number; depth: number }> = {}
  let cursor = 0
  const place = (id: string, depth: number): number => {
    const width = widthOf(id)
    const start = cursor
    spot[id] = { x: 0, depth }
    const children = (kids.get(id) ?? []).filter((child) => !(child in spot))
    if (children.length === 0) {
      spot[id].x = cursor + width / 2
      cursor += width + GAP_X
      return spot[id].x
    }
    const xs = children.map((child) => place(child, depth + 1))
    spot[id].x = Math.max((xs[0] + xs[xs.length - 1]) / 2, start + width / 2)
    cursor = Math.max(cursor, spot[id].x + width / 2 + GAP_X)
    return spot[id].x
  }
  for (const id of ids) if (!hasParent.has(id) && !(id in spot)) place(id, 0)
  // A cycle has no root; whatever is left starts a tree of its own.
  for (const id of ids) if (!(id in spot)) place(id, 0)
  const out: Record<string, [number, number]> = {}
  for (const id of ids) out[id] = [snap(120 + spot[id].x), 100 + spot[id].depth * ROW]
  return out
}

export function snap(value: number, step = 10): number {
  return Math.round(value / step) * step
}

/** A free spot under ``parent`` for a device that joins the plan later; nothing else moves. */
export function freeSpot(parent: [number, number], taken: { x: number; y: number; w: number }[], width: number): [number, number] {
  const y = parent[1] + ROW
  const step = width + GAP_X
  for (const shift of [0, 1, -1, 2, -2, 3, -3, 4, -4, 5]) {
    const x = parent[0] + shift * step
    const clear = taken.every((other) => Math.abs(other.x - x) >= (other.w + width) / 2 + 16 || Math.abs(other.y - y) >= CARD_H + 30)
    if (clear) return [snap(x), snap(y)]
  }
  return [snap(parent[0] + 6 * step), snap(y)]
}

export interface Curve {
  points: [number, number][]
  normals: [number, number][]
  lengths: number[]
  length: number
}

/** A link as a curve between two centres, sampled evenly enough for the dots that run along it. */
export function curve(a: [number, number], b: [number, number], straight: boolean): Curve {
  const [ax, ay] = a
  const [bx, by] = b
  const dx = bx - ax
  const dy = by - ay
  let c1: [number, number]
  let c2: [number, number]
  if (straight) {
    c1 = [ax + dx / 3, ay + dy / 3]
    c2 = [ax + (2 * dx) / 3, ay + (2 * dy) / 3]
  } else if (Math.abs(dy) >= Math.abs(dx) * 0.5) {
    c1 = [ax, ay + dy * 0.55]
    c2 = [bx, by - dy * 0.55]
  } else {
    c1 = [ax + dx * 0.55, ay]
    c2 = [bx - dx * 0.55, by]
  }
  const steps = 48
  const points: [number, number][] = []
  for (let i = 0; i <= steps; i++) {
    const t = i / steps
    const u = 1 - t
    const w = [u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t]
    points.push([w[0] * ax + w[1] * c1[0] + w[2] * c2[0] + w[3] * bx, w[0] * ay + w[1] * c1[1] + w[2] * c2[1] + w[3] * by])
  }
  const lengths = [0]
  for (let i = 1; i <= steps; i++) lengths.push(lengths[i - 1] + Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]))
  const normals = points.map((_, i): [number, number] => {
    const p = points[Math.max(0, i - 1)]
    const q = points[Math.min(steps, i + 1)]
    const tx = q[0] - p[0]
    const ty = q[1] - p[1]
    const len = Math.hypot(tx, ty) || 1
    return [-ty / len, tx / len]
  })
  return { points, normals, lengths, length: lengths[steps] || 1 }
}

/** The point at a share of the curve's length, and the normal there. */
export function along(c: Curve, share: number): [number, number, number, number] {
  const target = share * c.length
  let lo = 0
  let hi = c.points.length - 1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (c.lengths[mid] <= target) lo = mid
    else hi = mid
  }
  const seg = c.lengths[hi] - c.lengths[lo] || 1
  const f = (target - c.lengths[lo]) / seg
  const p = c.points[lo]
  const q = c.points[hi]
  const n = c.normals[lo]
  const m = c.normals[hi]
  return [p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f, n[0] + (m[0] - n[0]) * f, n[1] + (m[1] - n[1]) * f]
}

export function pathOf(c: Curve): string {
  return 'M' + c.points.map(([x, y]) => `${x.toFixed(1)} ${y.toFixed(1)}`).join('L')
}

export interface Label {
  id: string
  x: number
  y: number
  w: number
  h: number
  /** Which one wins when two would cover each other. */
  weight: number
}

/**
 * Which value labels may stand: the heavier first, and none over another
 * label or over a device card. The ones left out show their values on hover.
 */
export function declutter(labels: Label[], cards: { x: number; y: number; w: number; h: number }[]): Set<string> {
  const kept: Label[] = []
  const overlaps = (a: { x: number; y: number; w: number; h: number }, b: { x: number; y: number; w: number; h: number }) =>
    Math.abs(a.x - b.x) * 2 < a.w + b.w + 6 && Math.abs(a.y - b.y) * 2 < a.h + b.h + 4
  for (const label of [...labels].sort((p, q) => q.weight - p.weight)) {
    if (kept.some((other) => overlaps(label, other))) continue
    if (cards.some((card) => overlaps(label, card))) continue
    kept.push(label)
  }
  return new Set(kept.map((label) => label.id))
}

/** "Port 12", "Port 12 · NAS", or nothing. */
export function portName(port: PortRef | undefined, word: string): string {
  if (!port || port.index === null || port.index === undefined) return port?.name ?? ''
  return port.name ? `${word} ${port.index} · ${port.name}` : `${word} ${port.index}`
}

/** The way to the internet: the device, its parent, and so on up. */
export function pathUp(id: string, links: Pick<TopoLink, 'a' | 'b' | 'id'>[]): { nodes: string[]; links: string[] } {
  const nodes = [id]
  const via: string[] = []
  let current = id
  for (let guard = 0; guard < 64; guard++) {
    const link = links.find((one) => one.b === current)
    if (!link || nodes.includes(link.a)) break
    via.push(link.id)
    nodes.push(link.a)
    current = link.a
  }
  return { nodes, links: via }
}
