/**
 * Light or dark, followed live: the system's switch is heard at once, the
 * clock turns the page twice a day, and neither needs a reload.
 */
import { act, renderHook } from '@testing-library/react'

import { followTheme, keptPlan, resolveTheme, useShownTheme } from './themeMode'

/** A stand-in for the browser's question about the system, with a switch the test can flip. */
function systemQuestion(light: boolean) {
  const listeners = new Set<(event: MediaQueryListEvent) => void>()
  const query = {
    matches: light,
    addEventListener: (_name: string, listener: (event: MediaQueryListEvent) => void) => listeners.add(listener),
    removeEventListener: (_name: string, listener: (event: MediaQueryListEvent) => void) => listeners.delete(listener),
  }
  window.matchMedia = vi.fn(() => query) as unknown as typeof window.matchMedia
  return {
    flip(next: boolean) {
      query.matches = next
      for (const listener of listeners) listener({ matches: next } as MediaQueryListEvent)
    },
    listening: () => listeners.size,
  }
}

const at = (clock: string) => new Date(`2026-10-27T${clock}:00`)
const shown = () => document.documentElement.dataset.theme

afterEach(() => {
  followTheme({ theme: 'dark' }, { remember: false })
  vi.useRealTimers()
  localStorage.clear()
  delete (globalThis as { __NEXDECK_FORCED_THEME__?: string }).__NEXDECK_FORCED_THEME__
})

describe('resolveTheme', () => {
  it('turns light at the first time and dark at the second', () => {
    const plan = { theme: 'schedule' as const, light_from: '07:00', dark_from: '20:00' }
    expect(resolveTheme(plan, at('06:59'))).toBe('dark')
    expect(resolveTheme(plan, at('07:00'))).toBe('light')
    expect(resolveTheme(plan, at('19:59'))).toBe('light')
    expect(resolveTheme(plan, at('20:00'))).toBe('dark')
  })

  it('lets light run across midnight for whoever works nights', () => {
    const plan = { theme: 'schedule' as const, light_from: '22:00', dark_from: '06:00' }
    expect(resolveTheme(plan, at('23:30'))).toBe('light')
    expect(resolveTheme(plan, at('03:00'))).toBe('light')
    expect(resolveTheme(plan, at('12:00'))).toBe('dark')
  })

  it('falls back to seven and eight for times that are no times', () => {
    const plan = { theme: 'schedule' as const, light_from: 'soon', dark_from: '' }
    expect(resolveTheme(plan, at('06:00'))).toBe('dark')
    expect(resolveTheme(plan, at('12:00'))).toBe('light')
  })

  it('asks the system only for system', () => {
    expect(resolveTheme({ theme: 'system' }, at('12:00'), true)).toBe('light')
    expect(resolveTheme({ theme: 'system' }, at('12:00'), false)).toBe('dark')
    expect(resolveTheme({ theme: 'dark' }, at('12:00'), true)).toBe('dark')
  })
})

describe('followTheme', () => {
  it('follows a switch of the system without a reload', () => {
    const system = systemQuestion(false)
    followTheme({ theme: 'system' })
    expect(shown()).toBe('dark')
    system.flip(true)
    expect(shown()).toBe('light')
    system.flip(false)
    expect(shown()).toBe('dark')
  })

  it('stops listening to the system once something else is chosen', () => {
    const system = systemQuestion(false)
    followTheme({ theme: 'system' })
    expect(system.listening()).toBe(1)
    followTheme({ theme: 'dark' })
    expect(system.listening()).toBe(0)
    system.flip(true)
    expect(shown()).toBe('dark')
  })

  it('turns by the clock while the page stays open', () => {
    vi.useFakeTimers()
    vi.setSystemTime(at('19:59'))
    followTheme({ theme: 'schedule', light_from: '07:00', dark_from: '20:00' })
    expect(shown()).toBe('light')
    vi.advanceTimersByTime(60_000)
    expect(shown()).toBe('dark')
  })

  it('looks at the clock when a sleeping screen wakes', () => {
    vi.useFakeTimers()
    vi.setSystemTime(at('06:00'))
    followTheme({ theme: 'schedule', light_from: '07:00', dark_from: '20:00' })
    expect(shown()).toBe('dark')
    // Asleep: the clock moves, no timer ran.
    vi.setSystemTime(at('07:30'))
    document.dispatchEvent(new Event('visibilitychange'))
    expect(shown()).toBe('light')
  })

  it('keeps the plan for the next load, unless it is a display’s', () => {
    followTheme({ theme: 'schedule', light_from: '06:30', dark_from: '21:00' })
    expect(keptPlan()).toEqual({ theme: 'schedule', light_from: '06:30', dark_from: '21:00' })
    followTheme({ theme: 'light' }, { remember: false })
    expect(keptPlan().theme).toBe('schedule')
  })

  it('gives way to a brightness forced in the address', () => {
    ;(globalThis as { __NEXDECK_FORCED_THEME__?: string }).__NEXDECK_FORCED_THEME__ = 'light'
    followTheme({ theme: 'dark' })
    expect(shown()).toBe('light')
  })
})

it('tells a control when the brightness changes by itself', () => {
  const system = systemQuestion(false)
  followTheme({ theme: 'system' })
  const { result } = renderHook(() => useShownTheme())
  expect(result.current).toBe('dark')
  act(() => system.flip(true))
  return vi.waitFor(() => expect(result.current).toBe('light'))
})
