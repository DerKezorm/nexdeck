/**
 * The sign-in page with providers (shared sign-in module): the password form, "or", a button per provider in the
 * order of the list; with the password switched off only the buttons and the small way in for an administrator; a
 * refused sign-in said in words, and nothing shown that is not one of the module's codes.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'

import { useAuth } from '../stores/auth'
import { LoginPage } from './LoginPage'

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  get: vi.fn(async () => ({ available: false })),
  post: vi.fn(),
  serverUrl: (path: string) => path,
}))

const PROVIDERS = [
  { slug: 'authentik', label: 'authentik' },
  { slug: 'entra', label: 'Microsoft' },
]

function login(status: Record<string, unknown>, address = '/login') {
  useAuth.setState({ user: null, loading: false, status: { needs_setup: false, providers: PROVIDERS, can_reset_password: false, ...status } as never })
  return render(
    <MemoryRouter initialEntries={[address]}>
      <LoginPage />
    </MemoryRouter>,
  )
}

describe('the sign-in page with providers', () => {
  it('shows the password form, then "or", then a button per provider in order', () => {
    login({ password_login: true })
    expect(screen.getByLabelText('User name')).toBeInTheDocument()
    expect(screen.getByText('or')).toBeInTheDocument()
    const buttons = screen.getAllByRole('link', { name: /^Sign in with / })
    expect(buttons.map((button) => button.textContent)).toEqual(['Sign in with authentik', 'Sign in with Microsoft'])
    expect(buttons[0]).toHaveAttribute('href', '/api/v1/oidc/authentik/start')
  })

  it('with the password off shows the buttons and the small way in for the operator', async () => {
    login({ password_login: false })
    expect(screen.queryByLabelText('User name')).not.toBeInTheDocument()
    expect(screen.queryByText('or')).not.toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: /^Sign in with / })).toHaveLength(2)
    await userEvent.click(screen.getByRole('button', { name: 'Sign in as the operator with a password' }))
    expect(screen.getByLabelText('User name')).toBeInTheDocument()
  })

  it('says a refused sign-in in words, and nothing else that stands in the address', () => {
    const { unmount } = login({}, '/login?error=oidc_no_account')
    expect(screen.getByRole('alert')).toHaveTextContent('There is no account for you here.')
    unmount()
    login({}, '/login?error=%3Cscript%3E')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
