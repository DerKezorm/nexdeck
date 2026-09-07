/**
 * Every card has a floor under its size: the smallest the adapter says it is
 * still usable at. Saved layouts below that floor are lifted, and the floor
 * never exceeds the columns of the form factor.
 */
import type { WidgetView } from '../lib/types'
import { layoutFor } from './BoardGrid'

function widget(id: number, size: [number, number], min?: [number, number]): WidgetView {
  return {
    id, kind: 'core.clock', title: 'Clock', icon: '', link: '', renderer: 'clock',
    options: {}, integration_id: null, refresh_seconds: null,
    default_size: size, min_size: min ?? size,
  } as unknown as WidgetView
}

describe('layoutFor', () => {
  it('lets a card go down to the size the adapter calls its minimum', () => {
    // ⚠️ The floor used to be `default_size`, which made `min_size` dead:
    // all 195 widgets declare one below their default, so none of them was
    // ever reachable and a search bar could not be made into a bar.
    const [item] = layoutFor([{ i: '1', x: 0, y: 0, w: 2, h: 1 }], [widget(1, [4, 2], [2, 1])], 12)
    expect([item.w, item.h, item.minW, item.minH]).toEqual([2, 1, 2, 1])
  })

  it('still lifts a card that was saved below its minimum', () => {
    const [item] = layoutFor([{ i: '1', x: 0, y: 0, w: 1, h: 1 }], [widget(1, [4, 2], [3, 2])], 12)
    expect([item.w, item.h, item.minW, item.minH]).toEqual([3, 2, 3, 2])
  })

  it('keeps a larger saved size and position', () => {
    const [item] = layoutFor([{ i: '1', x: 2, y: 1, w: 5, h: 3 }], [widget(1, [3, 2])], 12)
    expect([item.x, item.y, item.w, item.h]).toEqual([2, 1, 5, 3])
  })

  it('caps the floor at the columns of the form factor', () => {
    const [item] = layoutFor(undefined, [widget(1, [6, 4])], 4)
    expect([item.w, item.minW, item.h, item.minH]).toEqual([4, 4, 4, 4])
  })

  it('places widgets without a position below the others', () => {
    const items = layoutFor([{ i: '1', x: 0, y: 0, w: 3, h: 2 }], [widget(1, [3, 2]), widget(2, [2, 1])], 12)
    expect(items[1]).toMatchObject({ i: '2', x: 0, y: 2, w: 3, h: 2, minW: 2, minH: 1 })
  })

  it('falls back to the default size when a widget declares no minimum', () => {
    const bare = { ...widget(1, [3, 2]), min_size: undefined } as unknown as WidgetView
    const [item] = layoutFor([{ i: '1', x: 0, y: 0, w: 1, h: 1 }], [bare], 12)
    expect([item.minW, item.minH]).toEqual([3, 2])
  })
})

/**
 * One card's data arriving must not redraw the board.
 *
 * ⚠️ Measured before this: thirty cards, the data of one of them changing,
 * thirty renders. Two things caused it together, and fixing either alone
 * changes nothing: the card was not memoised, and it was handed four freshly
 * made closures on every render, which defeats a memo. So this test counts.
 */
import { render } from '@testing-library/react'
import { vi } from 'vitest'

import type { WidgetData } from '../lib/types'
import { BoardGrid } from './BoardGrid'

const drawn = vi.fn()

vi.mock('./WidgetCard', () => ({
  WidgetCard: ({ widget }: { widget: WidgetView }) => {
    drawn(widget.id)
    return <div data-testid={`card-${widget.id}`} />
  },
}))

describe('a board that redraws', () => {
  it('draws only the card whose data changed', () => {
    const widgets = Array.from({ length: 30 }, (_, index) => widget(index + 1, [2, 2]))
    const layouts = { lg: [], md: [], sm: [] }
    const data: Record<number, WidgetData | undefined> = {}
    const noop = () => {}
    const props = {
      widgets, layouts, editing: false, canAct: true, autoCompact: false,
      onAction: noop, onRefresh: noop, onSettings: noop, onRemove: noop,
    } as unknown as Parameters<typeof BoardGrid>[0]

    const view = render(<BoardGrid {...props} data={data} />)
    expect(drawn).toHaveBeenCalledTimes(30)

    drawn.mockClear()
    // One card's data arrives. The object for every other card is the same
    // reference it was, which is what a live update looks like.
    view.rerender(<BoardGrid {...props} data={{ ...data, 7: { status: 'ok' } as WidgetData }} />)
    expect(drawn.mock.calls.map(([id]) => id)).toEqual([7])
  })
})
