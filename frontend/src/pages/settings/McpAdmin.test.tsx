/**
 * "AI from outside (MCP)" under System: the switches for the installation, the
 * block list, and every key of every account.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { McpAdminSettings } from '../../lib/mcp'
import { key, serve, TOOLS, type Call } from '../../test/mcpServer'
import { McpAdmin } from './McpAdmin'

let saved: McpAdminSettings
let calls: Call[]

function start() {
  calls = serve({
    'GET /mcp/admin': () => saved,
    'PUT /mcp/admin': (body) => {
      saved = body as McpAdminSettings
      return saved
    },
    'GET /mcp/tools': () => TOOLS,
    'GET /mcp/admin/keys': () => [
      key({ id: 1, user: 'sam' } as never),
      key({ id: 2, name: 'oauth-5', kind: 'oauth', client: 'Claude', user: 'kim', level: 'act' } as never),
      key({ id: 3, name: 'Gone', user: 'sam', revoked: true } as never),
    ],
    'DELETE /mcp/admin/keys/1': () => null,
  })
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <McpAdmin />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('MCP under System', () => {
  beforeEach(() => {
    saved = { allowed: false, max_level: 'act', oauth_allowed: false, blocked_tools: [] }
  })
  afterEach(() => vi.unstubAllGlobals())

  it('shows what is stored: off, the highest level, no connectors, nothing blocked', async () => {
    start()
    const allow = await screen.findByRole('switch', { name: 'Allow MCP' })
    await waitFor(() => expect(screen.getByLabelText('Highest level')).toHaveValue('act'))
    expect(allow).not.toBeChecked()
    expect(screen.getByRole('switch', { name: 'Allow connectors' })).not.toBeChecked()
    for (const box of screen.getAllByRole('checkbox')) expect(box).not.toBeChecked()
  })

  it('stores the switches, the level and the block list in one go', async () => {
    const user = userEvent.setup()
    start()
    await user.click(await screen.findByRole('switch', { name: 'Allow MCP' }))
    await user.click(screen.getByRole('switch', { name: 'Allow connectors' }))
    await user.selectOptions(screen.getByLabelText('Highest level'), 'read')
    await user.click(screen.getByRole('checkbox', { name: /container_log/ }))
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(calls.some((call) => call.method === 'PUT')).toBe(true))
    expect(calls.find((call) => call.method === 'PUT')?.body).toEqual({ allowed: true, max_level: 'read', oauth_allowed: true, blocked_tools: ['container_log'] })
  })

  it('says in the block list what each tool does, in words for a person', async () => {
    start()
    expect(await screen.findByText('Finds cards by title, service, kind or board.')).toBeInTheDocument()
    expect(screen.queryByText('find_cards description')).toBeNull()
  })

  it('shows a tool that is already blocked as ticked, and lets it go again', async () => {
    saved = { ...saved, blocked_tools: ['diagnosis'] }
    const user = userEvent.setup()
    start()
    const box = await screen.findByRole('checkbox', { name: /diagnosis/ })
    await waitFor(() => expect(box).toBeChecked())
    await user.click(box)
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(calls.some((call) => call.method === 'PUT')).toBe(true))
    expect((calls.find((call) => call.method === 'PUT')?.body as McpAdminSettings).blocked_tools).toEqual([])
  })

  it('lists the keys of every account with their owner, and ends one on request', async () => {
    const user = userEvent.setup()
    start()
    const mine = await screen.findByTestId('mcp-admin-key-1')
    expect(mine).toHaveTextContent('sam')
    expect(screen.getByTestId('mcp-admin-key-2')).toHaveTextContent('Claude')
    expect(screen.getByTestId('mcp-admin-key-2')).toHaveTextContent('kim')
    // A key that is already revoked has nothing left to revoke.
    expect(within(screen.getByTestId('mcp-admin-key-3')).queryByRole('button', { name: /^Revoke / })).toBeNull()
    await user.click(within(mine).getByRole('button', { name: 'Revoke Laptop' }))
    expect(calls.some((call) => call.method === 'DELETE')).toBe(false)
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Revoke' }))
    await waitFor(() => expect(calls.some((call) => call.method === 'DELETE' && call.path === '/mcp/admin/keys/1')).toBe(true))
  })
})
