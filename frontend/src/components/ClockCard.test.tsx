/**
 * The clock, with digits or with hands.
 *
 * ⚠️ The hands are read out of the formatted time, not off the Date. A Date
 * carries the browser's zone, so a clock set to another zone would draw one
 * time and print another underneath it, and only somebody in a third zone
 * would ever notice.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ClockCard, handsFor } from './renderers'
import type { WidgetData, WidgetView } from '../lib/types'

const WIDGET = { id: 1, title: 'Clock', renderer: 'clock' } as unknown as WidgetView

function show(meta: Record<string, unknown>) {
  return render(<ClockCard widget={WIDGET} data={{ meta } as unknown as WidgetData} />)
}

describe('handsFor', () => {
  const at = (iso: string) => new Date(iso)

  it('puts the hands where the time is', () => {
    // 03:00 UTC: the hour hand a quarter round, the minute hand at the top.
    expect(handsFor(at('2026-09-07T03:00:00Z'), 'UTC')).toEqual({ hour: 90, minute: 0, second: 0 })
    // 06:30: the hour hand is past the six, not on it.
    expect(handsFor(at('2026-09-07T06:30:00Z'), 'UTC')).toEqual({ hour: 195, minute: 180, second: 0 })
  })

  it('treats noon and midnight as the top of the dial', () => {
    expect(handsFor(at('2026-09-07T12:00:00Z'), 'UTC').hour).toBe(0)
    expect(handsFor(at('2026-09-07T00:00:00Z'), 'UTC').hour).toBe(0)
  })

  it('follows the zone the clock was set to, not the browser', () => {
    const utc = handsFor(at('2026-09-07T12:00:00Z'), 'UTC')
    const tokyo = handsFor(at('2026-09-07T12:00:00Z'), 'Asia/Tokyo')
    expect(tokyo.hour).not.toBe(utc.hour)
    // 21:00 in Tokyo is nine on a twelve-hour dial: three quarters round.
    expect(tokyo.hour).toBe(270)
  })

  it('falls back to the browser rather than throwing on a zone nobody has' , () => {
    expect(() => handsFor(at('2026-09-07T12:00:00Z'), 'Mars/Olympus')).not.toThrow()
  })
})

describe('ClockCard', () => {
  it('shows digits by default', () => {
    show({})
    expect(screen.queryByRole('img')).toBeNull()
  })

  it('draws a dial when it was asked for one', () => {
    show({ face: 'hands' })
    expect(screen.getByRole('img')).toBeInTheDocument()
  })

  it('takes the colour it was given, and only then', () => {
    const { container, rerender } = render(<ClockCard widget={WIDGET} data={{ meta: {} } as unknown as WidgetData} />)
    const digits = container.querySelector('.num') as HTMLElement
    // ⚠️ Nothing set, not a colour that happens to match the theme. A colour
    // written out here would freeze the digits against a board that changes.
    expect(digits.style.color).toBe('')

    rerender(<ClockCard widget={WIDGET} data={{ meta: { colour: '#ff8800' } } as unknown as WidgetData} />)
    expect((container.querySelector('.num') as HTMLElement).style.color).toBe('rgb(255, 136, 0)')
  })

  it('keeps the date and the subtitle on the dial too', () => {
    show({ face: 'hands', label: 'Kitchen' })
    expect(screen.getByText('Kitchen')).toBeInTheDocument()
  })
})
