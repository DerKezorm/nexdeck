import { act, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { between, Rolled, ROLL_MS } from './Rolled'

describe('the way between two readings', () => {
  it('starts at the old value and ends at the new one', () => {
    expect(between(10, 20, 0)).toBe(10)
    expect(between(10, 20, 1)).toBe(20)
  })

  it('is eased out: more than half way at half the time', () => {
    expect(between(0, 100, 0.5)).toBeGreaterThan(80)
  })

  it('keeps whole numbers whole on the way', () => {
    for (const share of [0.1, 0.3, 0.6, 0.9]) expect(Number.isInteger(between(5, 7, share))).toBe(true)
    expect(Number.isInteger(between(5, 7.5, 0.3))).toBe(false)
  })
})

describe('a rolling number', () => {
  let frames: FrameRequestCallback[] = []
  let clock = 0
  const tick = (ms: number) =>
    act(() => {
      clock += ms
      const due = frames
      frames = []
      for (const callback of due) callback(clock)
    })

  beforeEach(() => {
    frames = []
    clock = 0
    vi.spyOn(performance, 'now').mockImplementation(() => clock)
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => frames.push(callback))
    vi.stubGlobal('cancelAnimationFrame', () => undefined)
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query }))
  })
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('shows the first reading as it is', () => {
    const { container } = render(<Rolled value={45} unit="%" />)
    expect(container.textContent).toBe('45%')
  })

  it('counts up to a new reading instead of jumping to it', () => {
    const { container, rerender } = render(<Rolled value={100} />)
    rerender(<Rolled value={200} />)
    expect(container.textContent).toBe('100')
    tick(ROLL_MS / 3)
    const midway = Number(container.textContent)
    expect(midway).toBeGreaterThan(100)
    expect(midway).toBeLessThan(200)
    tick(ROLL_MS)
    expect(container.textContent).toBe('200')
  })

  it('changes at once when less motion is asked for', () => {
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: true, media: query }))
    const { container, rerender } = render(<Rolled value={100} />)
    rerender(<Rolled value={200} />)
    expect(container.textContent).toBe('200')
  })

  it('changes a word at once', () => {
    const { container, rerender } = render(<Rolled value="idle" />)
    rerender(<Rolled value="busy" />)
    expect(container.textContent).toBe('busy')
  })
})
