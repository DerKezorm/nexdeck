/**
 * The board says when every card shows invented data.
 *
 * ⚠️ Issue #2: a Nomad connection tested fine, and its cards showed the three
 * sample nodes, because the setup wizard had put the whole installation in
 * demo mode. Nothing on the board said so.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { get } from '../api/client'
import { DemoNotice } from './DemoNotice'

const about = vi.hoisted(() => ({ value: { demo: false, demo_forced: false } }))
vi.mock('../api/client', () => ({
  get: vi.fn(async () => about.value),
}))

function show(admin: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <DemoNotice admin={admin} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('DemoNotice', () => {
  beforeEach(() => {
    about.value = { demo: false, demo_forced: false }
  })

  it('says so while demo mode is on, with the way out for an administrator', async () => {
    about.value = { demo: true, demo_forced: false }
    show(true)
    expect(await screen.findByText(/every card shows invented data/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Switch off' })).toHaveAttribute('href', '/system/integrations')
    // No role: `status` is the board's edit-mode hint, `note` its phone hint.
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
  })

  it('offers no way out to somebody who cannot take it', async () => {
    about.value = { demo: true, demo_forced: false }
    show(false)
    expect(await screen.findByText(/every card shows invented data/)).toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('offers no switch when NEXDECK_DEMO holds the mode', async () => {
    about.value = { demo: true, demo_forced: true }
    show(true)
    expect(await screen.findByText(/every card shows invented data/)).toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('stays away with demo mode off', async () => {
    const { container } = show(true)
    // Let the answer arrive before looking; an empty page before it proves nothing.
    await vi.waitFor(() => expect(get).toHaveBeenCalledWith('/about'))
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(container).toBeEmptyDOMElement()
  })
})
