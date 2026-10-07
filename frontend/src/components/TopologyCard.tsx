import { useRef } from 'react'
import { useTranslation } from 'react-i18next'

import { useDisguise } from '../lib/showcase'
import type { WidgetData } from '../lib/types'
import { useBoxSize } from '../lib/useBoxSize'

/**
 * A map of places and what hangs on what: a cluster with its nodes and the
 * machines on each, or one day a network with its switches. The data brings
 * a flat list, each place naming its parent; the card lays it out in rows,
 * one row per level, the children of a place in a small grid under it.
 */
export interface Place {
  id: string
  name: string
  kind?: string
  parent: string | null
  status?: string
  detail?: string
}

export interface Box {
  place: Place
  x: number
  y: number
  w: number
  h: number
  level: number
}

const BOX_W = 150
const BOX_H = 34
const ROW_GAP = 30
const LEAF_W = 112
const LEAF_H = 30
const GAP = 10
/** Leaves of one place go into a grid of up to this many columns once there are more of them than that. */
const GRID = 3

interface Shape {
  width: number
}

/**
 * Where every place stands, for a tree of any depth: each place above its
 * children, each subtree as wide as its children side by side, and a place
 * whose children are all leaves, more than three of them, with those leaves
 * in a grid of three under it, which keeps a node with twenty machines from
 * spreading across the whole card. A place whose parent is missing is a root.
 * ``grid`` is how many columns such leaves get; see bestGrid.
 */
export function layout(places: Place[], grid = GRID): { boxes: Box[]; height: number; width: number } {
  const known = new Set(places.map((place) => place.id))
  const children = new Map<string, Place[]>()
  for (const place of places) {
    if (place.parent && known.has(place.parent) && place.parent !== place.id) children.set(place.parent, [...(children.get(place.parent) ?? []), place])
  }
  const roots = places.filter((place) => !place.parent || !known.has(place.parent) || place.parent === place.id)
  const kids = (id: string) => children.get(id) ?? []
  const leafy = (id: string) => kids(id).length > grid && kids(id).every((child) => !kids(child.id).length)
  const shapes = new Map<string, Shape>()
  const seen = new Set<string>()
  const measure = (place: Place): number => {
    if (seen.has(place.id)) return BOX_W
    seen.add(place.id)
    const own = kids(place.id).length ? BOX_W : LEAF_W
    let width = own
    if (leafy(place.id)) width = Math.max(own, grid * LEAF_W + (grid - 1) * GAP)
    else if (kids(place.id).length) width = Math.max(own, kids(place.id).reduce((sum, child) => sum + measure(child), 0) + (kids(place.id).length - 1) * GAP)
    shapes.set(place.id, { width })
    return width
  }
  const boxes: Box[] = []
  let height = 0
  const placed = new Set<string>()
  const put = (place: Place, left: number, y: number, level: number) => {
    if (placed.has(place.id)) return
    placed.add(place.id)
    const span = shapes.get(place.id)?.width ?? BOX_W
    const leaf = !kids(place.id).length
    const w = leaf ? LEAF_W : BOX_W
    const h = leaf ? LEAF_H : BOX_H
    boxes.push({ place, x: left + span / 2 - w / 2, y, w, h, level })
    height = Math.max(height, y + h)
    const below = y + h + ROW_GAP
    if (leafy(place.id)) {
      const columns = Math.min(grid, kids(place.id).length)
      const across = columns * LEAF_W + (columns - 1) * GAP
      kids(place.id).forEach((child, index) => {
        const row = Math.floor(index / columns)
        const x = left + span / 2 - across / 2 + (index % columns) * (LEAF_W + GAP)
        const top = below + row * (LEAF_H + GAP)
        placed.add(child.id)
        boxes.push({ place: child, x, y: top, w: LEAF_W, h: LEAF_H, level: level + 1 })
        height = Math.max(height, top + LEAF_H)
      })
      return
    }
    let cursor = left + (span - (kids(place.id).reduce((sum, child) => sum + (shapes.get(child.id)?.width ?? BOX_W), 0) + (kids(place.id).length - 1) * GAP)) / 2
    for (const child of kids(place.id)) {
      put(child, cursor, below, level + 1)
      cursor += (shapes.get(child.id)?.width ?? BOX_W) + GAP
    }
  }
  let left = 0
  for (const root of roots) {
    const width = measure(root)
    put(root, left, 0, 0)
    left += width + GAP * 2
  }
  return { boxes, height, width: Math.max(left - GAP * 2, BOX_W) }
}

/**
 * How many columns the leaves get so that the map is drawn largest in a box
 * of this size: three where nothing has been measured.
 *
 * ⚠️ Always three, the map of a Proxmox cluster with two nodes and nine
 * guests was 3.6 times as wide as tall. On a phone it shrank to a font of
 * five pixels, with the card's height empty above and below it.
 */
