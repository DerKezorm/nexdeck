import { closeGaps, namedSizes, overlaps, resized, settle, shiftGroup, Steps } from './arranging'
import type { LayoutItem } from './types'

const card = (i: string, x: number, y: number, w: number, h: number): LayoutItem => ({ i, x, y, w, h })
const spots = (items: LayoutItem[]) => Object.fromEntries(items.map(({ i, x, y, w, h }) => [i, [x, y, w, h]]))
const clear = (items: LayoutItem[]) => items.every((one, index) => items.slice(index + 1).every((other) => !overlaps(one, other)))

describe('closing the gaps', () => {
  it('moves every card up as far as it goes and never sideways', () => {
    // Two columns with holes in them. Read in order and packed from the left,
    // as a reflow would, "right" would jump into the left column.
    const page = [card('a', 0, 0, 6, 2), card('b', 0, 5, 6, 2), card('right', 12, 3, 6, 4), card('low', 12, 9, 6, 2)]
    expect(spots(closeGaps(page))).toEqual({ a: [0, 0, 6, 2], b: [0, 2, 6, 2], right: [12, 0, 6, 4], low: [12, 4, 6, 2] })
  })

  it('stops under a card that spans both columns', () => {
    const page = [card('top', 0, 0, 24, 2), card('under', 4, 6, 6, 2)]
    expect(spots(closeGaps(page)).under).toEqual([4, 2, 6, 2])
  })

  it('keeps the order the cards came in, so the save is only the positions', () => {
    const page = [card('b', 0, 4, 2, 2), card('a', 0, 0, 2, 2)]
    expect(closeGaps(page).map((one) => one.i)).toEqual(['b', 'a'])
  })
})

describe('moving a group', () => {
  const page = [card('a', 0, 0, 4, 2), card('b', 4, 0, 4, 2), card('c', 12, 0, 4, 2)]

  it('moves every selected card by the same step', () => {
    const moved = shiftGroup(page, new Set(['a', 'b']), 2, 1, 24)
    expect(spots(moved!)).toEqual({ a: [2, 1, 4, 2], b: [6, 1, 4, 2], c: [12, 0, 4, 2] })
  })

  it('refuses a step onto a card that is not moving', () => {
    expect(shiftGroup(page, new Set(['a', 'b']), 5, 0, 24)).toBeNull()
  })

  it('refuses a step off the board, on either side', () => {
    expect(shiftGroup(page, new Set(['a', 'b']), -1, 0, 24)).toBeNull()
    expect(shiftGroup(page, new Set(['c']), 9, 0, 24)).toBeNull()
    expect(shiftGroup(page, new Set(['a']), 0, -1, 24)).toBeNull()
  })
})

describe('a size by name', () => {
  it('offers the floor, the size it is made at, and one and a half and twice that', () => {
    expect(namedSizes([4, 2], [6, 3], 24)).toEqual([
      { name: 'S', w: 4, h: 2 }, { name: 'M', w: 6, h: 3 }, { name: 'L', w: 9, h: 5 }, { name: 'XL', w: 12, h: 6 },
    ])
  })

  it('offers two sizes that come out the same only once', () => {
    expect(namedSizes([6, 3], [6, 3], 24).map((size) => size.name)).toEqual(['S', 'L', 'XL'])
  })

  it('never goes wider than the board', () => {
    expect(namedSizes([4, 2], [8, 3], 12).at(-1)).toEqual({ name: 'XL', w: 12, h: 6 })
  })

  it('pushes down what the bigger card now covers, and pulls it in from the edge', () => {
    const page = [card('grow', 20, 0, 4, 2), card('under', 20, 2, 4, 2), card('beside', 0, 0, 4, 2)]
    const after = resized(page, 'grow', 8, 4, 24)
    expect(spots(after)).toEqual({ grow: [16, 0, 8, 4], under: [20, 4, 4, 2], beside: [0, 0, 4, 2] })
    expect(clear(after)).toBe(true)
  })
})

describe('settling', () => {
  it('leaves a card alone that overlaps nothing', () => {
    const page = [card('a', 0, 0, 4, 2), card('b', 8, 7, 4, 2)]
    expect(settle(page, new Set(['a']))).toEqual(page)
  })

  it('pushes a whole column down, not just the first card', () => {
    const page = [card('big', 0, 0, 6, 5), card('one', 0, 2, 6, 2), card('two', 0, 4, 6, 2)]
    const after = settle(page, new Set(['big']))
    expect(spots(after)).toEqual({ big: [0, 0, 6, 5], one: [0, 5, 6, 2], two: [0, 7, 6, 2] })
  })
})

describe('steps back and forth', () => {
  const one = [card('a', 0, 0, 2, 2)]
  const two = [card('a', 4, 0, 2, 2)]
  const three = [card('a', 8, 0, 2, 2)]

  it('goes back through what was, and forward again', () => {
    const steps = new Steps()
    steps.record(one)
    steps.record(two)
    expect(steps.undo(three)).toEqual(two)
    expect(steps.undo(two)).toEqual(one)
    expect(steps.undo(one)).toBeNull()
    expect(steps.redo(one)).toEqual(two)
    expect(steps.redo(two)).toEqual(three)
    expect(steps.canRedo).toBe(false)
  })

  it('forgets what could be redone once something new is done', () => {
    const steps = new Steps()
    steps.record(one)
    steps.undo(two)
    expect(steps.canRedo).toBe(true)
    steps.record(one)
    expect(steps.canRedo).toBe(false)
  })

  it('does not count the same arrangement twice, and keeps a limit', () => {
    const steps = new Steps(3)
    steps.record(one)
    steps.record(one)
    steps.undo(two)
    expect(steps.canUndo).toBe(false)
    for (const x of [1, 2, 3, 4, 5]) steps.record([card('a', x, 0, 2, 2)])
    let back = 0
    while (steps.undo(one)) back += 1
    expect(back).toBe(3)
  })
})
