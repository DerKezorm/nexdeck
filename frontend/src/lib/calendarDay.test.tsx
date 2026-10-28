/** A timed calendar entry sits on the viewer's own day and clock, wherever the viewer is (#56). */
import { render, screen } from '@testing-library/react'

import { DEMO_VIEWS } from '../demo/board'
import { renderWidget } from '../components/renderers'
import type { WidgetData, WidgetView } from './types'
import { onViewersDay, upcomingByDay } from './calendarDay'

const zone = process.env.TZ

/** Seven in the evening in Chicago on 28 October 2026, already the 29th in UTC, as Sonarr's airDateUtc. */
const SHOW = { date: '2026-10-29', at: '2026-10-29T00:00:00Z', title: 'Chicago Med', subtitle: 'S12E04' }

function inZone(name: string) {
  process.env.TZ = name
}

afterEach(() => {
  if (zone === undefined) delete process.env.TZ
  else process.env.TZ = zone
  vi.useRealTimers()
})

describe('the viewer’s day', () => {
  it('puts a show at seven in the evening in Chicago on that day, and on the next in Berlin', () => {
    inZone('America/Chicago')
    expect(onViewersDay(SHOW).date).toBe('2026-10-28')
    inZone('Europe/Berlin')
    expect(onViewersDay(SHOW).date).toBe('2026-10-29')
  })

  it('moves the clock of a timed appointment along with its day', () => {
    // 19:00 in Chicago, written by a server whose clock is UTC.
    const choir = { date: '2026-10-29', time: '00:00', at: '2026-10-28T19:00:00-05:00', title: 'Choir' }
    inZone('America/Chicago')
    expect(onViewersDay(choir)).toMatchObject({ date: '2026-10-28', time: '19:00' })
    inZone('Europe/Berlin')
    expect(onViewersDay(choir)).toMatchObject({ date: '2026-10-29', time: '01:00' })
  })

  it('leaves an entry without a moment on the day it came with, and gives it no time', () => {
    inZone('America/Chicago')
    const release = { date: '2026-10-29', title: 'Copper Sky' }
    expect(onViewersDay(release)).toBe(release)
    expect(onViewersDay(SHOW)).not.toHaveProperty('time')
  })

  it('lists from the viewer’s today on, by day and then by the clock', () => {
    inZone('Europe/Berlin')
    const now = new Date(2026, 9, 29, 0, 30)
    const entries = [
      { date: '2026-10-29', time: '18:00', title: 'Late' },
      { date: '2026-10-28', title: 'Yesterday here' },
      { date: '2026-10-29', time: '08:00', title: 'Early' },
      { date: '2026-10-29', title: 'All day' },
    ]
    expect(upcomingByDay(entries, now).map((entry) => entry.title)).toEqual(['All day', 'Early', 'Late'])
  })
})

describe('the calendar card', () => {
  const view = { ...DEMO_VIEWS[0], id: 56, renderer: 'calendar', kind: 'sonarr.calendar' } as WidgetView
  const data = { status: 'ok', items: [SHOW] } as unknown as WidgetData

  function dayOfTheShow() {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date(2026, 9, 28, 12, 0))
    const { container, unmount } = render(<>{renderWidget({ widget: view, data })}</>)
    const heading = container.querySelector('li > div')?.textContent
    unmount()
    return heading
  }

  it('lists the show under today in Chicago and under tomorrow in Berlin', () => {
    inZone('America/Chicago')
    expect(dayOfTheShow()).toBe('Today')
    inZone('Europe/Berlin')
    expect(dayOfTheShow()).toBe('Tomorrow')
  })

  it('draws the show on the 28th of the month in Chicago', async () => {
    inZone('America/Chicago')
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date(2026, 9, 28, 12, 0))
    const month = { ...data, meta: { view: 'month', range: { from: '2026-08-26', to: '2027-02-28' } } } as unknown as WidgetData
    render(<>{renderWidget({ widget: view, data: month })}</>)
    await screen.findByTestId('calendar-grid')
    const cell = (iso: string) => document.querySelector(`[data-testid="calendar-day"][data-day="${iso}"]`) as HTMLElement
    expect(cell('2026-10-28')).toHaveTextContent('Chicago Med')
    expect(cell('2026-10-29')).not.toHaveTextContent('Chicago Med')
  })
})
