/**
 * The countdown and the timer. Both count in the browser; the clock is set
 * here, and every date is in the browser's own zone, as on the wall.
 */
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { WidgetData, WidgetView } from '../lib/types'
import { clockText, CountdownCard, readCountdown, secondsLeft, targetOf, TimerCard, type CountdownMeta } from './TimeCards'

const meta = (more: Partial<CountdownMeta>): CountdownMeta => ({ event: '', date: '', time: '', yearly: false, show: 'auto', after: 'since', ...more })
const at = (year: number, month: number, day: number, hours = 0, minutes = 0, seconds = 0) => new Date(year, month - 1, day, hours, minutes, seconds)

describe('readCountdown', () => {
  it('counts the days to a date', () => {
    expect(readCountdown(meta({ date: '2026-11-06' }), at(2026, 10, 25, 9))).toEqual({ state: 'days', days: 12 })
  })

  it('says today all day long, and counts the days since afterwards', () => {
    const holiday = meta({ date: '2026-11-06' })
    expect(readCountdown(holiday, at(2026, 11, 6, 23, 59))).toEqual({ state: 'today' })
    expect(readCountdown(holiday, at(2026, 11, 10, 8))).toEqual({ state: 'since', days: 4 })
    expect(readCountdown({ ...holiday, after: 'here' }, at(2026, 11, 10, 8))).toEqual({ state: 'here' })
  })

  it('counts by the calendar across the night the clocks go forward', () => {
    // 29 March 2026 has 23 hours in Berlin; the test runs in whatever zone, and a date has no hours.
    expect(readCountdown(meta({ date: '2026-03-30' }), at(2026, 3, 29, 0, 30))).toEqual({ state: 'days', days: 1 })
  })

  // In November: no clock goes forward or back between these times in any zone that has summer time.
  it('shows hours and minutes in the last two days when a time is set', () => {
    const kickoff = meta({ date: '2026-11-25', time: '18:30' })
    expect(readCountdown(kickoff, at(2026, 11, 25, 15, 18))).toEqual({ state: 'clock', days: 0, hours: 3, minutes: 12, seconds: 0 })
    expect(readCountdown(kickoff, at(2026, 11, 20, 15))).toEqual({ state: 'days', days: 5 })
    expect(readCountdown({ ...kickoff, show: 'days' }, at(2026, 11, 25, 15))).toEqual({ state: 'today' })
    expect(readCountdown({ ...kickoff, show: 'all' }, at(2026, 11, 20, 15))).toEqual({ state: 'clock', days: 5, hours: 3, minutes: 30, seconds: 0 })
  })

  it('is here the moment the time has come, not a day later', () => {
    expect(readCountdown(meta({ date: '2026-11-25', time: '18:30' }), at(2026, 11, 25, 18, 30, 1))).toEqual({ state: 'here' })
  })

  it('counts to the next birthday once this one is over', () => {
    const birthday = meta({ date: '1990-12-09', yearly: true })
    expect(targetOf(birthday, at(2026, 10, 24))).toEqual(at(2026, 12, 9))
    expect(readCountdown(birthday, at(2026, 12, 9, 20))).toEqual({ state: 'today' })
    expect(targetOf(birthday, at(2026, 12, 10))).toEqual(at(2027, 12, 9))
  })

  it('keeps a birthday on 29 February on the 28th in other years', () => {
    expect(targetOf(meta({ date: '2000-02-29', yearly: true }), at(2026, 10, 24))).toEqual(at(2027, 2, 28))
    expect(targetOf(meta({ date: '2000-02-29', yearly: true }), at(2027, 3, 1))).toEqual(at(2028, 2, 29))
  })

  it('asks for a date it does not have', () => {
    expect(readCountdown(meta({ date: '' }), at(2026, 10, 24))).toEqual({ state: 'unset' })
  })
})

describe('CountdownCard', () => {
  afterEach(() => vi.useRealTimers())

  it('says how many days are left and until what', () => {
    vi.useFakeTimers({ now: at(2026, 10, 25, 9) })
    render(<CountdownCard widget={{ id: 1 } as WidgetView} data={{ status: 'ok', meta: { date: '2026-11-06', event: 'Holiday' } } as WidgetData} />)
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText('days')).toBeInTheDocument()
    expect(screen.getByText(/until Holiday/)).toBeInTheDocument()
  })

  it('counts from the options of the card before the server has answered', () => {
    vi.useFakeTimers({ now: at(2026, 10, 25, 9) })
    render(<CountdownCard widget={{ id: 1, options: { date: '2026-11-06' } } as unknown as WidgetView} data={undefined} />)
    expect(screen.getByText('12')).toBeInTheDocument()
  })

  it('says how long ago it was, the number large where the language puts it', () => {
    vi.useFakeTimers({ now: at(2026, 11, 10, 9) })
    const { container } = render(<CountdownCard widget={{ id: 1 } as WidgetView} data={{ status: 'ok', meta: { date: '2026-11-06', event: 'Moving day' } } as WidgetData} />)
    expect(container.querySelector('.nd-countdown-big')?.firstChild?.textContent).toBe('4')
    expect(screen.getByText('days ago')).toBeInTheDocument()
    expect(screen.getByText(/^Moving day/)).toBeInTheDocument()
  })
})

