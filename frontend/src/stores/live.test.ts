/**
 * Two roads carry the same card, and they do not arrive in order.
 *
 * ⚠️ The stream pushes each answer as it is made; every board request brings a
 * snapshot of the whole board along. Measured on 09.09.2026 in a real browser:
 * saving a card sent the new answer over the stream 120 ms later, and a board
 * request that had started 40 ms **before** the save answered 20 ms after
 * that, carrying the state from before it. The older snapshot won.
 *
 * On a card the server reads every fifteen seconds nobody notices. On a clock,
 * whose next fetch is an hour away, the old settings stay until the page is
 * reloaded, which is exactly how this was reported: "I change something, it
 * shows, it jumps back, and only F5 gives me the result."
 */
import { beforeEach, describe, expect, it } from 'vitest'

import { useLive } from './live'
import type { WidgetData } from '../lib/types'

const answer = (at: number, seconds: boolean): WidgetData =>
  ({ status: 'ok', meta: { seconds }, updated_at: at }) as unknown as WidgetData

describe('live store', () => {
  beforeEach(() => {
    useLive.setState({ data: {}, series: {}, health: {}, logs: {} })
  })

  it('takes the newer answer whichever road it came by', () => {
    useLive.getState().applyWidget(1, answer(1000, true))
    useLive.getState().setSnapshot({ 1: answer(2000, false) })
    expect(useLive.getState().data[1].updated_at).toBe(2000)
  })

  it('keeps the newer answer when an older snapshot lands after it', () => {
    useLive.getState().applyWidget(1, answer(2000, true))
    useLive.getState().setSnapshot({ 1: answer(1000, false) })
    expect(useLive.getState().data[1].meta?.seconds, 'the older board snapshot overwrote the fresh answer').toBe(true)
  })

  it('keeps the newer answer when an older stream event lands after it', () => {
    useLive.getState().setSnapshot({ 1: answer(2000, true) })
    useLive.getState().applyWidget(1, answer(1000, false))
    expect(useLive.getState().data[1].meta?.seconds).toBe(true)
  })

  it('lets the rest of a snapshot through while one card is held back', () => {
    useLive.getState().applyWidget(1, answer(2000, true))
    useLive.getState().setSnapshot({ 1: answer(1000, false), 2: answer(1000, false) })
    expect(useLive.getState().data[1].updated_at).toBe(2000)
    expect(useLive.getState().data[2].updated_at).toBe(1000)
  })

  it('takes an answer that carries no time of its own', () => {
    // ⚠️ An error card has no fetch time and must still be able to replace a
    // good one, or a card that broke would go on showing yesterday's numbers.
    useLive.getState().applyWidget(1, answer(2000, true))
    useLive.getState().applyWidget(1, { status: 'bad', error: 'gone' } as unknown as WidgetData)
    expect(useLive.getState().data[1].error).toBe('gone')
  })

  it('does not record history twice for an answer it turned away', () => {
    useLive.getState().applyWidget(1, { status: 'ok', metrics: { q: 5 }, updated_at: 2000 } as unknown as WidgetData)
    useLive.getState().applyWidget(1, { status: 'ok', metrics: { q: 9 }, updated_at: 1000 } as unknown as WidgetData)
    expect(useLive.getState().series[1].q).toEqual([5])
  })
})
