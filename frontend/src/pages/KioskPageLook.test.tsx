/**
 * A wall display is painted with the look of the installation.
 *
 * ⚠️ The shell paints the look only for someone signed in, and a display has
 * no session: every kiosk stood in nexdeck's own cyan, whatever theme, accent
 * or style sheet the operator had chosen. Found on 01.10.2026.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { KioskPage } from './KioskPage'

const asked = vi.hoisted(() => [] as string[])
vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  get: vi.fn(async (path: string) => {
    asked.push(path)
    if (path === '/kiosk') {
      return {
        id: 1, slug: 'hall', name: 'Hall', icon: '', owner_id: 1, background: { kind: 'bundled', value: 'aurora' }, settings: {},
        provisioned: false, permission: 'view', live: {},
        pages: [{ id: 1, name: 'One', slug: 'one', icon: '', position: 0, layouts: { lg: [], md: [], sm: [] }, widgets: [] }],
        kiosk: { cycle_seconds: 0, dim_from: '', dim_to: '', allow_actions: false, name: 'Hall' },
      }
    }
    if (path === '/settings/appearance') return { preset: 'cyan', accent: '', css: '.card { outline: 1px solid red; }', colour: '#22d3ee', card_style: 'neon', radius: 6, gap: 20 }
    return {}
  }),
  post: vi.fn(async () => ({})),
  mediaUrl: () => '',
  openKioskSession: vi.fn(async () => undefined),
}))
vi.mock('../hooks/useStream', () => ({ useStream: () => undefined }))

afterEach(() => {
  delete document.documentElement.dataset.cards
  document.documentElement.removeAttribute('style')
  document.getElementById('nexdeck-appearance')?.remove()
})

describe('the look on a wall display', () => {
  it('reads the look once the board is there and paints it on', async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={['/k']}>
          <Routes>
            <Route path="/k/:token?" element={<KioskPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    await waitFor(() => expect(document.documentElement.dataset.cards).toBe('neon'))
    expect(asked).toContain('/settings/appearance')
    expect(document.documentElement.style.getPropertyValue('--nd-radius')).toBe('6px')
    expect(document.getElementById('nexdeck-appearance')?.textContent).toContain('outline: 1px solid red')
  })
})
