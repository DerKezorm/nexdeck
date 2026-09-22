/**
 * The board says when every card shows invented data, and leaving the demo
 * says first what goes.
 *
 * ⚠️ Issue #2: a Nomad connection tested fine, and its cards showed the three
 * sample nodes, because the setup wizard had put the whole installation in
 * demo mode. Nothing on the board said so.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { get, post } from '../api/client'
import { DemoNotice } from './DemoNotice'

const about = vi.hoisted(() => ({ value: { demo: false, demo_forced: false, demo_data: false } }))
const PLAN = { flag: true, forced: false, connections: ['Docker (demo)', 'Plex (demo)'], switched: ['Radarr'], boards: ['Home'], cards: 12, pages: 0 }
vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  get: vi.fn(async (path: string) => (path === '/demo/leave' ? PLAN : about.value)),
  post: vi.fn(async () => ({ ...PLAN, flag: false, starter: 'home-2' })),
}))

function show(admin: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/b/home']}>
        <Routes>
          <Route path="/b/:slug" element={<DemoNotice admin={admin} />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('DemoNotice', () => {
  beforeEach(() => {
    about.value = { demo: false, demo_forced: false, demo_data: false }
    vi.mocked(post).mockClear()
  })

  it('says so while demo mode is on, and names what goes before it goes', async () => {
    about.value = { demo: true, demo_forced: false, demo_data: true }
    show(true)
    expect(await screen.findByText(/every card shows invented data/)).toBeInTheDocument()
    // No role: `status` is the board's edit-mode hint, `note` its phone hint.
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.queryByRole('note')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Leave the demo' }))
    const plan = await screen.findByTestId('demo-leave-plan')
    expect(plan).toHaveTextContent('2 invented connections go.')
    expect(plan).toHaveTextContent('12 cards that read them go.')
    expect(plan).toHaveTextContent('Boards that were nothing but the demo go as a whole: Home.')
    expect(plan).toHaveTextContent('Kept, and back to real data: Radarr.')
    expect(post).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Leave demo mode' }))
    expect(post).toHaveBeenCalledWith('/demo/leave', {})
  })

  it('still speaks up when the switch is off but connections invent data', async () => {
    about.value = { demo: false, demo_forced: false, demo_data: true }
    show(true)
    expect(await screen.findByText(/still in demo mode/)).toBeInTheDocument()
  })

  it('offers no way out to somebody who cannot take it', async () => {
    about.value = { demo: true, demo_forced: false, demo_data: true }
    show(false)
    expect(await screen.findByText(/every card shows invented data/)).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('offers no way out when NEXDECK_DEMO holds the mode', async () => {
    about.value = { demo: true, demo_forced: true, demo_data: true }
    show(true)
    expect(await screen.findByText(/every card shows invented data/)).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('stays away with demo mode off and nothing invented', async () => {
    const { container } = show(true)
    // Let the answer arrive before looking; an empty page before it proves nothing.
    await vi.waitFor(() => expect(get).toHaveBeenCalledWith('/about'))
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(container).toBeEmptyDOMElement()
  })
})
