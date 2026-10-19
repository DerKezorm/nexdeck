import { Box, Camera, Globe, HardDrive, Maximize2, Minus, Monitor, Network, Phone, Plus, Printer, Router, Server, Tv, Wifi, type LucideIcon } from 'lucide-react'
import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { along, CARD_H, curve, declutter, pathOf, snap, utilisation, type ClientKind, type NodeKind, type TopoLink } from '../../lib/topology'
import { Flow, POOL, TipChannel, type FlowMode } from './flow'

export type { FlowMode } from './flow'

export interface PlanNode {
  id: string
  name: string
  sub: string
  kind: NodeKind
  clientKind?: ClientKind
  status: 'ok' | 'offline'
  x: number
  y: number
  w: number
}

export type Selection = { type: 'node' | 'link'; id: string } | null
export type LabelMode = 'all' | 'load' | 'off'

interface Props {
  nodes: PlanNode[]
  links: TopoLink[]
  editing: boolean
  selected: Selection
  /** What stays bright while something is picked: its way to the internet and its own links. */
  lit: { nodes: Set<string>; links: Set<string> } | null
  straight: boolean
  flow: FlowMode
  labels: LabelMode
  /** The label of a link, already in the reader's language, and how wide it is. */
  labelText: (link: TopoLink) => ReactNode | null
  labelWidth: (link: TopoLink) => number
  tooltip: (link: TopoLink) => ReactNode
  onSelect: (selection: Selection) => void
  onMove: (id: string, x: number, y: number) => void
  onMoveEnd: (id: string) => void
  /** Changes when the plan should be fitted to the screen again. */
  fitKey: string | number
  /** A readable start: never smaller than this, centred on the internet. */
  minScale?: number
  /** Buttons that stand next to the zoom buttons. */
  controls?: ReactNode
  ariaLabel: string
}

export const ICONS: Record<string, LucideIcon> = {
  internet: Globe, gateway: Router, switch: Network, ap: Wifi,
  nas: HardDrive, tv: Tv, printer: Printer, camera: Camera, server: Server, computer: Monitor, phone: Phone, other: Box,
}

let measurer: CanvasRenderingContext2D | null = null
let asked = false
/** Text width without touching the page: the card grows with its longest line. */
export function textWidth(text: string, font: string): number {
  if (!asked && typeof document !== 'undefined') {
    // Asked once: a browser without a canvas (a test, a locked-down kiosk) gets an estimate.
    asked = true
    try {
      measurer = document.createElement('canvas').getContext?.('2d') ?? null
    } catch {
      measurer = null
    }
  }
  if (!measurer) return text.length * 7
  measurer.font = font
  return measurer.measureText(text).width
}
export const NAME_FONT = "600 13px 'Inter Variable', system-ui, sans-serif"
export const SUB_FONT = "400 11px 'Inter Variable', system-ui, sans-serif"
export const LABEL_FONT = "500 10.5px 'JetBrains Mono Variable', ui-monospace, monospace"

export function cardWidth(name: string, sub: string): number {
  return Math.max(150, Math.ceil(Math.max(textWidth(name, NAME_FONT), textWidth(sub, SUB_FONT))) + 56 + 30)
}

type Tip = { id: string; x: number; y: number } | null

/**
 * The plan: device cards, the links between them, and the traffic as dots or
 * dashes along each link, one lane per direction. Cards and curves are React;
 * the moving parts belong to ``Flow``. Moving one card redraws its own links only.
 */
