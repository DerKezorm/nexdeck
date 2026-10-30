import { create } from 'zustand'

import { ApiError, get, patch, post } from '../api/client'
import type { SetupStatus, User } from '../api/types'
import { setLanguage } from '../i18n'
import { followTheme, type ThemeChoice, type ThemePlan } from '../lib/themeMode'

/**
 * What the first half of a sign-in ends in. An account with a second factor
 * gets a ticket instead of a session: the password was right, and that is all
 * the ticket says.
 */
export type LoginOutcome = { done: true } | { done: false; ticket: string; recovery: boolean }

interface AuthState {
  user: User | null
  status: SetupStatus | null
  loading: boolean
  refresh: () => Promise<void>
  login: (username: string, password: string) => Promise<LoginOutcome>
  secondStep: (ticket: string, code: string, recoveryCode?: string) => Promise<void>
  /** Signed in on the home network without a password; `again` after signing out on purpose. */
  homeSignIn: (again?: boolean) => Promise<void>
  logout: () => Promise<void>
  update: (fields: Partial<Pick<User, 'display_name' | 'email' | 'locale' | 'language_pair' | 'theme' | 'light_from' | 'dark_from' | 'tilt' | 'skin' | 'start_board_id' | 'seen_version'>>) => Promise<void>
  /** Take an account the server just handed back, after an upload for instance. */
  setUser: (user: User) => void
}

/** Empty everything this browser holds about the person who just left.
 *
 * A full load, not a route change. The zustand stores, the react-query cache
 * and every open live connection live in this page; nothing short of loading
 * it again clears all three, and half-clearing them is how the next person to
 * sign in gets a glimpse of the last one's boards.
 */
export function forgetEverything(): void {
  window.location.assign('/login')
}

export const useAuth = create<AuthState>((set, getState) => ({
  user: null,
  status: null,
  loading: true,
  refresh: async () => {
    try {
      const status = await get<SetupStatus>('/setup/status')
      set({ status })
      if (status.needs_setup) {
        set({ user: null, loading: false })
        return
      }
      try {
        const user = await get<User>('/auth/me')
        set({ user, loading: false })
        await setLanguage(user.locale)
        applyTheme(user)
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) set({ user: null, loading: false })
        else set({ loading: false })
      }
    } catch {
      set({ loading: false })
    }
  },
  login: async (username, password) => {
    try {
      const user = await post<User>('/auth/login', { username, password })
      set({ user })
      await setLanguage(user.locale)
      applyTheme(user)
      return { done: true }
    } catch (failure) {
      if (failure instanceof ApiError && failure.code === 'second_step') {
        return { done: false, ticket: String(failure.detail.ticket ?? ''), recovery: Boolean(failure.detail.recovery) }
      }
      throw failure
    }
  },
  secondStep: async (ticket, code, recoveryCode = '') => {
    const user = await post<User>('/auth/login/second-step', { ticket, code, recovery_code: recoveryCode })
    set({ user })
    await setLanguage(user.locale)
    applyTheme(user)
  },
  homeSignIn: async (again = false) => {
    const user = await post<User>('/auth/home', { again })
    set({ user })
    await setLanguage(user.locale)
    applyTheme(user)
  },
  logout: async () => {
    await post('/auth/logout')
    set({ user: null })
    // ⚠️ Setting the user to null is not signing out. The boards, the notices
    // and everything react-query holds stay in memory, and the next person to
    // sign in at the same browser sees them for as long as it takes the new
    // data to arrive. Nothing here survives a full page load, so the cheapest
    // honest answer is to do one.
    forgetEverything()
  },
  update: async (fields) => {
    const user = await patch<User>('/auth/me', fields)
    set({ user })
    // The server's answer, not the request: a new pair can move the language too.
    if (fields.locale || fields.language_pair) await setLanguage(user.locale)
    if (fields.theme || fields.light_from || fields.dark_from) applyTheme(user)
    void getState
  },
  setUser: (user) => set({ user }),
}))

/** Light or dark for the person signed in: a fixed one, the system's, or by the clock, followed live. */
export function applyTheme(theme: ThemeChoice | ThemePlan) {
  followTheme(typeof theme === 'string' ? { theme } : theme)
}

export function currentTheme(): 'dark' | 'light' {
  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'
}
