/**
 * Every card has a floor under its size: what it was created with. Saved
 * layouts below that floor are lifted, and the floor never exceeds the
 * columns of the form factor.
 */
import type { WidgetView } from '../lib/types'
import { layoutFor } from './BoardGrid'

function widget(id: number, size: [number, number]): WidgetView {
  return { id, kind: 'core.clock', title: 'Clock', icon: '', link: '', renderer: 'clock', options: {}, integration_id: null, refresh_seconds: null, default_size: size }
}

describe('layoutFor', () => {
  it('never lets a card be smaller than the size it was created with', () => {
    const [item] = layoutFor([{ i: '1', x: 0, y: 0, w: 1, h: 1 }], [widget(1, [3, 2])], 12)
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
})
