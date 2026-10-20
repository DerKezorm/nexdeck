/**
 * A wall display shows a home page with its lamps, and switches them only
 * when its token allows actions. Before, a display drew every page as a grid
 * of cards, and a home page has none: the wall stayed empty.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { KioskPage } from './KioskPage'

const state = vi.hoisted(() => ({ allow: false, posted: [] as { path: string; body: unknown }[] }))
vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  get: vi.fn(async (path: string) => {
    if (path === '/kiosk') {
      return {
        id: 1, slug: 'hall', name: 'Hall', icon: '', owner_id: 1, background: { kind: 'bundled', value: 'aurora' }, settings: {},
        provisioned: false, permission: state.allow ? 'act' : 'view', live: {},
        pages: [{ id: 7, name: 'Lights', slug: 'lights', icon: '', position: 0, kind: 'home', home: { integration_id: 3 }, layouts: { lg: [], md: [], sm: [] }, widgets: [] }],
        kiosk: { cycle_seconds: 0, dim_from: '', dim_to: '', allow_actions: state.allow, name: 'Hall' },
      }
    }
    if (path === '/pages/7/home') {
      return {
        version: 1,
        problem: null,
        layout: { integration_id: 3, elements: [{ id: 'hall', type: 'light', x: 16, y: 16, rid: 'r-hall', entity_id: 'light.hall', name: 'Hall light', style: 'round' }] },
        lights: {
          hall: { rid: 'r-hall', entity_id: 'light.hall', name: 'Hall light', area: 'Hall', device: '', group: false, on: false, unavailable: false, pct: null, rgb: null, kelvin: null, dims: true, temperature: false, colour: false, missing: false },
        },
      }
    }
    return {}
  }),
  post: vi.fn(async (path: string, body: unknown) => {
    state.posted.push({ path, body })
    return { ok: true, confirmed: true, light: { rid: 'r-hall', entity_id: 'light.hall', name: 'Hall light', on: true, pct: 100, missing: false } }
  }),
  put: vi.fn(async () => ({})),
  mediaUrl: () => '',
  openKioskSession: vi.fn(async () => undefined),
}))
vi.mock('../hooks/useStream', () => ({ useStream: () => undefined }))

function wall() {
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

describe('a home page on a wall display', () => {
  it('shows its lamps in their style and switches one when the display may act', async () => {
    state.allow = true
    wall()
    const hall = await screen.findByRole('button', { name: /Hall light/ })
    expect(hall).toHaveAttribute('data-style', 'round')
    fireEvent.click(hall)
    await waitFor(() => expect(state.posted).toEqual([{ path: '/pages/7/home/lights/hall', body: { on: true } }]))
  })

  it('only shows them to a display that may look and nothing more', async () => {
    state.allow = false
    state.posted = []
    wall()
    await screen.findByText('Hall light')
    expect(screen.queryByRole('button', { name: /Hall light/ })).not.toBeInTheDocument()
  })
})
