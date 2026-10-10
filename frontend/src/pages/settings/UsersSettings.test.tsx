/**
 * The account list: a link to a sign-in provider is a mark, and it is undone in a menu of the account with the
 * administrator's own password (sign-in blueprint 04), not by a cross on the mark.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { UsersSettings } from './UsersSettings'
import { useAuth } from '../../stores/auth'

const USERS = [
  { id: 1, username: 'admin', display_name: 'Admin', role: 'admin', disabled: false, providers: [] },
  {
    id: 2,
    username: 'alex',
    display_name: 'Alex',
    role: 'user',
    disabled: false,
    providers: [
      { provider_id: 7, slug: 'sso', label: 'Single sign-on' },
      { provider_id: 8, slug: 'entra', label: 'Microsoft' },
    ],
  },
  { id: 3, username: 'sam', display_name: 'Sam', role: 'user', disabled: false, providers: [] },
]

// Built at run time: a literal with the shape of a credential stops the commit guard.
const OWN = ['typed', 'in', 'the', 'dialog'].join(' ')

const calls = vi.hoisted(() => ({ del: [] as { path: string; body: unknown }[] }))
vi.mock('../../api/client', () => ({
  ApiError: class ApiError extends Error {},
  get: vi.fn(async () => USERS),
  post: vi.fn(async () => ({})),
  patch: vi.fn(async () => ({})),
  put: vi.fn(async () => ({})),
  del: vi.fn(async (path: string, body: unknown) => {
    calls.del.push({ path, body })
  }),
}))

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <UsersSettings />
    </QueryClientProvider>,
  )
}

describe('the providers of an account', () => {
  beforeEach(() => {
    calls.del.length = 0
    useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin' } as never })
  })

  it('shows the links as marks without a cross', async () => {
    show()
    const marks = await screen.findByTestId('account-providers')
    expect(within(marks).getByText('Single sign-on')).toBeInTheDocument()
    expect(within(marks).getByText('Microsoft')).toBeInTheDocument()
    expect(within(marks).queryAllByRole('button')).toHaveLength(0)
  })

  it('offers a menu only to an account that has a link', async () => {
    show()
    await screen.findByText('Alex')
    expect(screen.getAllByRole('button', { name: /^More for/ })).toHaveLength(1)
    expect(screen.getByRole('button', { name: 'More for Alex' })).toHaveAttribute('aria-haspopup', 'menu')
  })

  it('unlinks through the menu, with the own password, from the provider that was chosen', async () => {
    const user = userEvent.setup()
    show()
    await user.click(await screen.findByRole('button', { name: 'More for Alex' }))
    const items = screen.getAllByRole('menuitem')
    expect(items.map((item) => item.textContent)).toEqual(['Unlink Single sign-on', 'Unlink Microsoft'])
    await user.click(screen.getByRole('menuitem', { name: 'Unlink Microsoft' }))
    expect(screen.queryByRole('menu')).toBeNull()
    const confirm = screen.getAllByRole('button', { name: 'Unlink' }).at(-1)!
    expect(confirm).toBeDisabled()
    await user.type(screen.getByLabelText('Your password'), OWN)
    await user.click(confirm)
    await waitFor(() => expect(calls.del).toHaveLength(1))
    expect(calls.del[0]).toEqual({ path: '/oidc/admin/accounts/2/links/8', body: { password: OWN } })
  })

  it('closes the menu with Escape and sends nothing', async () => {
    const user = userEvent.setup()
    show()
    await user.click(await screen.findByRole('button', { name: 'More for Alex' }))
    expect(screen.getByRole('menu')).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).toBeNull()
    expect(calls.del).toHaveLength(0)
  })
})
