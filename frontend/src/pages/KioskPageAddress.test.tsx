/**
 * A kiosk link's token leaves the address as soon as the display is let in.
 *
 * ⚠️ The page read the token from /k/nk_... and left it there: in the history
 * of the display's browser, and handed in again from the address every six
 * hours. Its own comment said the token "never appears in an address again".
 * An attempt on 07.09.2026 was taken back because /k without a token was not
 * routed, so a display would have been dead after its first reload. The token
 * now waits on the display itself, and the address is /k. Found on 12.09.2026.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { useEffect } from 'react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { KioskPage } from './KioskPage'

const calls = vi.hoisted(() => ({ opened: [] as string[] }))
vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  // The board never arrives: the address is all this test is about.
  get: vi.fn(() => new Promise(() => undefined)),
  post: vi.fn(async () => ({})),
  mediaUrl: () => '',
  openKioskSession: vi.fn(async (token: string) => {
    calls.opened.push(token)
  }),
}))

function memoryStorage(): Storage {
  const values = new Map<string, string>()
  return {
    get length() {
      return values.size
    },
    clear: () => values.clear(),
    getItem: (key: string) => values.get(key) ?? null,
    key: (index: number) => [...values.keys()][index] ?? null,
    removeItem: (key: string) => void values.delete(key),
    setItem: (key: string, value: string) => void values.set(key, String(value)),
  }
}

const seen = { path: '' }
function Where() {
  const { pathname } = useLocation()
  useEffect(() => {
    seen.path = pathname
  }, [pathname])
  return null
}

function show(address: string) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[address]}>
        <Routes>
          <Route
            path="/k/:token?"
            element={
              <>
                <KioskPage />
                <Where />
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('the kiosk address', () => {
  beforeEach(() => {
    calls.opened.length = 0
    seen.path = ''
    vi.stubGlobal('localStorage', memoryStorage())
  })

  it('takes the token out of the address once it is handed in', async () => {
    show('/k/nk_example-token')
    await waitFor(() => expect(seen.path).toBe('/k'))
    expect(calls.opened).toContain('nk_example-token')
    expect(localStorage.getItem('nexdeck.kiosk.token')).toBe('nk_example-token')
  })

  it('comes back in with the kept token after a reload', async () => {
    localStorage.setItem('nexdeck.kiosk.token', 'nk_kept-token')
    show('/k')
    await waitFor(() => expect(calls.opened).toEqual(['nk_kept-token']))
  })

  it('is routed without a token, or a reloaded display is dead', () => {
    const app = readFileSync(join(process.cwd(), 'src/App.tsx'), 'utf8')
    expect(app).toContain('<Route path="/k/:token?" element={<KioskPage />} />')
  })
})
