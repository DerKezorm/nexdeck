import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { WidgetData } from '../lib/types'
import { layout, type Place, TopologyCard } from './TopologyCard'

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

