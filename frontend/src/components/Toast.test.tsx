/**
 * A message on a board goes away by itself after five seconds, however often the board draws.
 *
 * ⚠️ The timer hung on the close handler, and the board passes a new one on
 * every render. Every card answer renders the board, so on a living board the
 * five seconds started again with each answer and the message stood until
 * somebody closed it by hand. The close button added on 07.09.2026 only gave
 * it a way out. Found again on 12.09.2026.
 */
import { act, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { Toast } from './ui'

describe('Toast', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('closes after five seconds while the page keeps drawing', () => {
    const closed = vi.fn()
    const { rerender } = render(<Toast onClose={() => closed()}>Saved</Toast>)
    for (let second = 1; second <= 6; second++) {
      act(() => {
        vi.advanceTimersByTime(1000)
      })
      // What a card answer does to the board: the same message, a new handler.
      rerender(<Toast onClose={() => closed()}>Saved</Toast>)
    }
    expect(closed).toHaveBeenCalledTimes(1)
  })

  it('gives a new message five seconds of its own', () => {
    const closed = vi.fn()
    const { rerender } = render(<Toast onClose={closed}>First</Toast>)
    act(() => {
      vi.advanceTimersByTime(4000)
    })
    rerender(<Toast onClose={closed}>Second</Toast>)
    act(() => {
      vi.advanceTimersByTime(4000)
    })
    expect(closed).not.toHaveBeenCalled()
    act(() => {
      vi.advanceTimersByTime(1000)
    })
    expect(closed).toHaveBeenCalledTimes(1)
  })
})
