/**
 * One arrangement, two screens.
 *
 * ⚠️ Reported on 10.09.2026: on the phone the cards stood in no order at all.
 * The phone kept a layout of its own, written once when a card was added and
 * never again, so arranging the board on a monitor left the phone as it was.
 * Measured on a board of 25 cards: 6 in the same place, one 15 places off.
 * The phone's board is now worked out from the wide one and never saved.
 */
import { act, render, screen } from '@testing-library/react'
import type { Layout } from 'react-grid-layout'
import { vi } from 'vitest'

import type { Breakpoint, LayoutItem, WidgetView } from '../lib/types'

const captured: Record<string, unknown>[] = []

vi.mock('react-grid-layout', () => ({
  Responsive: (props: Record<string, unknown>) => {
    captured.push(props)
    return <div data-testid="grid">{props.children as React.ReactNode}</div>
  },
  WidthProvider: (Component: unknown) => Component,
}))

const { BoardGrid, stackedFor } = await import('./BoardGrid')

type Change = (current: Layout[], all: Record<string, Layout[]>) => void

function widget(id: number, size: [number, number] = [2, 2]): WidgetView {
  return {
    id, kind: 'core.clock', title: `Card ${id}`, icon: '', link: '', renderer: 'clock',
    options: {}, integration_id: null, refresh_seconds: null,
    default_size: size, min_size: size,
  } as unknown as WidgetView
}

const card = (i: string, x: number, y: number, w: number, h: number): Layout => ({ i, x, y, w, h })

function board(layouts: Record<Breakpoint, LayoutItem[]>, widgets: WidgetView[], editing: boolean) {
  const saved = vi.fn()
  captured.length = 0
  render(
    <BoardGrid
      {...({ widgets, layouts, data: {}, editing, canAct: true, autoCompact: false, onLayoutChange: saved } as unknown as Parameters<typeof BoardGrid>[0])}
    />,
  )
  expect(captured.length, 'the grid was never rendered, so this test proves nothing').toBeGreaterThan(0)
  return { saved, handed: () => captured[captured.length - 1] }
}

describe('the stack on a phone', () => {
  it('reads the wide board like a page: row by row, left to right', () => {
    const wide = [card('c', 6, 0, 4, 3), card('a', 0, 0, 3, 3), card('d', 0, 3, 12, 2), card('b', 3, 0, 3, 3)]
    expect(stackedFor(wide, 4).map((one) => one.i)).toEqual(['a', 'b', 'c', 'd'])
  })

  it('gives a card the full width and puts the next one right under it', () => {
    const stacked = stackedFor([card('a', 0, 0, 3, 3), card('b', 3, 0, 6, 2), card('c', 0, 5, 12, 4)], 4)
    expect(stacked.map(({ x, y, w, h }) => [x, y, w, h])).toEqual([[0, 0, 4, 3], [0, 3, 4, 2], [0, 5, 4, 4]])
  })

  it('lets two small cards of the same height share a row', () => {
    const stacked = stackedFor([card('a', 0, 0, 2, 1), card('b', 2, 0, 2, 1), card('c', 4, 0, 2, 1)], 4)
    expect(stacked.map(({ i, x, y, w }) => [i, x, y, w])).toEqual([['a', 0, 0, 2], ['b', 2, 0, 2], ['c', 0, 1, 4]])
  })

  it('does not squeeze a list, and does not pair cards of different heights', () => {
    // Three columns of twelve is a list, not a tile: at half a phone it is unreadable.
    expect(stackedFor([card('a', 0, 0, 3, 2), card('b', 3, 0, 3, 2)], 4).map((one) => one.w)).toEqual([4, 4])
    expect(stackedFor([card('a', 0, 0, 2, 2), card('b', 2, 0, 2, 1)], 4).map((one) => one.w)).toEqual([4, 4])
  })

  it('offers no card on the phone to drag or resize', () => {
    const stacked = stackedFor([card('a', 0, 0, 2, 2), card('b', 2, 0, 2, 2), card('c', 0, 2, 6, 3)], 4)
    expect(stacked.length).toBe(3)
    expect(stacked.every((one) => one.isDraggable === false && one.isResizable === false)).toBe(true)
  })

  it('keeps the floor under the height of a card', () => {
    expect(stackedFor([{ ...card('a', 0, 0, 4, 1), minH: 3 }], 4)[0].h).toBe(3)
  })
})