export function bestGrid(places: Place[], width: number, height: number): number {
  if (width <= 0 || height <= 0) return GRID
  let best = GRID
  let largest = 0
  for (const grid of [GRID, 2, 1]) {
    const shape = layout(places, grid)
    const scale = Math.min(width / (shape.width + 8), height / (shape.height + 8))
    // A narrower grid has to draw clearly larger to be worth the longer columns.
    if (scale > largest * 1.05) {
      best = grid
      largest = scale
    }
  }
  return best
}

const COLOUR: Record<string, string> = { ok: 'var(--nd-ok)', warn: 'var(--nd-warn)', bad: 'var(--nd-bad)' }

export function TopologyCard({ data }: { data: WidgetData | undefined }) {
  const { t } = useTranslation()
  const disguise = useDisguise()
  const host = useRef<HTMLDivElement>(null)
  const size = useBoxSize(host)
  const places = ((data?.meta?.topology as { places?: Place[] } | undefined)?.places ?? []).filter((place) => place && typeof place.id === 'string')
  const { boxes, height, width } = layout(places, bestGrid(places, size.width - 16, size.height - 8))
  const byId = new Map(boxes.map((box) => [box.place.id, box]))
  // One element throughout, so the size is measured on the box that stays.
  return (
    <div ref={host} className="flex-1 min-h-0 px-2 pb-2 flex">
      {!boxes.length ? <div className="flex-1 flex items-center justify-center text-xs text-faint">{t('card.collecting')}</div> : (
      <svg viewBox={`-4 -4 ${width + 8} ${height + 8}`} className="w-full h-full" role="img" aria-label={t('card.topology')} data-testid="topology">
        {boxes.map((box) => {
          const parent = box.place.parent ? byId.get(box.place.parent) : undefined
          if (!parent) return null
          const from = { x: parent.x + parent.w / 2, y: parent.y + parent.h }
          const to = { x: box.x + box.w / 2, y: box.y }
          const bend = (from.y + to.y) / 2
          // Children share a trunk: down from the parent, across, and down into each.
          const d = box.h === LEAF_H ? `M${from.x} ${from.y} V${parent.y + parent.h + ROW_GAP / 2} H${to.x} V${to.y}` : `M${from.x} ${from.y} C${from.x} ${bend}, ${to.x} ${bend}, ${to.x} ${to.y}`
          const live = box.place.status === 'ok'
          return (
            <g key={`line-${box.place.id}`}>
              <path d={d} fill="none" stroke="color-mix(in srgb, var(--nd-text) 18%, transparent)" strokeWidth="1.5" />
              {live && <path d={d} className="nd-topology-run" />}
            </g>
          )
        })}
        {boxes.map((box) => {
          const colour = COLOUR[box.place.status ?? ''] ?? 'var(--nd-unknown)'
          const small = box.h === LEAF_H
          return (
            <g key={box.place.id} data-status={box.place.status ?? 'unknown'}>
              <rect x={box.x} y={box.y} width={box.w} height={box.h} rx="8" fill="color-mix(in srgb, var(--nd-text) 6%, var(--nd-bg))" stroke={box.place.status === 'bad' ? 'var(--nd-bad)' : 'var(--nd-border-strong)'} />
              <circle cx={box.x + 10} cy={box.y + (small ? 10 : 12)} r="3.5" fill={colour} />
              <text x={box.x + 19} y={box.y + (small ? 13 : 15)} fontSize={small ? 10.5 : 12} fontWeight="600" className="fill-[var(--nd-text)]">
                {clip(disguise.free(box.place.name), small ? Math.floor(box.w / 6.5) - 3 : Math.floor(box.w / 7) - 3)}
              </text>
              {box.place.detail && (
                <text x={box.x + 19} y={box.y + (small ? 24 : 28)} fontSize={small ? 9 : 10} className="num fill-[var(--nd-text-faint)]">
                  {clip(box.place.detail, roomFor(box.w, small ? 9 : 10))}
                </text>
              )}
              <title>{[box.place.name, box.place.detail].filter(Boolean).join(' · ')}</title>
            </g>
          )
        })}
      </svg>
      )}
    </div>
  )
}

/**
 * How many characters of a detail line fit inside its box: from where the
 * text starts (19) to the rounded corner on the right (8), in JetBrains Mono,
 * whose every character is 0.6 of the font size wide.
 *
 * ⚠️ It was the box over a guessed width, less three: 22 characters in a
 * large box where 20 fit, and "USW-24-PoE · 9 clients" ran into the edge.
 */
export function roomFor(boxWidth: number, fontSize: number): number {
  return Math.floor((boxWidth - 19 - 8) / (fontSize * 0.6))
}

/** A name cut to what fits its box, with an ellipsis. */
function clip(text: string, room: number): string {
  return text.length > room ? `${text.slice(0, Math.max(1, room - 1))}…` : text
}
