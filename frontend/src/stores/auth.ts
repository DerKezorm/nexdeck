import { create } from 'zustand'

import { ApiError, get, patch, post } from '../api/client'
import type { SetupStatus, User } from '../api/types'
import { setLanguage } from '../i18n'

interface AuthState {
  user: User | null
  status: SetupStatus | null
  loading: boolean
  refresh: () => Promise<void>
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  update: (fields: Partial<Pick<User, 'display_name' | 'locale' | 'theme' | 'start_board_id' | 'seen_version'>>) => Promise<void>
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
        applyTheme(user.theme)
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) set({ user: null, loading: false })
        else set({ loading: false })
      }
    } catch {
      set({ loading: false })
    }
  },
  login: async (username, password) => {
    const user = await post<User>('/auth/login', { username, password })
    set({ user })
    await setLanguage(user.locale)
    applyTheme(user.theme)
  },
  logout: async () => {
    await post('/auth/logout')
    set({ user: null })
  },
  update: async (fields) => {
    const user = await patch<User>('/auth/me', fields)
    set({ user })
    if (fields.locale) await setLanguage(fields.locale)
    if (fields.theme) applyTheme(fields.theme)
    void getState
  },
}))

export function applyTheme(theme: 'dark' | 'light' | 'system') {
  const resolved = theme === 'system' ? (window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark') : theme
  document.documentElement.dataset.theme = resolved
  try {
    localStorage.setItem('nexdeck.theme', theme)
  } catch {
    // ignore
  }
}

export function currentTheme(): 'dark' | 'light' {
  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'
}
