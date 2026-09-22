/**
 * Arranging in edit mode beyond one card and one drag: a selection moved as
 * one, a size from the card's menu, and cards sent to another page.
 */
import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Layout } from 'react-grid-layout'
import { vi } from 'vitest'

import type { LayoutItem, WidgetView } from '../lib/types'

const captured: Record<string, unknown>[] = []

vi.mock('react-grid-layout', () => ({
  Responsive: (props: Record<string, unknown>) => {
    captured.push(props)
    return <div data-testid="grid">{props.children as React.ReactNode}</div>
  },
  WidthProvider: (Component: unknown) => Component,
}))

const { BoardGrid } = await import('./BoardGrid')

function widget(id: number): WidgetView {
  return {
    id, kind: 'core.clock', title: `Card ${id}`, icon: '', link: '', renderer: 'value',
    options: {}, integration_id: null, refresh_seconds: null,
    default_size: [4, 2], min_size: [2, 1],
  } as unknown as WidgetView
}

const LAYOUT = [
  { i: '1', x: 0, y: 0, w: 4, h: 2 },
  { i: '2', x: 4, y: 0, w: 4, h: 2 },
  { i: '3', x: 0, y: 2, w: 4, h: 2 },
]

function board(extra: Record<string, unknown> = {}) {
  const saved = vi.fn()
  const moved = vi.fn()
  captured.length = 0
  const view = render(
    <BoardGrid
      {...({
        widgets: [widget(1), widget(2), widget(3)], layouts: { lg: LAYOUT, md: [], sm: [] }, data: {}, editing: true, canAct: true,
        autoCompact: false, columns: 24, onLayoutChange: saved, onMove: moved, ...extra,
      } as unknown as Parameters<typeof BoardGrid>[0])}
    />,
  )
  const wrapper = (id: number) => view.container.querySelector(`[data-widget="${id}"]`)!.parentElement!.parentElement as HTMLElement
  return { saved, moved, view, wrapper, handed: () => captured[captured.length - 1] }
}

const lastLg = (saved: ReturnType<typeof vi.fn>) => Object.fromEntries((saved.mock.calls.at(-1)![1] as LayoutItem[]).map(({ i, x, y }) => [i, [x, y]]))