export function TopologyCanvas(props: Props) {
  const { nodes, links, editing, selected, lit, straight, flow, labels, onSelect, onMove, onMoveEnd, fitKey, minScale = 0.6, labelWidth } = props
  const { t } = useTranslation()
  const host = useRef<HTMLDivElement>(null)
  const svg = useRef<SVGSVGElement>(null)
  const world = useRef<SVGGElement>(null)
  const view = useRef({ k: 1, x: 0, y: 0 })
  const [panning, setPanning] = useState(false)
  const [engine] = useState(() => new Flow())
  const [tips] = useState(() => new TipChannel())

  useEffect(() => engine.start(), [engine])
  useEffect(() => engine.update(links, flow), [engine, links, flow])

  const byId = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes])

  // -- view: fit, pan, zoom ---------------------------------------------------

  const apply = useCallback(() => {
    const { k, x, y } = view.current
    world.current?.setAttribute('transform', `translate(${x.toFixed(1)} ${y.toFixed(1)}) scale(${k.toFixed(4)})`)
  }, [])

  const fit = useCallback(
    (readable: boolean) => {
      const box = svg.current?.getBoundingClientRect()
      if (!box || box.width === 0 || nodes.length === 0) return
      const x0 = Math.min(...nodes.map((n) => n.x - n.w / 2)) - 30
      const x1 = Math.max(...nodes.map((n) => n.x + n.w / 2)) + 30
      const y0 = Math.min(...nodes.map((n) => n.y)) - CARD_H / 2 - 40
      const y1 = Math.max(...nodes.map((n) => n.y)) + CARD_H / 2 + 30
      const k = Math.min(1.3, Math.max(0.15, Math.min(box.width / (x1 - x0), box.height / (y1 - y0))))
      view.current = { k, x: (box.width - (x1 - x0) * k) / 2 - x0 * k, y: (box.height - (y1 - y0) * k) / 2 - y0 * k }
      const root = nodes.find((n) => n.kind === 'internet')
      if (readable && root && k < minScale) view.current = { k: minScale, x: box.width / 2 - root.x * minScale, y: 20 - y0 * minScale }
      apply()
    },
    [nodes, apply, minScale],
  )
  const fitted = useRef<string | number | null>(null)
  useLayoutEffect(() => {
    if (fitted.current === fitKey || nodes.length === 0) return
    fitted.current = fitKey
    fit(true)
  }, [fitKey, fit, nodes.length])

  const zoomAt = useCallback(
    (factor: number, sx: number, sy: number) => {
      const v = view.current
      const k = Math.min(3, Math.max(0.15, v.k * factor))
      view.current = { k, x: sx - (sx - v.x) * (k / v.k), y: sy - (sy - v.y) * (k / v.k) }
      apply()
    },
    [apply],
  )
  const zoomMiddle = (factor: number) => zoomAt(factor, (svg.current?.clientWidth ?? 0) / 2, (svg.current?.clientHeight ?? 0) / 2)

  useEffect(() => {
    const element = svg.current
    if (!element) return
    const wheel = (event: WheelEvent) => {
      event.preventDefault()
      const box = element.getBoundingClientRect()
      zoomAt(Math.exp(-event.deltaY * 0.0015), event.clientX - box.left, event.clientY - box.top)
    }
    element.addEventListener('wheel', wheel, { passive: false })
    return () => element.removeEventListener('wheel', wheel)
  }, [zoomAt])

  // -- pointer: pick, drag, pan, pinch ----------------------------------------

  const drag = useRef<null | { type: 'node' | 'link' | 'pan'; id?: string; sx: number; sy: number; ox: number; oy: number; vx: number; vy: number; moved: boolean }>(null)
  const pointers = useRef(new Map<number, { x: number; y: number }>())
  const pinch = useRef<null | { distance: number; k: number }>(null)

  const down = (event: React.PointerEvent<SVGSVGElement>) => {
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY })
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()]
      pinch.current = { distance: Math.hypot(a.x - b.x, a.y - b.y), k: view.current.k }
      drag.current = null
      return
    }
    if ((event.button ?? 0) !== 0) return
    const target = event.target as Element
    const card = target.closest('[data-node]')
    const hit = target.closest('[data-link]')
    try {
      svg.current?.setPointerCapture(event.pointerId)
    } catch {
      /* the pointer is already gone */
    }
    tips.show(null)
    const base = { sx: event.clientX, sy: event.clientY, vx: view.current.x, vy: view.current.y, moved: false, ox: 0, oy: 0 }
    if (card) {
      const node = byId.get(card.getAttribute('data-node') ?? '')
      drag.current = { ...base, type: 'node', id: node?.id, ox: node?.x ?? 0, oy: node?.y ?? 0 }
    } else if (hit) drag.current = { ...base, type: 'link', id: hit.getAttribute('data-link') ?? '' }
    else drag.current = { ...base, type: 'pan' }
  }

  const move = (event: React.PointerEvent<SVGSVGElement>) => {
    if (pointers.current.has(event.pointerId)) pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY })
    if (pinch.current && pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()]
      const box = svg.current?.getBoundingClientRect()
      if (!box) return
      const factor = (pinch.current.k * Math.hypot(a.x - b.x, a.y - b.y)) / pinch.current.distance / view.current.k
      zoomAt(factor, (a.x + b.x) / 2 - box.left, (a.y + b.y) / 2 - box.top)
      return
    }
    const current = drag.current
    if (!current) {
      const hit = (event.target as Element).closest?.('[data-link]')
      const box = host.current?.getBoundingClientRect()
      tips.show(hit && box ? { id: hit.getAttribute('data-link') ?? '', x: event.clientX - box.left, y: event.clientY - box.top } : null)
      return
    }
    const dx = event.clientX - current.sx
    const dy = event.clientY - current.sy
    if (!current.moved && Math.hypot(dx, dy) > 4) current.moved = true
    if (!current.moved) return
    if (current.type === 'node' && editing && current.id) {
      onMove(current.id, snap(current.ox + dx / view.current.k), snap(current.oy + dy / view.current.k))
    } else {
      if (!panning) setPanning(true)
      view.current = { ...view.current, x: current.vx + dx, y: current.vy + dy }
      apply()
    }
  }

  const lift = (event: React.PointerEvent<SVGSVGElement>) => {
    pointers.current.delete(event.pointerId)
    if (pointers.current.size < 2) pinch.current = null
    const current = drag.current
    drag.current = null
    setPanning(false)
    if (!current) return
    if (current.moved) {
      if (current.type === 'node' && editing && current.id) onMoveEnd(current.id)
      return
    }
    if (current.type === 'node' && current.id) onSelect(selected?.type === 'node' && selected.id === current.id ? null : { type: 'node', id: current.id })
    else if (current.type === 'link' && current.id) onSelect({ type: 'link', id: current.id })
    else onSelect(null)
  }

  // -- labels ------------------------------------------------------------------

  const placedLabels = useMemo(() => {
    if (labels === 'off') return []
    const candidates = links
      .filter((link) => {
        if (link.state === 'down') return true
        if (link.down === null && link.up === null) return false
        if (labels === 'all') return true
        const share = utilisation(link)
        return Math.max(link.down ?? 0, link.up ?? 0) >= 100e6 || (share !== null && share >= 0.3)
      })
      .flatMap((link) => {
        const a = byId.get(link.a)
        const b = byId.get(link.b)
        if (!a || !b) return []
        const [x, y] = along(curve([a.x, a.y], [b.x, b.y], straight), 0.5)
        return [{ id: link.id, x, y, w: labelWidth(link), h: 20, weight: link.state === 'down' ? 1e12 : Math.max(link.down ?? 0, link.up ?? 0) }]
      })
    const free = declutter(candidates, nodes.map((node) => ({ x: node.x, y: node.y, w: node.w, h: CARD_H })))
    return candidates.filter((label) => free.has(label.id))
  }, [links, byId, nodes, labels, labelWidth, straight])

  return (
    <div ref={host} className="relative w-full h-full overflow-hidden" data-topology-canvas>
      <svg
        ref={svg}
        className={`w-full h-full block select-none touch-none ${panning ? 'cursor-grabbing' : ''}`}
        role="img"
        aria-label={props.ariaLabel}
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={lift}
        onPointerCancel={(event) => {
          pointers.current.delete(event.pointerId)
          pinch.current = null
          drag.current = null
          setPanning(false)
        }}
        onPointerLeave={() => tips.show(null)}
      >
        <defs>
          <pattern id="topo-dots" width="20" height="20" patternUnits="userSpaceOnUse">
            <circle cx="1" cy="1" r="1" style={{ fill: 'var(--nd-border-strong)' }} opacity={editing ? 1 : 0.5} />
          </pattern>
          <filter id="topo-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="2.2" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <g ref={world}>
          <rect x={-20000} y={-20000} width={40000} height={40000} fill="url(#topo-dots)" />
          <g>
            {links.map((link) => {
              const a = byId.get(link.a)
              const b = byId.get(link.b)
              if (!a || !b) return null
              return (
                <LinkItem
                  key={link.id}
                  id={link.id}
                  ax={a.x}
                  ay={a.y}
                  bx={b.x}
                  by={b.y}
                  straight={straight}
                  down={link.state === 'down'}
                  dim={lit !== null && !lit.links.has(link.id)}
                  picked={selected?.type === 'link' && selected.id === link.id}
                  engine={engine}
                />
              )
            })}
          </g>
          <g>
            {nodes.map((node) => (
              <NodeCard key={node.id} node={node} editing={editing} picked={selected?.type === 'node' && selected.id === node.id} dim={lit !== null && !lit.nodes.has(node.id)} />
            ))}
          </g>
          <g pointerEvents="none">
            {placedLabels.map((label) => {
              const link = links.find((one) => one.id === label.id)
              if (!link) return null
              return (
                <g
                  key={label.id}
                  transform={`translate(${(label.x - label.w / 2).toFixed(1)} ${(label.y - 10).toFixed(1)})`}
                  style={{ opacity: lit !== null && !lit.links.has(link.id) ? 0.22 : 1 }}
                  data-topology-label={label.id}
                >
                  <rect width={label.w} height={20} rx={10} style={{ fill: 'var(--nd-surface-strong)', stroke: 'var(--nd-border-strong)' }} />
                  <text x={9} y={14} style={{ font: LABEL_FONT, fill: 'var(--nd-text)' }}>
                    {props.labelText(link)}
                  </text>
                </g>
              )
            })}
          </g>
        </g>
      </svg>
      <TipBox channel={tips} links={links} render={props.tooltip} host={host} />
      <div className="absolute right-3 bottom-3 flex gap-1.5 items-end" data-no-picture>
        {props.controls}
        <button type="button" className="btn btn-icon glass-strong" onClick={() => zoomMiddle(0.8)} aria-label={t('topology.zoomOut')} title={t('topology.zoomOut')}>
          <Minus size={15} />
        </button>
        <button type="button" className="btn btn-icon glass-strong" onClick={() => zoomMiddle(1.25)} aria-label={t('topology.zoomIn')} title={t('topology.zoomIn')}>
          <Plus size={15} />
        </button>
        <button type="button" className="btn btn-icon glass-strong" onClick={() => fit(false)} aria-label={t('topology.fit')} title={t('topology.fit')} data-topology-fit>
          <Maximize2 size={15} />
        </button>
      </div>
    </div>
  )
}