describe('what the grid is handed', () => {
  it('two screens, and the phone follows the wide board rather than what was once saved for it', () => {
    const widgets = [widget(1, [3, 2]), widget(2, [3, 2]), widget(3, [3, 2])]
    const layouts = {
      lg: [{ i: '1', x: 0, y: 0, w: 3, h: 2 }, { i: '2', x: 3, y: 0, w: 3, h: 2 }, { i: '3', x: 0, y: 2, w: 3, h: 2 }],
      md: [{ i: '3', x: 0, y: 0, w: 2, h: 2 }, { i: '2', x: 2, y: 0, w: 2, h: 2 }, { i: '1', x: 4, y: 0, w: 2, h: 2 }],
      // What an old phone layout looked like: the order the cards were added in, at half the width.
      sm: [{ i: '3', x: 0, y: 0, w: 2, h: 2 }, { i: '1', x: 2, y: 0, w: 2, h: 2 }, { i: '2', x: 0, y: 2, w: 2, h: 2 }],
    }
    const props = board(layouts, widgets, false).handed()
    expect(props.breakpoints).toEqual({ lg: 700, sm: 0 })
    expect(props.cols).toEqual({ lg: 12, sm: 4 })
    const grid = props.layouts as Record<string, Layout[]>
    expect(Object.keys(grid).sort()).toEqual(['lg', 'sm'])
    expect(grid.sm.map((one) => one.i)).toEqual(['1', '2', '3'])
    expect(grid.sm.map((one) => one.w)).toEqual([4, 4, 4])
  })
})

describe('saving an arrangement', () => {
  const widgets = [widget(1), widget(2)]
  const layouts = { lg: [{ i: '1', x: 0, y: 0, w: 2, h: 2 }, { i: '2', x: 2, y: 0, w: 2, h: 2 }], md: [], sm: [] }

  it('keeps the wide arrangement when a card was moved on it', () => {
    const { saved, handed } = board(layouts, widgets, true)
    const grid = handed().layouts as Record<string, Layout[]>
    const dragged = [card('1', 6, 0, 2, 2), card('2', 2, 0, 2, 2)]
    act(() => (handed().onLayoutChange as Change)(dragged, { ...grid, lg: dragged }))
    expect(saved).toHaveBeenCalledTimes(1)
    expect(saved.mock.calls[0]).toEqual(['lg', [{ i: '1', x: 6, y: 0, w: 2, h: 2 }, { i: '2', x: 2, y: 0, w: 2, h: 2 }]])
  })

  it('saves nothing when only the stack changed', () => {
    // ⚠️ The phone's stack is worked out, not kept. Saving it would write a
    // layout nobody reads, and a phone turned sideways while editing would
    // send a save for every turn.
    const { saved, handed } = board(layouts, widgets, true)
    const grid = handed().layouts as Record<string, Layout[]>
    const shifted = grid.sm.map((one) => ({ ...one, y: one.y + 1 }))
    act(() => (handed().onLayoutChange as Change)(shifted, { ...grid, sm: shifted }))
    expect(saved).not.toHaveBeenCalled()
  })
})

describe('edit mode on a phone', () => {
  const layouts = { lg: [{ i: '1', x: 0, y: 0, w: 2, h: 2 }], md: [], sm: [] }

  it('says why the cards do not move, and only on the phone', () => {
    const { handed } = board(layouts, [widget(1)], true)
    expect(screen.queryByRole('note'), 'the note shows on a wide screen, where cards can be dragged').toBeNull()
    act(() => (handed().onBreakpointChange as (next: string, cols: number) => void)('sm', 4))
    expect(screen.getByRole('note').textContent).toMatch(/wider screen/)
  })

  it('says nothing outside edit mode', () => {
    const { handed } = board(layouts, [widget(1)], false)
    act(() => (handed().onBreakpointChange as (next: string, cols: number) => void)('sm', 4))
    expect(screen.queryByRole('note')).toBeNull()
  })
})
