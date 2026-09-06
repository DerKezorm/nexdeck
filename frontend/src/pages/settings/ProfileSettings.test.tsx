/**
 * The profile card, and the button that has to look like one.
 *
 * ⚠️ Everything below it on that page saves the moment it changes. These two
 * fields need a press, and the press used to sit under the left column in the
 * quiet style, so it read as "belongs to the name above it". Somebody filling
 * in the address looked for a second one and reported that there was none.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ProfileSettings } from './ProfileSettings'
import { useAuth } from '../../stores/auth'

const calls = vi.hoisted(() => ({ patched: [] as unknown[] }))
vi.mock('../../api/client', () => ({
  ApiError: class ApiError extends Error {},
  get: vi.fn(async () => []),
  post: vi.fn(async () => ({})),
  del: vi.fn(async () => ({})),
  upload: vi.fn(async () => ({})),
  serverUrl: (path: string) => path,
}))

const ME = {
  id: 1,
  username: 'admin',
  display_name: 'Deckmaster',
  email: 'deck@example.com',
  role: 'admin',
  locale: 'en',
  theme: 'dark',
  has_password: true,
  avatar_url: null,
  start_board_id: null,
}

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ProfileSettings />
    </QueryClientProvider>,
  )
}

describe('ProfileSettings', () => {
  beforeEach(() => {
    calls.patched = []
    useAuth.setState({
      user: ME as never,
      status: null,
      loading: false,
      update: (async (fields: unknown) => {
        calls.patched.push(fields)
      }) as never,
    })
  })

  it('offers one button for both fields, named after both', () => {
    show()
    expect(screen.getByRole('button', { name: /name and address/i })).toBeInTheDocument()
  })

  it('keeps the button quiet while there is nothing to save', () => {
    show()
    expect(screen.getByRole('button', { name: /name and address/i })).toBeDisabled()
    expect(screen.queryByText(/not saved yet/i)).toBeNull()
  })

  it('wakes up when the address is edited, not only the name', async () => {
    /** ⚠️ The reported case: the address changed and nothing said so. */
    show()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText(/e-?mail/i), 'x')
    expect(screen.getByRole('button', { name: /name and address/i })).toBeEnabled()
    expect(screen.getByText(/not saved yet/i)).toBeInTheDocument()
  })

  it('sends the address it was given', async () => {
    show()
    const user = userEvent.setup()
    const field = screen.getByLabelText(/e-?mail/i)
    await user.clear(field)
    await user.type(field, 'someone@example.org')
    await user.click(screen.getByRole('button', { name: /name and address/i }))
    expect(calls.patched).toEqual([{ display_name: 'Deckmaster', email: 'someone@example.org' }])
  })

  it('goes quiet again once the edit is taken back', async () => {
    show()
    const user = userEvent.setup()
    const field = screen.getByLabelText(/e-?mail/i)
    await user.type(field, 'x')
    await user.clear(field)
    await user.type(field, ME.email)
    expect(screen.getByRole('button', { name: /name and address/i })).toBeDisabled()
  })
})
