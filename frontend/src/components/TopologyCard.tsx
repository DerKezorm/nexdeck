import { useTranslation } from 'react-i18next'

import { useDisguise } from '../lib/showcase'
import type { WidgetData } from '../lib/types'

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

const WIDTH = 640
const ROOT_H = 34
const ROW_GAP = 30
const LEAF_W = 112
const LEAF_H = 30
const LEAF_GAP = 8

/**
 * Where every place stands: the root on top, the next level spread across
 * the width, and the places under each of those in a grid of up to three
 * columns beneath it. Deeper levels are laid out as leaves of their parent.
 */
export function layout(places: Place[]): { boxes: Box[]; height: number } {
  const known = new Set(places.map((place) => place.id))
  const roots = places.filter((place) => !place.parent || !known.has(place.parent))
  const childrenOf = (id: string) => places.filter((place) => place.parent === id)
  const boxes: Box[] = []
  if (!roots.length) return { boxes, height: 0 }
  const rootW = 150
  roots.forEach((root, index) => boxes.push({ place: root, x: (WIDTH / (roots.length + 1)) * (index + 1) - rootW / 2, y: 0, w: rootW, h: ROOT_H, level: 0 }))
  const middle = roots.flatMap((root) => childrenOf(root.id))
  if (!middle.length) return { boxes, height: ROOT_H }
  const slot = WIDTH / middle.length
  const midY = ROOT_H + ROW_GAP
  const midW = Math.min(150, slot - 12)
  let bottom = midY + ROOT_H
  middle.forEach((place, index) => {
    const centre = slot * index + slot / 2
    boxes.push({ place, x: centre - midW / 2, y: midY, w: midW, h: ROOT_H, level: 1 })
    const leaves = childrenOf(place.id)
    const columns = Math.max(1, Math.min(3, Math.floor((slot - 8) / (LEAF_W + LEAF_GAP)), leaves.length))
    const leafW = Math.min(LEAF_W, (slot - 8 - (columns - 1) * LEAF_GAP) / columns)
    const span = columns * leafW + (columns - 1) * LEAF_GAP
    leaves.forEach((leaf, n) => {
      const column = n % columns
      const row = Math.floor(n / columns)
      const y = midY + ROOT_H + ROW_GAP + row * (LEAF_H + LEAF_GAP)
      boxes.push({ place: leaf, x: centre - span / 2 + column * (leafW + LEAF_GAP), y, w: leafW, h: LEAF_H, level: 2 })
      bottom = Math.max(bottom, y + LEAF_H)
    })
  })
  return { boxes, height: bottom }
}

const COLOUR: Record<string, string> = { ok: 'var(--nd-ok)', warn: 'var(--nd-warn)', bad: 'var(--nd-bad)' }

export function TopologyCard({ data }: { data: WidgetData | undefined }) {
  const { t } = useTranslation()
  const disguise = useDisguise()
  const places = ((data?.meta?.topology as { places?: Place[] } | undefined)?.places ?? []).filter((place) => place && typeof place.id === 'string')
  const { boxes, height } = layout(places)
  if (!boxes.length) return <div className="flex-1 flex items-center justify-center text-xs text-faint">{t('card.collecting')}</div>
  const byId = new Map(boxes.map((box) => [box.place.id, box]))
  return (
    <div className="flex-1 min-h-0 px-2 pb-2">
      <svg viewBox={`-4 -4 ${WIDTH + 8} ${height + 8}`} className="w-full h-full" role="img" aria-label={t('card.topology')} data-testid="topology">
        {boxes.map((box) => {
          const parent = box.place.parent ? byId.get(box.place.parent) : undefined
          if (!parent) return null
          const from = { x: parent.x + parent.w / 2, y: parent.y + parent.h }
          const to = { x: box.x + box.w / 2, y: box.y }
          const bend = (from.y + to.y) / 2
          // Leaves of one parent share a trunk: down from the parent, across, and down into each.
          const d = box.level === 2 ? `M${from.x} ${from.y} V${parent.y + parent.h + ROW_GAP / 2} H${to.x} V${to.y}` : `M${from.x} ${from.y} C${from.x} ${bend}, ${to.x} ${bend}, ${to.x} ${to.y}`
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
          const small = box.level === 2
          return (
            <g key={box.place.id} data-status={box.place.status ?? 'unknown'}>
              <rect x={box.x} y={box.y} width={box.w} height={box.h} rx="8" fill="color-mix(in srgb, var(--nd-text) 6%, var(--nd-bg))" stroke={box.place.status === 'bad' ? 'var(--nd-bad)' : 'var(--nd-border-strong)'} />
              <circle cx={box.x + 10} cy={box.y + (small ? 10 : 12)} r="3.5" fill={colour} />
              <text x={box.x + 19} y={box.y + (small ? 13 : 15)} fontSize={small ? 10.5 : 12} fontWeight="600" className="fill-[var(--nd-text)]">
                {clip(disguise.free(box.place.name), small ? Math.floor(box.w / 6.5) - 3 : Math.floor(box.w / 7) - 3)}
              </text>
              {box.place.detail && (
                <text x={box.x + 19} y={box.y + (small ? 24 : 28)} fontSize={small ? 9 : 10} className="num fill-[var(--nd-text-faint)]">
                  {clip(box.place.detail, small ? Math.floor(box.w / 5.6) - 3 : Math.floor(box.w / 6) - 3)}
                </text>
              )}
              <title>{[box.place.name, box.place.detail].filter(Boolean).join(' · ')}</title>
            </g>
          )
        })}
      </svg>
    </div>
  )
}

/** A name cut to what fits its box, with an ellipsis. */
function clip(text: string, room: number): string {
  return text.length > room ? `${text.slice(0, Math.max(1, room - 1))}…` : text
}
