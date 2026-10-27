/**
 * A token that only reads, unless full access is chosen on purpose.
 *
 * The server starts a token at reading when nothing is said; the form says it
 * all the same, so what the list shows is what was asked for, and the list
 * says which token may change things.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { TokensSettings } from './TokensSettings'
import { useAuth } from '../../stores/auth'

const calls = vi.hoisted(() => ({ post: [] as { path: string; body: unknown }[] }))
vi.mock('../../api/client', () => ({
  ApiError: class ApiError extends Error {},
  get: vi.fn(async () => [
    { id: 1, name: 'Wall', prefix: 'nd_aaaa', created_at: '2026-10-27T10:00:00Z', last_used_at: null, scope: 'read' },
    { id: 2, name: 'Backup script', prefix: 'nd_bbbb', created_at: '2026-10-27T10:00:00Z', last_used_at: null, scope: 'full' },
  ]),
  post: vi.fn(async (path: string, body: { name: string; scope: string }) => {
    calls.post.push({ path, body })
    return { id: 3, name: body.name, prefix: 'nd_cccc', created_at: '', last_used_at: null, scope: body.scope, token: 'nd_cccc-secret' }
  }),
  del: vi.fn(async () => ({})),
}))

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <TokensSettings />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('API tokens', () => {
  beforeEach(() => {
    calls.post.length = 0
    useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin' } as never })
  })

  it('says beside every token whether it only reads', async () => {
    show()
    const wall = (await screen.findByText('Wall')).closest('li')
    const script = screen.getByText('Backup script').closest('li')
    expect(wall?.textContent).toContain('Read only')
    expect(script?.textContent).toContain('Full access')
  })

  it('makes a token that only reads unless full access is picked', async () => {
    const user = userEvent.setup()
    show()
    await screen.findByText('Wall')
    expect((screen.getByLabelText('Access') as HTMLSelectElement).value).toBe('read')
    await user.type(screen.getByLabelText('Token name'), 'Tablet')
    await user.click(screen.getByRole('button', { name: 'Create' }))
    await waitFor(() => expect(calls.post).toHaveLength(1))
    expect(calls.post[0]).toEqual({ path: '/tokens', body: { name: 'Tablet', scope: 'read' } })

    await user.selectOptions(screen.getByLabelText('Access'), 'full')
    await user.type(screen.getByLabelText('Token name'), 'Script')
    await user.click(screen.getByRole('button', { name: 'Create' }))
    await waitFor(() => expect(calls.post).toHaveLength(2))
    expect(calls.post[1].body).toEqual({ name: 'Script', scope: 'full' })
    // The next one starts at reading again.
    expect((screen.getByLabelText('Access') as HTMLSelectElement).value).toBe('read')
  })
})
