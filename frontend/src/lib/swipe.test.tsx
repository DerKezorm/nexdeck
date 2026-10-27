/**
 * A sideways swipe turns the page; a scroll never does, nor a finger that
 * starts on something that moves sideways by itself.
 */
import { fireEvent, render } from '@testing-library/react'
import { useRef } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { pageAfter, scrolling, swipeOf, takesSideways, useSwipe } from './swipe'

const at = (x: number, y: number, t = 0) => ({ x, y, t })

describe('what counts as a swipe', () => {
  it('is far, quick and sideways, and says which way', () => {
    expect(swipeOf(at(300, 400), at(200, 410, 200))).toBe(-1)
    expect(swipeOf(at(100, 400), at(220, 380, 200))).toBe(1)
  })

  it('is not a short one, a slow one or a slanting one', () => {
    expect(swipeOf(at(300, 400), at(250, 400, 100)), 'too short').toBe(0)
    expect(swipeOf(at(300, 400), at(100, 400, 1500)), 'too slow').toBe(0)
    expect(swipeOf(at(300, 400), at(200, 340, 200)), 'more down than twice sideways').toBe(0)
  })

  it('stops for good once the finger has gone up or down first', () => {
    expect(scrolling(at(100, 100), at(104, 118))).toBe(true)
    expect(scrolling(at(100, 100), at(130, 110))).toBe(false)
    expect(scrolling(at(100, 100), at(102, 105)), 'too little to tell').toBe(false)
  })
})

describe('where a swipe leads', () => {
  const pages = [{ id: 4 }, { id: 9 }, { id: 2 }]
  it('to the next page with the finger to the left, the one before to the right, and no further than the ends', () => {
    expect(pageAfter(pages, 9, -1)).toEqual({ id: 2 })
    expect(pageAfter(pages, 9, 1)).toEqual({ id: 4 })
    expect(pageAfter(pages, 2, -1)).toBeUndefined()
    expect(pageAfter(pages, 4, 1)).toBeUndefined()
    expect(pageAfter(pages, 7, -1), 'a page that is gone').toBeUndefined()
  })
})

describe('where a swipe may start', () => {
  it('not in a field, a row that scrolls sideways, a swiped control or a place marked so', () => {
    document.body.innerHTML = `
      <div id="root">
        <p id="text">words</p>
        <input id="field">
        <div id="row" style="overflow-x: auto"><span id="inside">wide</span></div>
        <div style="touch-action: pan-y"><button id="dial">20°</button></div>
        <nav data-no-swipe><a id="tab">Media</a></nav>
      </div>`
    const root = document.getElementById('root')
    const row = document.getElementById('row')!
    Object.defineProperty(row, 'scrollWidth', { value: 900, configurable: true })
    Object.defineProperty(row, 'clientWidth', { value: 300 })
    expect(takesSideways(document.getElementById('text'), root)).toBe(false)
    for (const id of ['field', 'inside', 'dial', 'tab']) expect(takesSideways(document.getElementById(id), root), id).toBe(true)
    // A row with nothing to scroll is just a row.
    Object.defineProperty(row, 'scrollWidth', { value: 300 })
    expect(takesSideways(document.getElementById('inside'), root)).toBe(false)
  })
})

function Area({ enabled, onSwipe }: { enabled: boolean; onSwipe: (direction: -1 | 1) => void }) {
  const area = useRef<HTMLDivElement>(null)
  useSwipe(area, enabled, onSwipe)
  return (
    <div>
      <div ref={area}>
        <p>the page</p>
      </div>
      <p>a sheet over it</p>
    </div>
  )
}

function swipe(element: Element, from: [number, number], to: [number, number], moves: [number, number][] = []) {
  fireEvent.touchStart(element, { touches: [{ clientX: from[0], clientY: from[1] }] })
  for (const [x, y] of moves) fireEvent.touchMove(element, { touches: [{ clientX: x, clientY: y }] })
  fireEvent.touchEnd(element, { touches: [], changedTouches: [{ clientX: to[0], clientY: to[1] }] })
}

describe('a swipe on the page', () => {
  let phone = true
  beforeEach(() => {
    phone = true
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: phone, media: query }))
  })
  afterEach(() => vi.unstubAllGlobals())

  it('turns the page on a phone, and nothing else does', () => {
    const turned = vi.fn()
    const view = render(<Area enabled onSwipe={turned} />)
    const page = view.getByText('the page')
    swipe(page, [300, 400], [180, 405])
    expect(turned).toHaveBeenLastCalledWith(-1)
    swipe(page, [100, 400], [240, 395])
    expect(turned).toHaveBeenLastCalledWith(1)
    expect(turned).toHaveBeenCalledTimes(2)
    // A scroll that ends up sideways is still a scroll.
    swipe(page, [300, 400], [150, 420], [[302, 380], [250, 400]])
    // Outside the page: a sheet drawn over it.
    swipe(view.getByText('a sheet over it'), [300, 400], [150, 400])
    expect(turned).toHaveBeenCalledTimes(2)
  })

  it('does nothing while switched off, nor on a wide screen', () => {
    const turned = vi.fn()
    const view = render(<Area enabled={false} onSwipe={turned} />)
    swipe(view.getByText('the page'), [300, 400], [150, 400])
    view.unmount()
    phone = false
    const wide = render(<Area enabled onSwipe={turned} />)
    swipe(wide.getByText('the page'), [300, 400], [150, 400])
    expect(turned).not.toHaveBeenCalled()
  })
})
