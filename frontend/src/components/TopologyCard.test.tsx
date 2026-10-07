import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { WidgetData } from '../lib/types'
import { bestGrid, layout, type Place, roomFor, TopologyCard } from './TopologyCard'

const places: Place[] = [
  { id: 'cluster', name: 'Cluster', parent: null, status: 'ok' },
  { id: 'node/a', name: 'a', parent: 'cluster', status: 'ok' },
  { id: 'node/b', name: 'b', parent: 'cluster', status: 'bad' },
  ...Array.from({ length: 5 }, (_, index) => ({ id: `a/${index}`, name: `guest ${index}`, parent: 'node/a', status: index === 4 ? 'unknown' : 'ok' })),
]

describe('the map', () => {
  it('lays the root on top, the next level across, and each one’s places under it', () => {
    const { boxes } = layout(places)
    const level = (id: string) => boxes.find((box) => box.place.id === id)!
    expect(level('cluster').level).toBe(0)
    expect(level('node/a').y).toBeGreaterThan(level('cluster').y)
    expect(level('a/0').y).toBeGreaterThan(level('node/a').y)
    // Under its own parent, on the parent's side of the card.
    expect(level('a/0').x).toBeLessThan(level('node/b').x)
  })

  it('never lets two places overlap', () => {
    const { boxes } = layout(places)
    for (const one of boxes)
      for (const other of boxes) {
        if (one === other) continue
        const apart = one.x + one.w <= other.x || other.x + other.w <= one.x || one.y + one.h <= other.y || other.y + other.h <= one.y
        expect(apart).toBe(true)
      }
  })

  it('draws a place that is down red, and runs dots only to what is up', () => {
    render(<TopologyCard data={{ status: 'bad', meta: { topology: { places } } } as unknown as WidgetData} />)
    const map = screen.getByTestId('topology')
    expect(map.querySelector('[data-status="bad"] rect')?.getAttribute('stroke')).toBe('var(--nd-bad)')
    expect(map.querySelectorAll('.nd-topology-run')).toHaveLength(5)
  })
})

describe('a deep network', () => {
  it('hangs every level under its own parent, however deep', () => {
    const chain: Place[] = [
      { id: 'gw', name: 'gateway', parent: null, status: 'ok' },
      { id: 'core', name: 'core', parent: 'gw', status: 'ok' },
      { id: 'rack', name: 'rack', parent: 'core', status: 'ok' },
      { id: 'ap1', name: 'ap 1', parent: 'core', status: 'ok' },
      { id: 'garden', name: 'garden', parent: 'rack', status: 'bad' },
    ]
    const { boxes } = layout(chain)
    const at = (id: string) => boxes.find((box) => box.place.id === id)!
    expect(boxes).toHaveLength(5)
    expect(at('garden').y).toBeGreaterThan(at('rack').y)
    expect(at('rack').y).toBeGreaterThan(at('core').y)
    expect(at('core').y).toBeGreaterThan(at('gw').y)
  })

  it('draws a place whose parent is unknown as a root rather than losing it', () => {
    const { boxes } = layout([{ id: 'x', name: 'x', parent: 'elsewhere' }, { id: 'y', name: 'y', parent: null }])
    expect(boxes.map((box) => box.place.id).sort()).toEqual(['x', 'y'])
  })
})

describe('the detail line', () => {
  it('ends before the rounded corner of its box, in the mono font every character is 0.6 em of', () => {
    for (const [width, size] of [[150, 10], [112, 9]]) {
      expect(19 + roomFor(width, size) * size * 0.6).toBeLessThanOrEqual(width - 8)
    }
    const places = [
      { id: 'sw', name: 'Core switch', parent: null, status: 'ok', detail: 'USW-24-PoE · 9 clients' },
      { id: 'ap', name: 'AP', parent: 'sw', status: 'ok' },
    ]
    render(<TopologyCard data={{ status: 'ok', meta: { topology: { places } } } as unknown as WidgetData} />)
    expect(screen.getByText('USW-24-PoE · 9 clie…')).toBeInTheDocument()
  })
})

describe('the columns of the leaves', () => {
  // A cluster with two nodes and nine guests, as the Proxmox map draws it.
  const cluster: Place[] = [
    { id: 'c', name: 'Cluster', parent: null },
    { id: 'a', name: 'pve', parent: 'c' },
    { id: 'b', name: 'pve2', parent: 'c' },
    ...['media', 'ha', 'win', 'pihole', 'deck', 'backup'].map((name) => ({ id: name, name, parent: 'a' })),
    ...['git', 'cloud', 'watch'].map((name) => ({ id: name, name, parent: 'b' })),
  ]
  const scale = (grid: number, width: number, height: number) => {
    const shape = layout(cluster, grid)
    return Math.min(width / (shape.width + 8), height / (shape.height + 8))
  }

  it('stay three on a wide card and where nothing is measured', () => {
    expect(bestGrid(cluster, 0, 0)).toBe(3)
    expect(bestGrid(cluster, 1100, 320)).toBe(3)
  })

  it('narrow on a phone, so the map is drawn larger than three columns would draw it', () => {
    const grid = bestGrid(cluster, 340, 300)
    expect(grid).toBeLessThan(3)
    expect(scale(grid, 340, 300)).toBeGreaterThan(scale(3, 340, 300) * 1.4)
  })

  it('put every leaf under its own place in one column when asked for one', () => {
    const { boxes } = layout(cluster, 1)
    const media = boxes.find((box) => box.place.id === 'media')!
    const pihole = boxes.find((box) => box.place.id === 'pihole')!
    expect(pihole.x).toBe(media.x)
    expect(pihole.y).toBeGreaterThan(media.y)
  })
})