const LinkItem = memo(function LinkItem(props: { id: string; ax: number; ay: number; bx: number; by: number; straight: boolean; down: boolean; dim: boolean; picked: boolean; engine: Flow }) {
  const { id, ax, ay, bx, by, straight, down, dim, picked, engine } = props
  const shape = useMemo(() => curve([ax, ay], [bx, by], straight), [ax, ay, bx, by, straight])
  useEffect(() => {
    engine.shape(id, shape)
    return () => engine.shape(id, null)
  }, [engine, id, shape])
  const d = pathOf(shape)
  return (
    <g style={{ opacity: dim ? 0.22 : 1, transition: 'opacity .25s' }} data-link-id={id}>
      <path
        ref={(element) => engine.base(id, element)}
        d={d}
        fill="none"
        strokeLinecap="round"
        style={{ strokeOpacity: down ? 0.8 : picked ? 0.45 : 0.16 }}
        strokeDasharray={down ? '6 7' : undefined}
      />
      <polyline ref={(element) => engine.lane(id, 'laneDown', element)} fill="none" strokeLinecap="round" style={{ display: 'none' }} />
      <polyline ref={(element) => engine.lane(id, 'laneUp', element)} fill="none" strokeLinecap="round" style={{ display: 'none' }} />
      <g filter="url(#topo-glow)">
        {Array.from({ length: POOL * 2 }, (_, i) => (
          <circle key={i} ref={(element) => engine.dot(id, i, element)} r={2} style={{ display: 'none' }} />
        ))}
      </g>
      <path d={d} fill="none" stroke="transparent" strokeWidth={18} data-link={id} className="cursor-pointer" />
    </g>
  )
})

