import { along, levelOf, type Curve, type Level, type TopoLink } from '../../lib/topology'

export type FlowMode = 'dots' | 'dashes' | 'still'

const LEVEL_COLOUR: Record<Level, string> = { calm: 'var(--nd-accent)', busy: 'var(--nd-warn)', full: 'var(--nd-bad)' }
/** Dots per lane at most. */
export const POOL = 24

const lg = (bits: number) => Math.log10(Math.max(bits, 1e3) / 1e3)
/** A lane's width grows with the logarithm of its traffic: 1 at a trickle, about 6 at a gigabit. */
export const thickness = (bits: number) => 1 + 0.75 * lg(bits)
/** Pixels per second the dots travel. */
export const speedOf = (bits: number) => 22 + 30 * lg(bits)
export const levelColour = (bits: number, speed: number | null) => LEVEL_COLOUR[levelOf(speed ? bits / speed : null)]

interface Elements {
  base: SVGPathElement | null
  laneDown: SVGPolylineElement | null
  laneUp: SVGPolylineElement | null
  dots: (SVGCircleElement | null)[]
  shape: Curve | null
}

interface Motion {
  shownDown: number
  shownUp: number
  phaseDown: number
  phaseUp: number
  dash: number
}

/**
 * The moving parts of the plan, outside React: one animation frame loop sets
 * the width and colour of every link and moves its dots or dashes, straight on
 * the elements. A render would cost sixty times a second what this costs once.
 */
export class Flow {
  private parts = new Map<string, Elements>()
  private motion = new Map<string, Motion>()
  private links: TopoLink[] = []
  private mode: FlowMode = 'dots'
  private frame = 0

  private entry(id: string): Elements {
    let found = this.parts.get(id)
    if (!found) {
      found = { base: null, laneDown: null, laneUp: null, dots: [], shape: null }
      this.parts.set(id, found)
    }
    return found
  }

  base(id: string, element: SVGPathElement | null): void {
    this.entry(id).base = element
  }

  lane(id: string, which: 'laneDown' | 'laneUp', element: SVGPolylineElement | null): void {
    this.entry(id)[which] = element
  }

  dot(id: string, index: number, element: SVGCircleElement | null): void {
    this.entry(id).dots[index] = element
  }

  shape(id: string, shape: Curve | null): void {
    this.entry(id).shape = shape
  }

  update(links: TopoLink[], mode: FlowMode): void {
    this.links = links
    this.mode = mode
  }

  /** Starts the loop; the function it returns stops it. */
  start(): () => void {
    if (typeof requestAnimationFrame !== 'function') return () => undefined
    const still = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches ?? false
    let last = performance.now()
    const step = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000)
      last = now
      for (const link of this.links) this.draw(link, dt, still)
      this.frame = requestAnimationFrame(step)
    }
    this.frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(this.frame)
  }

  private draw(link: TopoLink, dt: number, still: boolean): void {
    const el = this.parts.get(link.id)
    const shape = el?.shape
    if (!el || !shape) return
    let m = this.motion.get(link.id)
    if (!m) {
      m = { shownDown: link.down ?? 0, shownUp: link.up ?? 0, phaseDown: Math.random(), phaseUp: Math.random(), dash: 0 }
      this.motion.set(link.id, m)
    }
    const off = link.state === 'down'
    // A new value glides in over about a second instead of jumping.
    const glide = Math.min(1, dt * 2.5)
    m.shownDown += ((off ? 0 : (link.down ?? 0)) - m.shownDown) * glide
    m.shownUp += ((off ? 0 : (link.up ?? 0)) - m.shownUp) * glide
    const known = !off && (link.down !== null || link.up !== null)
    const tDown = known ? thickness(m.shownDown) : 1
    const tUp = known ? thickness(m.shownUp) : 1
    if (el.base) {
      // For 1984, which draws the load in the width of the line and not in colour alone.
      el.base.dataset.level = off ? 'down' : known ? levelOf(link.speed ? Math.max(m.shownDown, m.shownUp) / link.speed : null) : 'unknown'
      el.base.style.strokeWidth = off || !known ? '2' : (tDown + tUp + 5).toFixed(1)
      el.base.style.stroke = off ? 'var(--nd-unknown)' : known ? levelColour(Math.max(m.shownDown, m.shownUp), link.speed) : 'var(--nd-text-faint)'
    }
    const moving = known && this.mode !== 'still'
    const lanes: [number, number, 'phaseDown' | 'phaseUp', 1 | -1, number, SVGPolylineElement | null][] = [
      [m.shownDown, tDown, 'phaseDown', 1, tDown / 2 + 1, el.laneDown],
      [m.shownUp, tUp, 'phaseUp', -1, -(tUp / 2 + 1), el.laneUp],
    ]
    m.dash += dt
    let used = 0
    for (const [rate, width, phase, direction, offset, lane] of lanes) {
      const idle = rate < 2e3
      if (lane) {
        const show = moving && this.mode === 'dashes' && !idle
        lane.style.display = show ? '' : 'none'
        if (show) {
          lane.setAttribute('points', shape.points.map(([x, y], i) => `${(x + shape.normals[i][0] * offset).toFixed(1)},${(y + shape.normals[i][1] * offset).toFixed(1)}`).join(' '))
          lane.style.stroke = levelColour(rate, link.speed)
          lane.style.strokeWidth = width.toFixed(1)
          lane.style.strokeDasharray = `${(width * 2.4).toFixed(1)} ${(width * 2.4 + 9).toFixed(1)}`
          if (!still) lane.style.strokeDashoffset = String(-direction * ((m.dash * speedOf(rate)) % 1000))
        }
      }
      if (!(moving && this.mode === 'dots') || idle) continue
      const spacing = Math.min(150, Math.max(46, 150 - 14 * lg(rate)))
      const count = Math.min(POOL, Math.max(1, Math.round(shape.length / spacing)))
      if (!still) m[phase] = (m[phase] + (speedOf(rate) * dt) / shape.length) % 1
      const radius = (width * 0.55 + 0.7).toFixed(2)
      for (let i = 0; i < count; i++) {
        let share = (m[phase] + i / count) % 1
        if (direction < 0) share = 1 - share
        const [x, y, nx, ny] = along(shape, share)
        const dot = el.dots[used++]
        if (!dot) continue
        dot.setAttribute('cx', (x + nx * offset).toFixed(1))
        dot.setAttribute('cy', (y + ny * offset).toFixed(1))
        dot.setAttribute('r', radius)
        dot.style.fill = levelColour(rate, link.speed)
        dot.style.display = ''
      }
    }
    for (let i = used; i < el.dots.length; i++) {
      const dot = el.dots[i]
      if (dot && dot.style.display !== 'none') dot.style.display = 'none'
    }
  }
}

/** The hover box, told from the pointer handlers where to stand; see ``Tip``. */
export class TipChannel {
  private listener: ((tip: { id: string; x: number; y: number } | null) => void) | null = null
  listen(fn: ((tip: { id: string; x: number; y: number } | null) => void) | null): void {
    this.listener = fn
  }
  show(tip: { id: string; x: number; y: number } | null): void {
    this.listener?.(tip)
  }
}
