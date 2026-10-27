/**
 * ``/go/<name>``, signed out: the server sends the browser to ``/login?next=/go/<name>``.
 *
 * After signing in it goes back there, and only there: a ``next`` that leads
 * off nexdeck is dropped, and the sign-in ends on the start board as before.
 * A sign-in at a provider comes back to ``/``; the start page then picks up
 * the way back. ``/?find=words`` opens the bar on the start board.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { keepReturn } from '../lib/returnPath'
import { useAuth } from '../stores/auth'
import { HomeRedirect } from './HomeRedirect'
import { LoginPage } from './LoginPage'

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  get: vi.fn(async (path: string) => {
    if (path === '/auth/home') return { available: false }
    if (path === '/boards') return [{ id: 1, slug: 'home', name: 'Home', in_menu: true, pages: [] }]
    throw new Error(`unexpected ${path}`)
  }),
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
  serverUrl: (path: string) => path,
}))
vi.mock('../i18n', async (importOriginal) => ({ ...(await importOriginal<typeof import('../i18n')>()), setLanguage: vi.fn(async () => undefined) }))

const ADMIN = { id: 1, username: 'admin', role: 'admin', start_board_id: 1 }

function Where() {
  const location = useLocation()
  return <p data-testid="where">{`${location.pathname}${location.search}`}</p>
}

function at(address: string, element: React.ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[address]}>
        <Routes>
          <Route path="/login" element={element} />
          <Route path="/" element={address.startsWith('/login') ? <Where /> : element} />
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('the way back after signing in', () => {
  const replace = vi.fn()
  beforeEach(() => {
    replace.mockClear()
    sessionStorage.clear()
    vi.stubGlobal('location', { ...window.location, origin: window.location.origin, replace })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('goes back to the short address once the browser is in', async () => {
    useAuth.setState({ user: ADMIN as never, loading: false, status: { needs_setup: false, providers: [] } as never })
    at('/login?next=%2Fgo%2Fplex', <LoginPage />)
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/go/plex'))
  })

  it('goes nowhere else', async () => {
    useAuth.setState({ user: ADMIN as never, loading: false, status: { needs_setup: false, providers: [] } as never })
    at('/login?next=%2F%2Fevil.example%2Fgo%2Fplex', <LoginPage />)
    expect(await screen.findByTestId('where')).toHaveTextContent(/^\/$/)
    expect(replace).not.toHaveBeenCalled()
  })

  it('is picked up on the start page after a provider sent the browser back there', async () => {
    useAuth.setState({ user: ADMIN as never, loading: false })
    keepReturn('/go/plex')
    at('/', <HomeRedirect />)
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/go/plex'))
  })

  it('carries the words of an unknown short name to the start board', async () => {
    useAuth.setState({ user: ADMIN as never, loading: false })
    at('/?find=two%20words', <HomeRedirect />)
    expect(await screen.findByTestId('where')).toHaveTextContent('/b/home?find=two+words')
    expect(replace).not.toHaveBeenCalled()
  })
})