describe('a selection', () => {
  it('is made with Shift and a press, and shown on the cards', () => {
    const { wrapper } = board()
    fireEvent.mouseDown(wrapper(1), { shiftKey: true })
    fireEvent.mouseDown(wrapper(2), { ctrlKey: true })
    expect(wrapper(1).getAttribute('aria-selected')).toBe('true')
    expect(wrapper(2).getAttribute('aria-selected')).toBe('true')
    expect(wrapper(3).getAttribute('aria-selected')).toBeNull()
    expect(screen.getByRole('status').textContent).toMatch(/2/)
    fireEvent.mouseDown(wrapper(2), { shiftKey: true })
    expect(wrapper(2).getAttribute('aria-selected')).toBeNull()
  })

  it('moves together with the arrow keys, and Escape lets go', async () => {
    const { wrapper, saved } = board()
    fireEvent.mouseDown(wrapper(1), { shiftKey: true })
    fireEvent.mouseDown(wrapper(2), { shiftKey: true })
    wrapper(2).focus()
    await userEvent.keyboard('{ArrowRight}')
    expect(lastLg(saved)).toEqual({ 1: [1, 0], 2: [5, 0], 3: [0, 2] })
    await userEvent.keyboard('{Escape}')
    expect(wrapper(1).getAttribute('aria-selected')).toBeNull()
  })

  it('moves together when one of it is dragged, and the second report of the grid is swallowed', () => {
    const { wrapper, saved, handed } = board()
    fireEvent.mouseDown(wrapper(1), { shiftKey: true })
    fireEvent.mouseDown(wrapper(2), { shiftKey: true })
    const grid = handed() as { onDragStart: () => void; onDragStop: (l: Layout[], a: Layout, b: Layout) => void; onLayoutChange: (c: Layout[], all: Record<string, Layout[]>) => void }
    act(() => {
      grid.onDragStart()
      grid.onDragStop([], { i: '1', x: 0, y: 0, w: 4, h: 2 }, { i: '1', x: 0, y: 5, w: 4, h: 2 })
    })
    expect(lastLg(saved)).toEqual({ 1: [0, 5], 2: [4, 5], 3: [0, 2] })
    const calls = saved.mock.calls.length
    // What the grid reports next knows of the one dragged card only.
    grid.onLayoutChange([], { lg: [{ i: '1', x: 0, y: 5, w: 4, h: 2 }, { i: '2', x: 4, y: 0, w: 4, h: 2 }, { i: '3', x: 0, y: 2, w: 4, h: 2 }] })
    expect(saved.mock.calls.length).toBe(calls)
  })

  it('takes the other selected cards along while one is still being dragged', () => {
    const { wrapper, handed } = board()
    fireEvent.mouseDown(wrapper(1), { shiftKey: true })
    fireEvent.mouseDown(wrapper(2), { shiftKey: true })
    const inner = (id: number) => wrapper(id).firstElementChild as HTMLElement
    const grid = () => handed() as { onDrag: (l: Layout[], a: Layout, b: Layout) => void }
    act(() => grid().onDrag([], { i: '1', x: 0, y: 0, w: 4, h: 2 }, { i: '1', x: 0, y: 5, w: 4, h: 2 }))
    // Five rows down: 5 × (68 + 12) pixels, before the pointer has let go.
    expect(inner(2).style.transform).toContain('400px')
    expect(inner(2).style.opacity).toBe('1')
    expect(inner(1).style.transform, 'the grid moves the dragged card itself').toBe('')
    expect(inner(3).style.transform, 'a card outside the selection stays').toBe('')
    // Where the group would land on card 3, the others fade.
    act(() => grid().onDrag([], { i: '1', x: 0, y: 0, w: 4, h: 2 }, { i: '1', x: 0, y: 2, w: 4, h: 2 }))
    expect(inner(2).style.opacity).toBe('0.4')
  })

  it('stays put where the group cannot go, and saves nothing', () => {
    const { wrapper, saved, handed } = board()
    fireEvent.mouseDown(wrapper(1), { shiftKey: true })
    fireEvent.mouseDown(wrapper(2), { shiftKey: true })
    const grid = handed() as { onDragStart: () => void; onDragStop: (l: Layout[], a: Layout, b: Layout) => void }
    act(() => {
      grid.onDragStart()
      // Card 2 would land on card 3.
      grid.onDragStop([], { i: '1', x: 0, y: 0, w: 4, h: 2 }, { i: '1', x: 0, y: 2, w: 4, h: 2 })
    })
    expect(saved).not.toHaveBeenCalled()
  })
})

describe("a card's menu", () => {
  const targets = [
    { boardName: 'Home', current: true, pages: [{ id: 7, name: 'Media' }] },
    { boardName: 'Lab', current: false, pages: [{ id: 9, name: 'Rack' }] },
  ]

  it('puts the card to a size and moves down what it now covers', async () => {
    const { saved } = board({ moveTargets: targets })
    await userEvent.click(screen.getAllByRole('button', { name: 'Size and place' })[0])
    // XL is twice the size it is made at: 8 by 4, over card 2 and card 3.
    await userEvent.click(screen.getByRole('menuitemradio', { name: /XL/ }))
    const after = Object.fromEntries((saved.mock.calls.at(-1)![1] as LayoutItem[]).map(({ i, x, y, w, h }) => [i, [x, y, w, h]]))
    expect(after[1]).toEqual([0, 0, 8, 4])
    expect(after[2][1]).toBeGreaterThanOrEqual(4)
    expect(after[3][1]).toBeGreaterThanOrEqual(4)
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('sends the card to another page, or the whole selection when the card is in it', async () => {
    const { moved, wrapper } = board({ moveTargets: targets })
    await userEvent.click(screen.getAllByRole('button', { name: 'Size and place' })[2])
    await userEvent.click(screen.getByRole('menuitem', { name: 'Rack' }))
    expect(moved).toHaveBeenLastCalledWith([3], 9)

    fireEvent.mouseDown(wrapper(1), { shiftKey: true })
    fireEvent.mouseDown(wrapper(2), { shiftKey: true })
    await userEvent.click(screen.getAllByRole('button', { name: 'Size and place' })[1])
    await userEvent.click(screen.getByRole('menuitem', { name: 'Media' }))
    expect(moved.mock.calls.at(-1)![0].sort()).toEqual([1, 2])
    expect(moved.mock.calls.at(-1)![1]).toBe(7)
  })

  it('is not offered outside edit mode', () => {
    board({ editing: false })
    expect(screen.queryByRole('button', { name: 'Size and place' })).toBeNull()
  })
})
