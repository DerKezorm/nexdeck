import { afterEach, describe, expect, it } from 'vitest'

import { keepInView, shiftIntoView } from './keepInView'

describe('shiftIntoView', () => {
  it('moves a box that sticks out on the left to the margin', () => {
    expect(shiftIntoView(-167, 89, 400)).toBe(175)
  })

  it('moves a box that sticks out on the right back by the part outside plus the margin', () => {
    expect(shiftIntoView(250, 506, 400)).toBe(-114)
  })

  it('leaves a box that fits where it is', () => {
    expect(shiftIntoView(20, 276, 400)).toBe(0)
    expect(shiftIntoView(8, 392, 400)).toBe(0)
  })

  it('puts a box wider than the screen at the left margin', () => {
    expect(shiftIntoView(-50, 450, 400)).toBe(58)
  })
})

/** jsdom has no layout: the box lies where the test says, plus the move made so far, and is never wider than its max-width. */
function menuAt(left: number, width: number, screen: number): HTMLElement {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: screen })
  const menu = document.createElement('div')
  menu.getBoundingClientRect = () => {
    const size = Math.min(width, parseFloat(menu.style.maxWidth) || Infinity)
    const at = left + (parseFloat(menu.style.translate) || 0)
    return { left: at, right: at + size, width: size, top: 0, bottom: 0, height: 0, x: at, y: 0, toJSON: () => ({}) } as DOMRect
  }
  return menu
}

describe('keepInView', () => {
  afterEach(() => Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1024 }))

  it('pulls a menu that sticks out on the left into view', () => {
    const menu = menuAt(-167, 256, 400)
    keepInView(menu)
    expect(menu.style.translate).toBe('175px 0')
  })

  it('pulls a menu that sticks out on the right into view', () => {
    const menu = menuAt(250, 256, 400)
    keepInView(menu)
    expect(menu.style.translate).toBe('-114px 0')
  })

  it('leaves a menu that fits alone', () => {
    const menu = menuAt(20, 256, 400)
    keepInView(menu)
    expect(menu.style.translate).toBe('')
  })

  it('cuts a menu wider than the screen to the screen', () => {
    const menu = menuAt(-20, 400, 300)
    keepInView(menu)
    expect(menu.style.maxWidth).toBe('284px')
    expect(menu.style.translate).toBe('28px 0')
  })
})
