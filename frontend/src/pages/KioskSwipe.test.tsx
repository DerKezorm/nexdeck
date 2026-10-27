/**
 * A wall display turns its pages by a swipe, on a wide screen too, and the
 * rotation then starts its time again from the page chosen.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { KioskPage } from './KioskPage'

const wall = vi.hoisted(() => ({ cycle: 10, rest: 0 }))
vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  get: vi.fn(async (path: string) => {
    if (path === '/kiosk') {
      const page = (id: number, name: string) => ({
        id, name, slug: name.toLowerCase(), icon: '', position: id, layouts: { lg: [], md: [], sm: [] }, widgets: [
          { id: id * 10, kind: 'core.clock', title: `Clock ${name}`, icon: '', link: '', renderer: 'clock', options: {}, integration_id: null, refresh_seconds: null },
        ],
      })
      return {
        id: 1, slug: 'hall', name: 'Hall', icon: '', owner_id: 1, background: { kind: 'bundled', value: 'aurora' }, settings: {},
        provisioned: false, permission: 'view', live: {},
        pages: [page(1, 'One'), page(2, 'Two'), page(3, 'Three')],
        kiosk: { cycle_seconds: wall.cycle, dim_from: '', dim_to: '', allow_actions: false, name: 'Hall', rest_minutes: wall.rest },
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

const current = () => screen.getAllByRole('button').find((one) => one.getAttribute('aria-current') === 'page')?.getAttribute('aria-label')

function swipe(from: number, to: number) {
  const card = document.querySelector('[data-widget]')!
  fireEvent.touchStart(card, { touches: [{ clientX: from, clientY: 400 }] })
  fireEvent.touchMove(card, { touches: [{ clientX: (from + to) / 2, clientY: 402 }] })
  fireEvent.touchEnd(card, { touches: [], changedTouches: [{ clientX: to, clientY: 404 }] })
}

async function wait(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

// A wide wall tablet: no phone-sized query matches, and the wall swipes anyway.
const wide = (query: string) => ({ matches: query === 'all', media: query })

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.stubGlobal('matchMedia', wide)
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  wall.cycle = 10
  wall.rest = 0
})

describe('swiping on a wall display', () => {
  it('turns to the next page and back, on a wide screen, and not past the first', async () => {
    wall.cycle = 0
    show()
    await screen.findByRole('button', { name: 'One' })
    expect(current()).toBe('One')
    swipe(600, 300)
    expect(current()).toBe('Two')
    swipe(300, 600)
    expect(current()).toBe('One')
    swipe(300, 600)
    expect(current()).toBe('One')
  })

  it('starts the rotation again from the page chosen by hand', async () => {
    show()
    await screen.findByRole('button', { name: 'One' })
    await wait(8_000)
    expect(current()).toBe('One')
    swipe(600, 300)
    expect(current()).toBe('Two')
    // Without the new start the rotation would leave the page two seconds later.
    await wait(8_000)
    expect(current()).toBe('Two')
    await wait(3_000)
    expect(current()).toBe('Three')
  })

  it('does nothing while the display rests', async () => {
    wall.cycle = 0
    wall.rest = 1
    show()
    await screen.findByRole('button', { name: 'One' })
    await wait(61_000)
    expect(screen.getByTestId('wall-rest')).toBeInTheDocument()
    swipe(600, 300)
    // The touch that wakes it is only that.
    expect(current()).toBe('One')
  })
})
