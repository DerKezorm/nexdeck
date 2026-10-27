/**
 * Light or dark, and when.
 *
 * Four answers: always dark, always light, as the system says, or by the
 * clock (light from one time, dark from another, for the tablet on the wall
 * that should not light up the hall at night). The last two change while the
 * page is open, so choosing one is not painting once but following: the
 * system's switch is heard the moment it flips, the clock is looked at twice
 * a minute and whenever the page comes back into view.
 *
 * ⚠️ `system` used to be read once, when the page loaded. A Mac that turned
 * dark at sunset left nexdeck light until somebody pressed F5.
 */
import { useSyncExternalStore } from 'react'

export type ThemeChoice = 'dark' | 'light' | 'system' | 'schedule'
export type Brightness = 'dark' | 'light'
export interface ThemePlan {
  theme: ThemeChoice
  /** With `schedule`: when light begins and when dark does, `HH:MM`. */
  light_from?: string
  dark_from?: string
}

export const LIGHT_FROM = '07:00'
export const DARK_FROM = '20:00'
const CLOCK = /^([01]\d|2[0-3]):([0-5]\d)$/
/** Often enough that nobody waits for it, rarely enough to cost nothing on a wall that runs for weeks. */
const LOOK_EVERY_MS = 30_000
const KEPT = 'nexdeck.theme'
const KEPT_TIMES = 'nexdeck.theme.times'

/** Minutes after midnight of a `HH:MM`, or the fallback for anything else. */
function minutes(clock: string | undefined, fallback: string): number {
  const read = CLOCK.exec(clock ?? '') ?? CLOCK.exec(fallback)!
  return Number(read[1]) * 60 + Number(read[2])
}

/** Whether the system asks for light. A browser without the question gets dark, as nexdeck always was. */
export function systemLight(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-color-scheme: light)').matches
}

/** The brightness a plan means at a moment. */
export function resolveTheme(plan: ThemePlan, now: Date = new Date(), light: boolean = systemLight()): Brightness {
  if (plan.theme === 'light' || plan.theme === 'dark') return plan.theme
  if (plan.theme === 'system') return light ? 'light' : 'dark'
  const start = minutes(plan.light_from, LIGHT_FROM)
  const end = minutes(plan.dark_from, DARK_FROM)
  const at = now.getHours() * 60 + now.getMinutes()
  // Light may also run across midnight, for whoever works nights.
  const lit = start < end ? at >= start && at < end : at >= start || at < end
  return lit ? 'light' : 'dark'
}

/** `?theme=light` in the address wins for this page load (screenshots, displays). */
function forcedTheme(): Brightness | null {
  const forced = (globalThis as { __NEXDECK_FORCED_THEME__?: string }).__NEXDECK_FORCED_THEME__
  return forced === 'light' || forced === 'dark' ? forced : null
}

function paint(brightness: Brightness): void {
  const root = document.documentElement
  if (root.dataset.theme !== brightness) root.dataset.theme = brightness
}

/** The plan this browser followed last, read before anything else is drawn so the page does not flash. */
export function keptPlan(): ThemePlan {
  try {
    const theme = localStorage.getItem(KEPT)
    const [light_from, dark_from] = (localStorage.getItem(KEPT_TIMES) ?? '').split('-')
    if (theme === 'light' || theme === 'system' || theme === 'schedule') return { theme, light_from, dark_from }
  } catch {
    // A browser that keeps nothing starts dark.
  }
  return { theme: 'dark' }
}

function keep(plan: ThemePlan): void {
  try {
    localStorage.setItem(KEPT, plan.theme)
    if (plan.theme === 'schedule') localStorage.setItem(KEPT_TIMES, `${plan.light_from ?? LIGHT_FROM}-${plan.dark_from ?? DARK_FROM}`)
  } catch {
    // ignore
  }
}

let stopFollowing: (() => void) | null = null

/**
 * Paint a plan and keep following it until the next one. A wall display
 * passes `remember: false`: what it shows is the link's choice, not the
 * browser's, and the next person to sign in at that browser should not
 * inherit it.
 */
export function followTheme(plan: ThemePlan, { remember = true }: { remember?: boolean } = {}): void {
  stopFollowing?.()
  stopFollowing = null
  const forced = forcedTheme()
  if (forced) {
    paint(forced)
    return
  }
  if (remember) keep(plan)
  const look = () => paint(resolveTheme(plan))
  look()
  if (plan.theme === 'system' && typeof window.matchMedia === 'function') {
    const query = window.matchMedia('(prefers-color-scheme: light)')
    const heard = (event: MediaQueryListEvent) => paint(event.matches ? 'light' : 'dark')
    // Safari before 14 knows only the old pair of names.
    if (typeof query.addEventListener === 'function') query.addEventListener('change', heard)
    else query.addListener(heard)
    stopFollowing = () => (typeof query.removeEventListener === 'function' ? query.removeEventListener('change', heard) : query.removeListener(heard))
  } else if (plan.theme === 'schedule') {
    // ⚠️ A timer alone is not enough: a tablet asleep does not run it, and
    // wakes at seven with the night still on the screen. Coming back into
    // view looks at the clock as well.
    const timer = window.setInterval(look, LOOK_EVERY_MS)
    document.addEventListener('visibilitychange', look)
    stopFollowing = () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', look)
    }
  }
}

function listen(changed: () => void): () => void {
  const watcher = new MutationObserver(changed)
  watcher.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  return () => watcher.disconnect()
}

/** The brightness on screen, for a control that shows it: it changes by itself now. */
export function useShownTheme(): Brightness {
  return useSyncExternalStore(listen, () => (document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'), () => 'dark')
}
