/**
 * Ctrl K leads to the MCP keys. The entry's words are not in the first load:
 * the bar fetches them when it opens, and the entry shows once they are there.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuth } from '../stores/auth'
import { CommandPalette } from './CommandPalette'

vi.mock('../api/client', () => ({
  get: vi.fn(async () => ({ enabled: false, targets: [] })),
  mediaUrl: () => '',
}))

function Where() {
  const location = useLocation()
  return <span data-testid="where">{location.pathname + location.hash}</span>
}

function show() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <CommandPalette open onClose={vi.fn()} boards={[]} widgets={[]} />
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('the MCP entry in Ctrl K', () => {
  beforeEach(() => {
    useAuth.setState({ user: { id: 1, username: 'sam', role: 'user' } as never })
  })
  afterEach(async () => {
    await i18next.changeLanguage('en')
  })

  it('opens the page of the keys, found by "mcp"', async () => {
    const user = userEvent.setup()
    show()
    await user.type(screen.getByRole('textbox'), 'mcp')
    await user.click(await screen.findByText('MCP keys'))
    expect(screen.getByTestId('where')).toHaveTextContent('/settings/mcp')
  })

  it('is found by the word Claude as well', async () => {
    const user = userEvent.setup()
    show()
    await user.type(screen.getByRole('textbox'), 'claude')
    expect(await screen.findByText('MCP keys')).toBeInTheDocument()
  })

  it('is not offered to a guest', async () => {
    useAuth.setState({ user: { id: 2, username: 'visitor', role: 'guest' } as never })
    const user = userEvent.setup()
    show()
    await user.type(screen.getByRole('textbox'), 'mcp')
    // Long enough for the words to have come, were they asked for at all.
    await act(async () => {
      await import('../lib/mcpTexts')
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
    expect(screen.queryByText('MCP keys')).toBeNull()
  })

  it('speaks the language on screen once its words have come', async () => {
    await i18next.changeLanguage('de')
    const user = userEvent.setup()
    show()
    await user.type(screen.getByRole('textbox'), 'mcp')
    expect(await screen.findByText('MCP-Schlüssel')).toBeInTheDocument()
  })
})
