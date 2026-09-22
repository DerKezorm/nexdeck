/**
 * A board with its own columns and rows that fill the window.
 *
 * The server hands every size in the board's columns; what the grid has to
 * get right is to draw on those columns, to read "small" on the phone in them
 * too, and to size its rows from the window only where that stays readable.
 */
import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Layout } from 'react-grid-layout'
import { vi } from 'vitest'

import { fittingRow, FIT_ROW_MAX, FIT_ROW_MIN, gridColumns } from '../lib/grid'
import type { LayoutItem, WidgetView } from '../lib/types'

const captured: Record<string, unknown>[] = []

vi.mock('react-grid-layout', () => ({
  Responsive: (props: Record<string, unknown>) => {
    captured.push(props)
    return <div data-testid="grid">{props.children as React.ReactNode}</div>
  },
  WidthProvider: (Component: unknown) => Component,
}))

const { BoardGrid, stackedFor } = await import('./BoardGrid')

function widget(id: number, size: [number, number]): WidgetView {
  return {
    id, kind: 'core.clock', title: `Card ${id}`, icon: '', link: '', renderer: 'clock',
    options: {}, integration_id: null, refresh_seconds: null,
    default_size: size, min_size: size,
  } as unknown as WidgetView
}

function draw(props: Record<string, unknown>) {
  captured.length = 0
  const view = render(<BoardGrid {...({ data: {}, canAct: true, autoCompact: false, ...props } as unknown as Parameters<typeof BoardGrid>[0])} />)
  expect(captured.length, 'the grid was never rendered, so this test proves nothing').toBeGreaterThan(0)
  return { view, handed: () => captured[captured.length - 1] }
}

describe('the columns of a board', () => {
  it('draws on the columns the board has, and on twelve when it says nothing', () => {
    const layouts = { lg: [{ i: '1', x: 18, y: 0, w: 6, h: 2 }], md: [], sm: [] }
    expect((draw({ widgets: [widget(1, [4, 2])], layouts, columns: 24 }).handed().cols as { lg: number }).lg).toBe(24)
    expect((draw({ widgets: [widget(1, [4, 2])], layouts }).handed().cols as { lg: number }).lg).toBe(12)
  })

  it('reads settings the way the server writes them', () => {
    expect(gridColumns({ columns: 36 })).toBe(36)
    expect(gridColumns({ columns: 24 })).toBe(24)
    expect(gridColumns({ columns: 7 })).toBe(12)
    expect(gridColumns(undefined)).toBe(12)
  })

  it('pairs small cards on the phone by the twelfths they are, not the columns they take', () => {
    // Two twelfths are four of 24 columns. Read as columns, these two tiles
    // would be too wide to share a row, and every tile would fill a phone.
    const wide: Layout[] = [{ i: 'a', x: 0, y: 0, w: 4, h: 2 }, { i: 'b', x: 4, y: 0, w: 4, h: 2 }, { i: 'c', x: 8, y: 0, w: 6, h: 2 }, { i: 'd', x: 14, y: 0, w: 6, h: 2 }]
    const stacked = stackedFor(wide, 4, 24)
    expect(stacked.map(({ i, x, y, w }) => [i, x, y, w])).toEqual([['a', 0, 0, 2], ['b', 2, 0, 2], ['c', 0, 2, 4], ['d', 0, 4, 4]])
  })

  it('moves a card with the arrow keys up to the edge of its own columns, and no further', async () => {
    const press = async (x: number) => {
      const saved = vi.fn()
      const { view } = draw({ widgets: [widget(1, [2, 2])], layouts: { lg: [{ i: '1', x, y: 0, w: 2, h: 2 }], md: [], sm: [] }, columns: 24, editing: true, onLayoutChange: saved })
      const card = view.container.querySelector('[tabindex="0"]') as HTMLElement
      card.focus()
      await userEvent.keyboard('{ArrowRight}')
      view.unmount()
      return saved.mock.calls.map(([, layout]) => (layout as LayoutItem[])[0].x)
    }
    // Far past the twelve columns a board used to have.
    expect(await press(21)).toEqual([22])
    // 22 and two wide is the whole of 24: nothing left to move into.
    expect(await press(22)).toEqual([])
  })
})

describe('rows that fill the window', () => {
  it('shares the space out between the rows and their gaps', () => {
    // 6 rows, 5 gaps of 12: (720 - 60) / 6 = 110.
    expect(fittingRow(720, 6, 12)).toBe(110)
  })

  it('stops at a height a card can still be read at', () => {
    expect(fittingRow(300, 20, 12)).toBeNull()
    expect(fittingRow(20 * FIT_ROW_MIN + 19 * 12, 20, 12)).toBe(FIT_ROW_MIN)
  })

  it('does not blow a short page up into posters', () => {
    expect(fittingRow(2000, 2, 12)).toBe(FIT_ROW_MAX)
  })

  it('hands the grid the fitted height, and the usual one when fitting is off', () => {
    const tall = vi.spyOn(window, 'innerHeight', 'get').mockReturnValue(1000)
    try {
      const layouts = { lg: [{ i: '1', x: 0, y: 0, w: 6, h: 4 }, { i: '2', x: 0, y: 4, w: 6, h: 4 }], md: [], sm: [] }
      const widgets = [widget(1, [6, 4]), widget(2, [6, 4])]
      // jsdom puts everything at the top, so the space is 1000 minus the 40 left under the board.
      expect(draw({ widgets, layouts, columns: 24, fitHeight: true }).handed().rowHeight).toBe(fittingRow(960, 8, 12))
      expect(draw({ widgets, layouts, columns: 24 }).handed().rowHeight).toBe(68)
    } finally {
      tall.mockRestore()
    }
  })
})
