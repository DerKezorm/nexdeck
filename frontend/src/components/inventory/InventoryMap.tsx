/**
 * The inventory as a map (roadmap M5): hosts above, what runs on them below,
 * lines between. Drag a box to put it somewhere else; where each box stands
 * is kept for the installation. Red is down, a dashed line only proposed.
 */
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { get, put } from '../../api/client'
import { layered, NODE_HEIGHT, NODE_WIDTH, type Inventory } from '../../lib/inventory'

type Positions = Record<string, [number, number]>

export function InventoryMap({ inventory }: { inventory: Inventory }) {
  const { t } = useTranslation()
  const [positions, setPositions] = useState<Positions | null>(null)
  const dragging = useRef<{ ref: string; dx: number; dy: number } | null>(null)
  const svg = useRef<SVGSVGElement>(null)

  useEffect(() => {
    let gone = false
    void get<{ positions: Positions }>('/inventory/layout')
      .then((answer) => {
        if (!gone) setPositions({ ...layered(inventory), ...answer.positions })
      })
      .catch(() => {
        if (!gone) setPositions(layered(inventory))
      })
    return () => {
      gone = true
    }
  }, [inventory])

  if (!positions) return <div className="h-[480px]" />
  const at = (ref: string): [number, number] => positions[ref] ?? [0, 0]
  const lines: { from: string; to: string; proposed: boolean }[] = [
    ...inventory.nodes.filter((node) => node.parent).map((node) => ({ from: node.parent as string, to: node.ref, proposed: false })),
    ...inventory.relations.filter((one) => one.state !== 'rejected').map((one) => ({ from: one.parent, to: one.child, proposed: one.state === 'suggested' })),
  ].filter((line) => positions[line.from] && positions[line.to])
  const width = Math.max(640, ...Object.values(positions).map(([x]) => x + NODE_WIDTH + 24))
  const height = Math.max(420, ...Object.values(positions).map(([, y]) => y + NODE_HEIGHT + 24))

  const point = (event: React.PointerEvent): [number, number] => {
    const box = svg.current?.getBoundingClientRect()
    return box ? [event.clientX - box.left, event.clientY - box.top] : [0, 0]
  }
  const save = (next: Positions) => void put('/inventory/layout', { positions: next }).catch(() => undefined)

  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <p className="flex-1 text-[12px] text-muted">{t('inventory.mapHelp')}</p>
        <button
          type="button"
          className="btn"
          onClick={() => {
            const fresh = layered(inventory)
            setPositions(fresh)
            save(fresh)
          }}
        >
          {t('inventory.arrange')}
        </button>
      </div>
      <div className="scroll max-h-[70vh] overflow-auto rounded-xl border border-line">
        <svg
          ref={svg}
          width={width}
          height={height}
          className="select-none touch-none"
          data-testid="inventory-map"
          onPointerMove={(event) => {
            const drag = dragging.current
            if (!drag) return
            const [x, y] = point(event)
            setPositions((old) => (old ? { ...old, [drag.ref]: [Math.max(0, x - drag.dx), Math.max(0, y - drag.dy)] } : old))
          }}
          onPointerUp={() => {
            if (!dragging.current) return
            dragging.current = null
            if (positions) save(positions)
          }}
          onPointerLeave={() => {
            dragging.current = null
          }}
        >
          <g className="text-line-strong">
            {lines.map((line) => {
              const [x1, y1] = at(line.from)
              const [x2, y2] = at(line.to)
              return (
                <line
                  key={`${line.from}>${line.to}`}
                  x1={x1 + NODE_WIDTH / 2}
                  y1={y1 + NODE_HEIGHT}
                  x2={x2 + NODE_WIDTH / 2}
                  y2={y2}
                  stroke="currentColor"
                  strokeWidth={1.5}
                  strokeDasharray={line.proposed ? '5 4' : undefined}
                />
              )
            })}
          </g>
          {inventory.nodes.filter((node) => positions[node.ref]).map((node) => {
            const [x, y] = at(node.ref)
            return (
              <g
                key={node.ref}
                transform={`translate(${x} ${y})`}
                className="cursor-grab"
                data-testid="inventory-node"
                onPointerDown={(event) => {
                  const [px, py] = point(event)
                  dragging.current = { ref: node.ref, dx: px - x, dy: py - y }
                }}
              >
                <rect
                  width={NODE_WIDTH}
                  height={NODE_HEIGHT}
                  rx={10}
                  fill="var(--nd-surface-strong)"
                  stroke={node.down ? 'var(--nd-bad)' : node.host ? 'var(--nd-accent)' : 'var(--nd-border-strong)'}
                  strokeWidth={node.down ? 2 : 1}
                />
                <text x={10} y={18} fontSize={12} fontWeight={600} fill="var(--nd-text)">
                  {node.name.length > 22 ? `${node.name.slice(0, 21)}…` : node.name}
                </text>
                <text x={10} y={34} fontSize={10.5} fill="var(--nd-text-faint)">
                  {node.down ? t('inventory.down') : t(`inventory.kind.${node.kind}`)}
                </text>
              </g>
            )
          })}
        </svg>
      </div>
    </div>
  )
}
