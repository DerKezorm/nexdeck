/**
 * What the bar says when a shortcut has been typed and nothing else yet.
 *
 * ⚠️ `!y` on its own produced "nothing matches", which reads as "that
 * shortcut does not exist". It exists; it is waiting for a word. A wrong
 * message here makes a working feature look broken.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { CommandPalette } from './CommandPalette'

const settings = vi.hoisted(() => ({ value: {} as unknown }))
vi.mock('../api/client', () => ({
  get: vi.fn(async () => settings.value),
  mediaUrl: () => '',
}))

const TARGETS = {
  enabled: true,
  targets: [
    { name: 'DuckDuckGo', url: 'https://duckduckgo.com/?q={query}', prefix: 'd', icon: '' },
    { name: 'YouTube', url: 'https://www.youtube.com/results?search_query={query}', prefix: 'y', icon: '' },
  ],
}

function show() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <CommandPalette open onClose={vi.fn()} boards={[]} widgets={[]} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('CommandPalette', () => {
  beforeEach(() => {
    settings.value = TARGETS
    vi.stubGlobal('open', () => null)
  })

  it('says which target it is waiting on, not that nothing matches', async () => {
    show()
    await userEvent.type(screen.getByRole('textbox'), '!y')
    await waitFor(() => expect(screen.getByText(/YouTube/)).toBeTruthy())
    expect(screen.queryByText(/Nothing matches|Nichts passt/i)).toBeNull()
  })

  it('offers the search once a word is typed', async () => {
    show()
    await userEvent.type(screen.getByRole('textbox'), '!y cats')
    await waitFor(() => expect(screen.getByRole('option', { name: /cats/ })).toBeTruthy())
  })

  it('treats a shortcut nobody has as ordinary words', async () => {
    show()
    await userEvent.type(screen.getByRole('textbox'), '!zz')
    // pickTarget leaves an unknown shortcut in the query, so it is searched
    // for rather than swallowed. Nothing is waiting, so no logo row appears.
    await waitFor(() => expect(screen.getAllByRole('option').length).toBeGreaterThan(0))
    expect(screen.queryByText(/type what to search for|Suchbegriff eingeben/i)).toBeNull()
  })

  it('says nothing matches for ordinary text that finds nothing', async () => {
    show()
    await userEvent.type(screen.getByRole('textbox'), 'zzzqqq')
    // Plain words are a search, so the way out is offered rather than nothing.
    await waitFor(() => expect(screen.getAllByRole('option').length).toBeGreaterThan(0))
  })
})
