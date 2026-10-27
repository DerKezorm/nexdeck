/**
 * A wall display is as light as its link says: dark as it always was, or
 * light, the system's, or by the clock, and it turns without a reload.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { followTheme } from '../lib/themeMode'
import { KioskPage } from './KioskPage'

const link = vi.hoisted(() => ({ kiosk: {} as Record<string, unknown> }))
vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  get: vi.fn(async (path: string) => {
    if (path === '/kiosk') {
      return {
        id: 1, slug: 'hall', name: 'Hall', icon: '', owner_id: 1, background: { kind: 'bundled', value: 'aurora' }, settings: {},
        provisioned: false, permission: 'view', live: {},
        pages: [{ id: 1, name: 'One', slug: 'one', icon: '', position: 0, layouts: { lg: [], md: [], sm: [] }, widgets: [] }],
        kiosk: { cycle_seconds: 0, dim_from: '', dim_to: '', allow_actions: false, name: 'Hall', ...link.kiosk },
      }
    }
    return {}
  }),
  post: vi.fn(async () => ({})),
  mediaUrl: () => '',
  openKioskSession: vi.fn(async () => undefined),
}))
vi.mock('../hooks/useStream', () => ({ useStream: () => undefined }))

function show() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/k']}>
        <Routes>
          <Route path="/k/:token?" element={<KioskPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  followTheme({ theme: 'dark' }, { remember: false })
  vi.useRealTimers()
  localStorage.clear()
})

describe('light and dark on a wall display', () => {
  it('stays dark for a link made before it could choose, whatever the browser kept', async () => {
    localStorage.setItem('nexdeck.theme', 'light')
    document.documentElement.dataset.theme = 'light'
    link.kiosk = {}
    show()
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe('dark'))
  })

  it('goes by the clock, and turns at the time without a reload', async () => {
    vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] })
    vi.setSystemTime(new Date('2026-10-27T19:59:30'))
    link.kiosk = { theme: 'schedule', light_from: '07:00', dark_from: '20:00' }
    show()
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe('light'))
    vi.advanceTimersByTime(60_000)
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(localStorage.getItem('nexdeck.theme')).toBeNull()
  })
})
