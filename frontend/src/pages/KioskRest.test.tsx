/**
 * A wall display rests on a large clock after a while without a touch, and
 * a touch brings the board back.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { nudge } from '../components/WallRest'
import { KioskPage } from './KioskPage'

const minutes = vi.hoisted(() => ({ rest: 5 }))
vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  get: vi.fn(async (path: string) => {
    if (path === '/kiosk') {
      return {
        id: 1, slug: 'hall', name: 'Hall', icon: '', owner_id: 1, background: { kind: 'bundled', value: 'aurora' }, settings: {},
        provisioned: false, permission: 'view',
        live: { 7: { status: 'ok', error: 'timed out' } },
        pages: [{ id: 1, name: 'One', slug: 'one', icon: '', position: 0, layouts: { lg: [], md: [], sm: [] }, widgets: [
          { id: 7, kind: 'radarr.queue', title: 'Radarr', icon: '', link: '', renderer: 'list', options: {}, integration_id: 1, refresh_seconds: null },
        ] }],
        kiosk: { cycle_seconds: 0, dim_from: '', dim_to: '', allow_actions: false, name: 'Hall', rest_minutes: minutes.rest },
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

beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }))
afterEach(() => {
  vi.useRealTimers()
  minutes.rest = 5
})

describe('the rest of a wall display', () => {
  it('comes after the minutes without a touch, says what is down, and goes at a touch', async () => {
    show()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4 * 60_000)
    })
    expect(screen.queryByTestId('wall-rest')).toBeNull()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(61_000)
    })
    expect(screen.getByTestId('wall-rest')).toBeInTheDocument()
    expect(screen.getByTestId('rest-state').textContent).toContain('Radarr')
    fireEvent.pointerDown(window)
    expect(screen.queryByTestId('wall-rest')).toBeNull()
  })

  it('never comes when the link was made without a rest', async () => {
    minutes.rest = 0
    show()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(120 * 60_000)
    })
    expect(screen.queryByTestId('wall-rest')).toBeNull()
  })
})

describe('the wander against burn-in', () => {
  it('stays within a few pixels of the middle', () => {
    expect(nudge(() => 0)).toEqual({ x: -24, y: -16 })
    expect(nudge(() => 1)).toEqual({ x: 24, y: 16 })
  })
})
