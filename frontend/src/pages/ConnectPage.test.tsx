/**
 * The consent page of an MCP connector: what a program asks for, allowing it
 * (the browser goes back to the program with what the server answered),
 * declining it, and a browser that is not signed in yet. The server is a
 * table of answers (`test/mcpServer.ts`).
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuth } from '../stores/auth'
import { refusal, serve, type Call } from '../test/mcpServer'
import { ConnectPage, leave } from './ConnectPage'

const ASKED = 'client_id=prog-1&redirect_uri=https%3A%2F%2Fapp.example.com%2Fcallback&code_challenge=' + 'c'.repeat(43) +
  '&code_challenge_method=S256&state=st-9&resource=https%3A%2F%2Fdeck.example.com%2Fapi%2Fmcp&response_type=code'

const INFO = {
  client_name: 'Claude',
  redirect_host: 'app.example.com',
  max_level: 'act',
  boards: [
    { id: 1, name: 'Lab' },
    { id: 2, name: 'Wall' },
  ],
}

let calls: Call[]
let went: string[]

function LoginStandIn() {
  const location = useLocation()
  return <p data-testid="login">{location.search}</p>
}

function start(routes: Record<string, (body: unknown) => unknown> = {}) {
  calls = serve({
    'GET /mcp/consent': () => INFO,
    'POST /mcp/consent': (body) => {
      const answer = body as { allow: boolean }
      return { redirect: answer.allow ? 'https://app.example.com/callback?code=ndc_x&state=st-9' : 'https://app.example.com/callback?error=access_denied&state=st-9' }
    },
    ...routes,
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/connect?${ASKED}`]}>
        <Routes>
          <Route path="/connect" element={<ConnectPage />} />
          <Route path="/login" element={<LoginStandIn />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('the consent page of a connector', () => {
  beforeEach(() => {
    went = []
    vi.spyOn(leave, 'to').mockImplementation((address: string) => {
      went.push(address)
    })
    useAuth.setState({ user: { id: 1, username: 'sam', role: 'user' } as never, loading: false, status: { needs_setup: false } as never })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('shows the program, where it returns to, the levels up to the ceiling and the boards', async () => {
    start()
    expect(await screen.findByRole('heading', { name: 'Claude wants to connect to your nexdeck' })).toBeInTheDocument()
    expect(screen.getByTestId('connect-host')).toHaveTextContent('app.example.com')
    expect(screen.getByText('sam')).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /^Read and act/ })).toBeInTheDocument()
    // The request goes to the server as the program made it, so the server checks it before anything is shown.
    const asked = calls.find((call) => call.method === 'GET' && call.path.startsWith('/mcp/consent'))!
    const query = new URLSearchParams(asked.path.split('?')[1])
    expect(query.get('client_id')).toBe('prog-1')
    expect(query.get('redirect_uri')).toBe('https://app.example.com/callback')
    expect(query.get('resource')).toBe('https://deck.example.com/api/mcp')
    await userEvent.click(screen.getByRole('radio', { name: 'Only these boards' }))
    expect(screen.getByRole('checkbox', { name: 'Wall' })).toBeInTheDocument()
  })

  it('offers only reading when the administrator allows no more', async () => {
    start({ 'GET /mcp/consent': () => ({ ...INFO, max_level: 'read' }) })
    await screen.findByRole('heading', { name: /wants to connect/ })
    expect(screen.queryByRole('radio', { name: /^Read and act/ })).toBeNull()
    expect(screen.getByRole('radio', { name: /^Read/ })).toBeChecked()
  })

  it('allowing sends the choice and goes back to the address the server answered', async () => {
    start()
    await screen.findByRole('heading', { name: /wants to connect/ })
    await userEvent.click(screen.getByRole('radio', { name: /^Read and act/ }))
    await userEvent.click(screen.getByRole('radio', { name: 'Only these boards' }))
    await userEvent.click(screen.getByRole('checkbox', { name: 'Wall' }))
    await userEvent.click(screen.getByRole('button', { name: 'Allow' }))
    await waitFor(() => expect(went).toEqual(['https://app.example.com/callback?code=ndc_x&state=st-9']))
    const sent = calls.find((call) => call.method === 'POST')!.body as Record<string, unknown>
    expect(sent).toMatchObject({ allow: true, level: 'act', boards: [2], client_id: 'prog-1', state: 'st-9',
      redirect_uri: 'https://app.example.com/callback', code_challenge_method: 'S256', resource: 'https://deck.example.com/api/mcp' })
    expect(sent.code_challenge).toBe('c'.repeat(43))
    expect(await screen.findByText('Back to the program …')).toBeInTheDocument()
  })

  it('allows nothing with an empty choice of boards', async () => {
    start()
    await screen.findByRole('heading', { name: /wants to connect/ })
    await userEvent.click(screen.getByRole('radio', { name: 'Only these boards' }))
    expect(screen.getByRole('button', { name: 'Allow' })).toBeDisabled()
  })

  it('declining goes back to the program with the refusal', async () => {
    start()
    await screen.findByRole('heading', { name: /wants to connect/ })
    await userEvent.click(screen.getByRole('button', { name: 'Decline' }))
    await waitFor(() => expect(went).toEqual(['https://app.example.com/callback?error=access_denied&state=st-9']))
    expect((calls.find((call) => call.method === 'POST')!.body as { allow: boolean }).allow).toBe(false)
  })

  it('stays and says why when the server refuses the answer', async () => {
    start({ 'POST /mcp/consent': () => refusal(409, 'too_many_keys', 'An account holds at most 20 keys.') })
    await screen.findByRole('heading', { name: /wants to connect/ })
    await userEvent.click(screen.getByRole('button', { name: 'Allow' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Your account holds the most keys it may have.')
    expect(went).toEqual([])
  })

  it('explains a request it cannot show, and offers no buttons', async () => {
    start({ 'GET /mcp/consent': () => refusal(400, 'oauth_redirect', 'This return address is not registered for the program.') })
    expect(await screen.findByRole('alert')).toHaveTextContent('did not register. Nothing was sent to it.')
    expect(screen.queryByRole('button', { name: 'Allow' })).toBeNull()
  })

  it('sends a browser that is not signed in to the sign-in first, with the whole request to come back to', async () => {
    useAuth.setState({ user: null, loading: false })
    start()
    const login = await screen.findByTestId('login')
    const next = new URLSearchParams(login.textContent ?? '').get('next')
    expect(next).toBe(`/connect?${ASKED}`)
    expect(calls).toEqual([])
  })
})