const NodeCard = memo(function NodeCard({ node, editing, picked, dim }: { node: PlanNode; editing: boolean; picked: boolean; dim: boolean }) {
  const Icon = ICONS[node.kind === 'client' ? (node.clientKind ?? 'other') : node.kind] ?? Box
  const offline = node.status === 'offline'
  const client = node.kind === 'client'
  return (
    <g data-node={node.id} transform={`translate(${node.x - node.w / 2} ${node.y - CARD_H / 2})`} className={editing ? 'cursor-grab' : 'cursor-pointer'} style={{ opacity: dim ? 0.4 : 1, transition: 'opacity .25s' }}>
      <title>{node.name}</title>
      <rect
        width={node.w}
        height={CARD_H}
        rx={14}
        style={{
          fill: 'var(--nd-surface-strong)',
          stroke: picked ? 'var(--nd-accent)' : offline ? 'color-mix(in srgb, var(--nd-bad) 55%, transparent)' : 'var(--nd-border-strong)',
          strokeWidth: picked ? 2 : 1,
        }}
      />
      <rect x={10} y={11} width={36} height={36} rx={10} style={{ fill: offline ? 'color-mix(in srgb, var(--nd-bad) 16%, transparent)' : client ? 'var(--nd-surface-hover)' : 'var(--nd-accent-soft)' }} />
      <Icon x={17} y={18} width={22} height={22} strokeWidth={1.8} style={{ color: offline ? 'var(--nd-bad)' : client ? 'var(--nd-text-muted)' : 'var(--nd-accent)' }} />
      <text x={56} y={26} style={{ font: NAME_FONT, fill: 'var(--nd-text)' }}>
        {node.name}
      </text>
      <text x={56} y={43} style={{ font: SUB_FONT, fill: 'var(--nd-text-muted)' }}>
        {node.sub}
      </text>
      {node.kind !== 'internet' && <circle cx={node.w - 14} cy={14} r={4} style={{ fill: offline ? 'var(--nd-bad)' : 'var(--nd-ok)' }} />}
    </g>
  )
})

/** The hover box of a link, with a state of its own, so moving the pointer never redraws the plan. */
function TipBox({ channel, links, render, host }: { channel: TipChannel; links: TopoLink[]; render: (link: TopoLink) => ReactNode; host: React.RefObject<HTMLDivElement | null> }) {
  const [tip, setTip] = useState<Tip>(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    channel.listen((next) => {
      setTip((current) => (next === null && current === null ? current : next))
      if (next) setWidth(host.current?.clientWidth ?? 0)
    })
    return () => channel.listen(null)
  }, [channel, host])
  const link = tip ? links.find((one) => one.id === tip.id) : undefined
  if (!tip || !link) return null
  return (
    <div className="absolute z-20 pointer-events-none glass-strong rounded-xl px-3 py-2 text-xs shadow-xl min-w-[220px]" style={{ left: Math.max(8, Math.min(tip.x + 14, width - 250)), top: tip.y + 14 }} role="tooltip">
      {render(link)}
    </div>
  )
}
