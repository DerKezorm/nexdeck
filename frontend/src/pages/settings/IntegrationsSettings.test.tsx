/**
 * Issue #20: the bell on a connection.
 *
 * One click where the connection stands, no sheet to open and nothing to
 * save. The crossed-out bell is the state; the name says which way a click
 * goes, so a screen reader hears more than "button".
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { IntegrationsSettings } from './IntegrationsSettings'
import { useAuth } from '../../stores/auth'

const state = vi.hoisted(() => ({
  muted: false,
  fail: false,
  cards: 2,
  demo: false,
  patches: [] as { path: string; body: unknown }[],
}))

vi.mock('../../api/client', () => {
  class ApiError extends Error {}
  return {
    ApiError,
    get: vi.fn(async (path: string) => {
      if (path === '/about') return { version: '0.22.0', demo: state.demo, demo_forced: false, demo_data: false }
      if (path === '/adapters') return []
      if (path === '/boards') return [{ id: 3, slug: 'home', name: 'Home' }]
      return [
        {
          id: 7, kind: 'sonarr', label: 'Sonarr', icon: 'sonarr', beta: false, name: 'Sonarr', config: {},
          enabled: true, demo: false, admin_only: false, muted: state.muted,
          last_ok_at: '2026-09-26T10:00:00Z', last_error: '', widget_count: state.cards, created_at: '2026-09-01T10:00:00Z',
        },
      ]
    }),
    post: vi.fn(async () => ({})),
    del: vi.fn(async () => ({})),
    patch: vi.fn(async (path: string, body: { muted?: boolean }) => {
      state.patches.push({ path, body })
      if (state.fail) throw new ApiError('The connection is gone.')
      if (body.muted !== undefined) state.muted = body.muted
      return {}
    }),
  }
})

/** Where "Build a card" leads, and what it carries there. */
function Board() {
  const location = useLocation()
  return <p>{`board ${location.pathname} ${JSON.stringify(location.state)}`}</p>
}

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/system/integrations']}>
        <Routes>
          <Route path="/system/integrations" element={<IntegrationsSettings />} />
          <Route path="/b/:slug" element={<Board />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('the bell on a connection', () => {
  beforeEach(() => {
    state.muted = false
    state.fail = false
    state.cards = 2
    state.demo = false
    state.patches.length = 0
    useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin' } as never })
  })

  it('mutes with one click and turns back on with the next', async () => {
    show()
    const bell = await screen.findByRole('button', { name: 'Mute notices for Sonarr' })
    expect(bell).toHaveAttribute('aria-pressed', 'false')

    await userEvent.click(bell)
    expect(state.patches).toEqual([{ path: '/integrations/7', body: { muted: true } }])
    const off = await screen.findByRole('button', { name: 'Turn notices for Sonarr back on' })
    expect(off).toHaveAttribute('aria-pressed', 'true')

    await userEvent.click(off)
    expect(state.patches[1]).toEqual({ path: '/integrations/7', body: { muted: false } })
    await screen.findByRole('button', { name: 'Mute notices for Sonarr' })
  })

  it('sends the bell alone, so the cards are not logged in again', async () => {
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Mute notices for Sonarr' }))
    expect(Object.keys(state.patches[0].body as object)).toEqual(['muted'])
  })

  it('says so when the switch did not take', async () => {
    state.fail = true
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Mute notices for Sonarr' }))
    expect(await screen.findByText('The connection is gone.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Mute notices for Sonarr' })).toBeInTheDocument()
  })

  it('is not there for a user, who may not change a connection', async () => {
    useAuth.setState({ user: { id: 2, username: 'sam', role: 'user' } as never })
    show()
    await screen.findByText('1 connection, 2 cards together.')
    await waitFor(() => expect(screen.queryByRole('button', { name: /notices for Sonarr/ })).toBeNull())
  })
})

describe('a connection without a card', () => {
  beforeEach(() => {
    state.cards = 0
    useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin', start_board_id: 3 } as never })
  })

  it('leads to the library of the home board, already searching for its service', async () => {
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Build a card' }))
    expect(await screen.findByText('board /b/home {"library":"Sonarr"}')).toBeInTheDocument()
  })
})

describe('demo mode for everything', () => {
  beforeEach(() => {
    state.demo = false
    state.patches.length = 0
    useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin' } as never })
  })

  it('is one slim line while it is off, and switches on from there', async () => {
    show()
    const toggle = await screen.findByRole('switch', { name: 'Demo mode for everything' })
    expect(toggle).toHaveAttribute('aria-checked', 'false')
    expect(screen.getByText('off. Switches every card to invented data.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Leave demo mode…' })).toBeNull()
    await userEvent.click(toggle)
    expect(state.patches).toContainEqual({ path: '/settings', body: { demo: true } })
  })

  it('is the full box while it is on, with the way out', async () => {
    state.demo = true
    show()
    expect(await screen.findByRole('switch', { name: 'Demo mode for everything' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByText('Some connections still run in demo mode and show invented data.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Leave demo mode…' })).toBeInTheDocument()
    expect(screen.queryByText('off. Switches every card to invented data.')).toBeNull()
  })
})
