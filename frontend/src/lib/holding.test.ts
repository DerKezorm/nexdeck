import { describe, expect, it } from 'vitest'

import { boardRowsFor, cellAt, freeSpot, grown, heldSizeOf, pack, rowsOf, sizeFromBoard, sizeOnBoard } from './holding'
import type { WidgetView } from './types'

const card = (options: Record<string, unknown> = {}) => ({ id: 1, kind: 'core.clock', options }) as unknown as WidgetView

describe('the size of a held card', () => {
  it('is its own when it has one', () => {
    expect(heldSizeOf(card({ held_size: { w: 6, h: 3 } }))).toEqual({ w: 6, h: 3 })
  })

  it('follows the old even columns of its group until it has one', () => {
    expect(heldSizeOf(card(), '3')).toEqual({ w: 4, h: 2 })
    expect(heldSizeOf(card(), '2')).toEqual({ w: 6, h: 2 })
    expect(heldSizeOf(card(), 'auto')).toEqual({ w: 4, h: 2 })
    expect(heldSizeOf(card({ held_size: { w: 20, h: 3 } }), '6')).toEqual({ w: 2, h: 2 }, 'nothing outside the twelve')
  })

  it('goes from the board into the group by its share of the width, and back', () => {
    expect(sizeFromBoard({ w: 6, h: 3 }, 24)).toEqual({ w: 3, h: 3 })
    expect(sizeFromBoard({ w: 6, h: 3 }, 12)).toEqual({ w: 6, h: 3 })
    expect(sizeOnBoard({ w: 3, h: 2 }, 24)).toEqual({ w: 6, h: 2 })
  })
})

describe('packing a group', () => {
  it('puts each card in the first place from the top left where it fits', () => {
    // Plex wide and tall, two small ones beside it, a wide line under the small ones.
    const packed = pack([{ w: 6, h: 3 }, { w: 3, h: 2 }, { w: 3, h: 2 }, { w: 6, h: 1 }])
    expect(packed).toEqual([
      { x: 0, y: 0, w: 6, h: 3 },
      { x: 6, y: 0, w: 3, h: 2 },
      { x: 9, y: 0, w: 3, h: 2 },
      { x: 6, y: 2, w: 6, h: 1 },
    ])
    expect(rowsOf(packed)).toBe(3)
  })

  it('fills a gap a later card fits into', () => {
    const packed = pack([{ w: 8, h: 1 }, { w: 6, h: 1 }, { w: 4, h: 1 }])
    expect(packed[2]).toEqual({ x: 8, y: 0, w: 4, h: 1 })
  })

  it('needs board rows for its title and its own rows', () => {
    expect(boardRowsFor(3, 68, 12)).toBe(4)
    expect(boardRowsFor(0, 68, 12)).toBe(2)
  })
})

describe('room on the board', () => {
  const layout = [
    { i: 'g', x: 0, y: 0, w: 12, h: 3 },
    { i: 'a', x: 0, y: 3, w: 6, h: 2 },
    { i: 'b', x: 6, y: 3, w: 6, h: 2 },
    { i: 'c', x: 0, y: 5, w: 6, h: 2 },
  ]

  it('pushes the cards under a growing group down, and those under them', () => {
    const after = grown(layout, 'g', 5)
    expect(after.find((one) => one.i === 'a')!.y).toBe(5)
    expect(after.find((one) => one.i === 'b')!.y).toBe(5)
    expect(after.find((one) => one.i === 'c')!.y).toBe(7)
  })

  it('pulls nothing up when a group shrinks', () => {
    expect(grown(layout, 'g', 2).find((one) => one.i === 'a')!.y).toBe(3)
  })

  it('finds the spot dropped on when it is free, else the next one', () => {
    expect(freeSpot(layout, 6, 2, 6, 5, 12)).toEqual({ x: 6, y: 5 })
    expect(freeSpot(layout, 6, 2, 0, 5, 12)).toEqual({ x: 6, y: 5 })
    expect(freeSpot(layout, 12, 2, 0, 1, 12)).toEqual({ x: 0, y: 7 })
  })

  it('reads the cell under the pointer', () => {
    // Twelve columns of 88 px with 12 px between them make 1188 px.
    expect(cellAt(250, 170, 1188, 12, 68, 12)).toEqual({ x: 2, y: 2 })
    expect(cellAt(-5, -5, 1188, 12, 68, 12)).toEqual({ x: 0, y: 0 })
  })
})
