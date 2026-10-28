/**
 * The MCP keys have their own entry and page in the settings (Abnahme 9).
 *
 * They stood right under the API tokens and looked alike, and the first key
 * made for Claude Code was an API token, which MCP does not take. The tokens
 * page now points to the keys, and the old address leads to their page.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useAuth } from '../../stores/auth'
import { key, serve, STATUS, TOOLS } from '../../test/mcpServer'
import { SettingsPage } from './SettingsPage'

function Where() {
  const location = useLocation()
  return <span data-testid="where">{location.pathname + location.hash}</span>
}

function open(path: string, role: 'user' | 'guest' = 'user') {
  useAuth.setState({ user: { id: 1, username: 'sam', role } as never })
  serve({
    'GET /boards': () => [],
    'GET /tokens': () => [],
    'GET /mcp/status': () => STATUS,
    'GET /mcp/tools': () => TOOLS,
    'GET /mcp/keys': () => [key()],
  })
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/settings/*" element={<SettingsPage />} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  useAuth.setState({ user: null })
})

describe('the MCP keys in the settings', () => {
  it('have an entry of their own in the menu', async () => {
    open('/settings')
    const menu = screen.getByRole('navigation', { name: 'My settings' })
    expect(await within(menu).findByRole('link', { name: 'AI from outside (MCP)' })).toHaveAttribute('href', '/settings/mcp')
  })

  it('are not in the menu of a guest', async () => {
    open('/settings', 'guest')
    const menu = screen.getByRole('navigation', { name: 'My settings' })
    await new Promise((settle) => setTimeout(settle, 20))
    expect(within(menu).queryByRole('link', { name: 'AI from outside (MCP)' })).toBeNull()
  })

  it('have a page of their own, without the API tokens', async () => {
    open('/settings/mcp')
    expect(await screen.findByRole('heading', { name: 'AI from outside (MCP)' })).toBeInTheDocument()
    expect(await screen.findByTestId('mcp-key-1')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'API tokens' })).toBeNull()
  })

  it('are no longer under the API tokens, which point to them instead', async () => {
    open('/settings/tokens')
    expect(await screen.findByRole('heading', { name: 'API tokens' })).toBeInTheDocument()
    const hint = await screen.findByTestId('mcp-hint')
    expect(hint).toHaveTextContent('Programs such as Claude Code connect over MCP')
    expect(within(hint).getByRole('link', { name: 'AI from outside (MCP)' })).toHaveAttribute('href', '/settings/mcp')
    expect(screen.queryByTestId('mcp-key-1')).toBeNull()
  })

  it('are found at the old address too', async () => {
    open('/settings/tokens#mcp')
    expect(await screen.findByTestId('mcp-key-1')).toBeInTheDocument()
    expect(screen.getByTestId('where')).toHaveTextContent(/^\/settings\/mcp$/)
  })
})
