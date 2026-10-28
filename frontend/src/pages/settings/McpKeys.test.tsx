/**
 * "AI from outside (MCP)" in the account settings: making a key, seeing it
 * once, the list, and the rights per tool. The server is replaced by a table
 * of answers (`test/mcpServer.ts`).
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { McpKey } from '../../lib/mcp'
import { useAuth } from '../../stores/auth'
import { key, serve, STATUS, TOOLS, type Call } from '../../test/mcpServer'
import { McpKeys } from './McpKeys'

const BOARDS = [
  { id: 1, slug: 'lab', name: 'Lab', pages: [] },
  { id: 2, slug: 'wall', name: 'Wall', pages: [] },
]

let keys: McpKey[]
let status = STATUS
let calls: Call[]

function start(role: 'admin' | 'user' | 'guest' = 'user') {
  useAuth.setState({ user: { id: 1, username: 'sam', role } as never })
  calls = serve({
    'GET /mcp/status': () => status,
    'GET /mcp/tools': () => TOOLS,
    'GET /mcp/keys': () => keys,
    'GET /boards': () => BOARDS,
    'POST /mcp/keys': (body) => {
      const made = key({ id: 9, name: (body as { name: string }).name, prefix: 'ndm_Zz9Y' })
      keys = [...keys, made]
      return { key: made, token: `ndm_${'x'.repeat(43)}` }
    },
    'PUT /mcp/keys/1/rights': () => ({}),
    'DELETE /mcp/keys/1': () => null,
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <McpKeys />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('MCP keys in the account settings', () => {
  beforeEach(() => {
    keys = [key()]
    status = STATUS
  })
  afterEach(() => vi.unstubAllGlobals())

  it('says MCP is off and offers no form, to an account that cannot switch it on', async () => {
    status = { ...STATUS, allowed: false }
    start()
    expect(await screen.findByTestId('mcp-off')).toHaveTextContent('Only an administrator can switch it on')
    expect(screen.queryByRole('button', { name: 'Create key' })).toBeNull()
  })

  it('points an administrator to the switch under System', async () => {
    status = { ...STATUS, allowed: false }
    start('admin')
    expect(await screen.findByRole('link', { name: 'Switch it on under System.' })).toHaveAttribute('href', '/system/mcp')
  })

  it('shows nothing to a guest', async () => {
    start('guest')
    await waitFor(() => expect(screen.queryByText('AI from outside (MCP)')).toBeNull())
    expect(calls).toEqual([])
  })

  it('makes a key for all boards, shows it once with the two lines to copy, and then drops it', async () => {
    const user = userEvent.setup()
    start()
    await screen.findByText('Laptop')
    const create = screen.getByRole('button', { name: 'Create key' })
    expect(create).toBeDisabled()
    await user.type(screen.getByLabelText('Name of the key'), '  Tablet  ')
    await user.click(create)
    const token = `ndm_${'x'.repeat(43)}`
    expect(await screen.findByTestId('mcp-token')).toHaveTextContent(token)
    expect(calls.find((call) => call.method === 'POST')?.body).toEqual({ name: 'Tablet', level: 'read', expires_days: 90, boards: null })
    expect(screen.getByTestId('mcp-command')).toHaveTextContent(`claude mcp add --transport http nexdeck https://deck.example.com/api/mcp --header "Authorization: Bearer ${token}"`)
    const json = JSON.parse(screen.getByTestId('mcp-json').textContent ?? '')
    expect(json).toEqual({ mcpServers: { nexdeck: { type: 'http', url: 'https://deck.example.com/api/mcp', headers: { Authorization: `Bearer ${token}` } } } })
    // The list shows the prefix, never the key.
    expect(await screen.findByText('Tablet')).toBeInTheDocument()
    expect(screen.getByTestId('mcp-key-9')).not.toHaveTextContent(token)
    await user.click(screen.getByRole('button', { name: 'I have copied it' }))
    expect(screen.queryByTestId('mcp-token')).toBeNull()
    expect(document.body.textContent).not.toContain(token)
  })

  it('sends the chosen level, expiry and boards, and wants at least one board when a choice is made', async () => {
    const user = userEvent.setup()
    start()
    await screen.findByText('Laptop')
    await user.type(screen.getByLabelText('Name of the key'), 'Wall script')
    await user.selectOptions(screen.getByLabelText('Level'), 'act')
    await user.selectOptions(screen.getByLabelText('Expires'), 'never')
    await user.click(screen.getByLabelText('Only these boards'))
    expect(screen.getByRole('button', { name: 'Create key' })).toBeDisabled()
    await user.click(screen.getByLabelText('Wall'))
    await user.click(screen.getByRole('button', { name: 'Create key' }))
    await screen.findByTestId('mcp-token')
    expect(calls.find((call) => call.method === 'POST')?.body).toEqual({ name: 'Wall script', level: 'act', expires_days: null, boards: [2] })
  })

  it('sends the number of days that was picked', async () => {
    const user = userEvent.setup()
    start()
    await screen.findByText('Laptop')
    await user.type(screen.getByLabelText('Name of the key'), 'Short')
    await user.selectOptions(screen.getByLabelText('Expires'), '30')
    await user.click(screen.getByRole('button', { name: 'Create key' }))
    await screen.findByTestId('mcp-token')
    expect((calls.find((call) => call.method === 'POST')?.body as { expires_days: number }).expires_days).toBe(30)
  })

  it('offers no higher level than the administrator allows', async () => {
    status = { ...STATUS, max_level: 'read' }
    const user = userEvent.setup()
    start()
    await screen.findByText('Laptop')
    expect(screen.queryByLabelText('Level')).toBeNull()
    await user.type(screen.getByLabelText('Name of the key'), 'Reader')
    await user.click(screen.getByRole('button', { name: 'Create key' }))
    await screen.findByTestId('mcp-token')
    expect((calls.find((call) => call.method === 'POST')?.body as { level: string }).level).toBe('read')
  })

  it('lists prefix, level, boards, last use and expiry, and a connected program under its own name', async () => {
    keys = [
      key({ id: 1, level: 'act', boards: [2], last_used_at: '2026-10-27T08:00:00Z', expires_at: '2099-01-01T00:00:00Z' }),
      key({ id: 2, name: 'oauth-3', prefix: 'ndm_OaOa', kind: 'oauth', client: 'Claude' }),
      key({ id: 3, name: 'Old', revoked: true }),
      key({ id: 4, name: 'Lapsed', expires_at: '2020-01-01T00:00:00Z' }),
    ]
    start()
    const first = await screen.findByTestId('mcp-key-1')
    expect(first).toHaveTextContent('ndm_AbCd…')
    expect(first).toHaveTextContent('Read and act')
    expect(first).toHaveTextContent('Boards: Wall')
    expect(first).toHaveTextContent(/Last used/)
    expect(first).toHaveTextContent(/Expires/)
    const connected = screen.getByTestId('mcp-key-2')
    expect(connected).toHaveTextContent('Claude')
    expect(connected).toHaveTextContent('Connected program')
    expect(connected).toHaveTextContent('never used')
    expect(connected).toHaveTextContent('All boards you may see')
    // Neither a revoked nor a lapsed key holds rights to set; a revoked one cannot be revoked again, a lapsed one can be tidied away.
    for (const id of [3, 4]) {
      expect(within(screen.getByTestId(`mcp-key-${id}`)).queryByRole('button', { name: 'Rights per tool' })).toBeNull()
    }
    expect(within(screen.getByTestId('mcp-key-3')).queryByRole('button', { name: /^Revoke / })).toBeNull()
    expect(within(screen.getByTestId('mcp-key-4')).getByRole('button', { name: 'Revoke Lapsed' })).toBeInTheDocument()
    expect(screen.getByTestId('mcp-key-3')).toHaveTextContent('Revoked')
    expect(screen.getByTestId('mcp-key-4')).toHaveTextContent('Expired')
  })

  it('asks before it revokes, and revokes the one key', async () => {
    const user = userEvent.setup()
    start()
    await user.click(await screen.findByRole('button', { name: 'Revoke Laptop' }))
    expect(calls.some((call) => call.method === 'DELETE')).toBe(false)
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Revoke' }))
    await waitFor(() => expect(calls.some((call) => call.method === 'DELETE' && call.path === '/mcp/keys/1')).toBe(true))
  })

  it('does not revoke when the question is cancelled', async () => {
    const user = userEvent.setup()
    start()
    await user.click(await screen.findByRole('button', { name: 'Revoke Laptop' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }))
    expect(calls.some((call) => call.method === 'DELETE')).toBe(false)
  })

  describe('rights per tool', () => {
    async function open() {
      const user = userEvent.setup()
      start()
      await user.click(await screen.findByRole('button', { name: 'Rights per tool' }))
      await screen.findByTestId('rights-1')
      return user
    }
    const optionsOf = (name: string) => Array.from((screen.getByLabelText(`Right for ${name}`) as HTMLSelectElement).options).map((option) => option.value)

    it('lets a reading tool be allowed or denied, never asked about', async () => {
      await open()
      expect(optionsOf('needs_attention')).toEqual(['allow', 'deny'])
      expect(optionsOf('find_cards')).toEqual(['allow', 'deny'])
      expect(optionsOf('press_button')).toEqual(['allow', 'ask', 'deny'])
      expect((screen.getByLabelText('Right for press_button') as HTMLSelectElement).value).toBe('ask')
    })

    it('greys out what cannot be set and says why', async () => {
      await open()
      // Above the level of a key that only reads.
      expect(screen.getByLabelText('Right for press_button')).toBeDisabled()
      expect(screen.getByTestId('why-press_button')).toHaveTextContent('Needs the level')
      // Blocked for everyone by the administrator.
      expect(screen.getByLabelText('Right for container_log')).toBeDisabled()
      expect(screen.getByTestId('why-container_log')).toHaveTextContent('Blocked by the administrator')
      // For administrators only, and this account is none.
      expect(screen.getByLabelText('Right for diagnosis')).toBeDisabled()
      expect(screen.getByTestId('why-diagnosis')).toHaveTextContent('Only administrators')
      expect(screen.getByLabelText('Right for needs_attention')).toBeEnabled()
    })

    it('stores only what differs from the defaults, and keeps what a greyed-out row already held', async () => {
      keys = [key({ level: 'act', tool_rights: { container_log: 'allow' } })]
      const user = await open()
      expect(screen.getByRole('button', { name: 'Save rights' })).toBeDisabled()
      await user.selectOptions(screen.getByLabelText('Right for press_button'), 'allow')
      await user.selectOptions(screen.getByLabelText('Right for find_cards'), 'deny')
      await user.click(screen.getByRole('button', { name: 'Save rights' }))
      await waitFor(() => expect(calls.some((call) => call.method === 'PUT')).toBe(true))
      expect(calls.find((call) => call.method === 'PUT')).toEqual({
        method: 'PUT',
        path: '/mcp/keys/1/rights',
        body: { tool_rights: { find_cards: 'deny', press_button: 'allow', container_log: 'allow' } },
      })
    })
  })
})