/** Node's own half-made localStorage hides jsdom's in this runner; a plain map stands in (as in player.test). */
function memoryStorage(): Storage {
  const items = new Map<string, string>()
  return {
    get length() {
      return items.size
    },
    clear: () => items.clear(),
    getItem: (key) => items.get(key) ?? null,
    key: (index) => [...items.keys()][index] ?? null,
    removeItem: (key) => void items.delete(key),
    setItem: (key, value) => void items.set(key, String(value)),
  }
}

/**
 * Time passing in quarter seconds, each its own act. Advanced in one act,
 * React draws the last state only, and a tone a second becomes one tone.
 */
function pass(milliseconds: number) {
  for (let done = 0; done < milliseconds; done += 250) act(() => vi.advanceTimersByTime(250))
}

describe('the timer', () => {
  const widget = { id: 7, title: 'Kitchen' } as WidgetView
  const data = (more: Record<string, unknown> = {}) => ({ status: 'ok', meta: { minutes: 10, presets: [3, 0.5], end: 'flash', ...more } }) as WidgetData

  beforeEach(() => {
    vi.stubGlobal('localStorage', memoryStorage())
    vi.useFakeTimers({ now: at(2026, 10, 24, 12) })
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('writes what is left as a clock, hours only once there are any', () => {
    expect(clockText(600)).toBe('10:00')
    expect(clockText(59)).toBe('00:59')
    expect(clockText(3725)).toBe('1:02:05')
  })

  it('rounds what is left up, as a kitchen timer does', () => {
    expect(secondsLeft({ total: 600, left: 600, endsAt: Date.now() + 599_400 }, Date.now())).toBe(600)
    expect(secondsLeft({ total: 600, left: 0, endsAt: Date.now() - 5000 }, Date.now())).toBe(0)
  })

  it('runs, pauses and goes on where it stood', () => {
    render(<TimerCard widget={widget} data={data()} />)
    expect(screen.getByRole('timer')).toHaveTextContent('10:00')
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    pass(65_000)
    expect(screen.getByRole('timer')).toHaveTextContent('08:55')
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
    pass(30_000)
    expect(screen.getByRole('timer')).toHaveTextContent('08:55')
    fireEvent.click(screen.getByRole('button', { name: 'Go on' }))
    pass(5_000)
    expect(screen.getByRole('timer')).toHaveTextContent('08:50')
  })

  it('keeps running in this browser across a reload', () => {
    const first = render(<TimerCard widget={widget} data={data()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    first.unmount()
    pass(120_000)
    render(<TimerCard widget={widget} data={data()} />)
    expect(screen.getByRole('timer')).toHaveTextContent('08:00')
  })

  it('flashes the card when done until somebody stops it', () => {
    const { container } = render(
      <div className="card">
        <TimerCard widget={widget} data={data({ minutes: 0.5 })} />
      </div>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    pass(31_000)
    expect(container.querySelector('.card')).toHaveClass('nd-ringing')
    expect(screen.getByText('Time is up')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
    expect(container.querySelector('.card')).not.toHaveClass('nd-ringing')
    expect(screen.getByRole('timer')).toHaveTextContent('00:30')
  })

  it('starts a quick pick at once', () => {
    render(<TimerCard widget={widget} data={data()} />)
    fireEvent.click(screen.getByRole('button', { name: '30 s' }))
    pass(10_000)
    expect(screen.getByRole('timer')).toHaveTextContent('00:20')
  })

  it('adds a minute, and snoozes a minute once it rang', () => {
    render(<TimerCard widget={widget} data={data({ minutes: 0.5 })} />)
    fireEvent.click(screen.getByRole('button', { name: 'One minute more' }))
    expect(screen.getByRole('timer')).toHaveTextContent('01:30')
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    pass(91_000)
    expect(screen.getByText('Time is up')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'One minute more' }))
    pass(1_000)
    expect(screen.getByRole('timer')).toHaveTextContent('00:59')
  })

  it('rings only when asked to, and stops ringing after a minute', () => {
    const tones: number[] = []
    class FakeAudio {
      currentTime = 0
      destination = {}
      resume() {
        return Promise.resolve()
      }
      createOscillator() {
        return { frequency: { value: 0 }, connect: () => undefined, start: () => tones.push(Date.now()), stop: () => undefined }
      }
      createGain() {
        return { gain: { value: 0 }, connect: () => undefined }
      }
    }
    vi.stubGlobal('AudioContext', FakeAudio)
    const quiet = render(<TimerCard widget={{ id: 8 } as WidgetView} data={data({ minutes: 0.5, end: 'flash' })} />)
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    pass(40_000)
    expect(tones).toHaveLength(0)
    quiet.unmount()
    render(<TimerCard widget={{ id: 9 } as WidgetView} data={data({ minutes: 0.5, end: 'sound' })} />)
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    pass(35_000)
    expect(tones.length).toBeGreaterThan(2)
    const sounded = tones.length
    pass(120_000)
    // A minute of ringing, one tone a second, and then quiet.
    expect(tones.length).toBeLessThanOrEqual(62)
    expect(tones.length).toBeGreaterThan(sounded)
  })
})
