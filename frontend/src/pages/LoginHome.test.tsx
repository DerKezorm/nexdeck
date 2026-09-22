/**
 * On the home network the sign-in page signs the browser in without anything
 * typed; after signing out on purpose it waits for a press instead. And the
 * administrator's page sends what was entered and says what nexdeck makes of
 * the address.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'

import { post, put } from '../api/client'
import { useAuth } from '../stores/auth'
import { HomeNetworkSettings } from './settings/HomeNetworkSettings'
import { LoginPage } from './LoginPage'

let home: { available: boolean; held_off?: boolean; name?: string } = { available: false }
const KITCHEN = { id: 5, username: 'kitchen', display_name: 'Kitchen', role: 'user', locale: 'en', theme: 'system', auth_kind: 'home' }

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  get: vi.fn(async (path: string) => {
    if (path === '/auth/home') return home
    if (path === '/settings/home-network')
      return { enabled: false, networks: [], user_id: null, seen: { address: null, how: 'forwarded_by_unknown', reason: 'Something in front forwards.' }, trusted_proxies: [], recent: [] }
    if (path === '/users') return [KITCHEN, { id: 1, username: 'admin', display_name: 'Admin', role: 'admin', disabled: false }]
    throw new Error(`unexpected ${path}`)
  }),
  post: vi.fn(async (path: string) => {
    if (path === '/auth/home') return KITCHEN
    throw new Error(`unexpected ${path}`)
  }),
  put: vi.fn(async () => ({})),
  patch: vi.fn(),
}))
vi.mock('../i18n', () => ({ setLanguage: vi.fn(async () => undefined) }))

function login() {
  useAuth.setState({ user: null, loading: false, status: { needs_setup: false, providers: [], can_reset_password: false } as never })
  return render(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>,
  )
}

describe('signing in at home', () => {
  beforeEach(() => {
    vi.mocked(post).mockClear()
    vi.mocked(put).mockClear()
  })

  it('signs in without anything typed on the home network', async () => {
    home = { available: true, held_off: false, name: 'Kitchen' }
    login()
    await waitFor(() => expect(post).toHaveBeenCalledWith('/auth/home', { again: false }))
    await waitFor(() => expect(useAuth.getState().user?.username).toBe('kitchen'))
  })

  it('waits for a press after signing out on purpose', async () => {
    home = { available: true, held_off: true, name: 'Kitchen' }
    login()
    const button = await screen.findByRole('button', { name: 'Continue as Kitchen' })
    expect(post).not.toHaveBeenCalled()
    await userEvent.click(button)
    expect(post).toHaveBeenCalledWith('/auth/home', { again: true })
  })

  it('shows only the password form elsewhere', async () => {
    home = { available: false }
    login()
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(post).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: /Continue as/ })).not.toBeInTheDocument()
  })

  it('lets the administrator choose only ordinary accounts and says what it sees', async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <HomeNetworkSettings />
      </QueryClientProvider>,
    )
    expect(await screen.findByTestId('home-seen')).toHaveTextContent('cannot tell your real address')
    const account = await screen.findByLabelText('Account')
    await waitFor(() => expect(account.querySelectorAll('option')).toHaveLength(2))
    expect(account).not.toHaveTextContent('Admin')
    await userEvent.selectOptions(account, '5')
    await userEvent.type(screen.getByLabelText('Home networks'), '192.168.1.0/24{enter}10.0.0.0/8')
    await userEvent.click(screen.getByRole('switch', { name: 'Sign in on the home network without a password' }))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(put).toHaveBeenCalledWith('/settings/home-network', { enabled: true, networks: ['192.168.1.0/24', '10.0.0.0/8'], user_id: 5 })
  })
})
