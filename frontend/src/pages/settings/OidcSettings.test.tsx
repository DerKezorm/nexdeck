/**
 * Changing an identity provider instead of deleting it and adding it again
 * (issue #10). Deleting it drops every account linked to it, so a typo in the
 * issuer URL cost every linked person their way in.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { OidcSettings } from './OidcSettings'

const PROVIDER = {
  id: 7,
  slug: 'authentik',
  label: 'authentik',
  issuer_url: 'https://auth.example.com/application/o/nexdeck/',
  client_id: 'nexdeck',
  has_secret: true,
  scopes: 'openid profile email',
  enabled: true,
  auto_create: false,
  trusts_second_factor: true,
  default_role: 'guest',
}

const calls = vi.hoisted(() => ({ patch: [] as { path: string; body: unknown }[], post: [] as unknown[] }))
vi.mock('../../api/client', () => ({
  ApiError: class ApiError extends Error {},
  get: vi.fn(async (path: string) => (path === '/oidc/providers' ? [PROVIDER] : { public_url: 'https://deck.example.com' })),
  post: vi.fn(async (_path: string, body: unknown) => {
    calls.post.push(body)
    return {}
  }),
  patch: vi.fn(async (path: string, body: unknown) => {
    calls.patch.push({ path, body })
    return {}
  }),
  del: vi.fn(async () => ({})),
}))

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <OidcSettings />
    </QueryClientProvider>,
  )
}

describe('identity providers', () => {
  beforeEach(() => {
    calls.patch.length = 0
    calls.post.length = 0
  })

  it('are changed in place, and an empty secret field keeps the secret', async () => {
    const user = userEvent.setup()
    show()
    await user.click(await screen.findByRole('button', { name: 'Edit authentik' }, { timeout: 3000 }))

    expect(screen.getByLabelText('Issuer URL')).toHaveValue(PROVIDER.issuer_url)
    expect(screen.getByLabelText('Client secret')).toHaveValue('')
    expect(screen.getByLabelText('Client secret')).toHaveAttribute('placeholder', 'Left empty, the secret stays as it is')

    const issuer = screen.getByLabelText('Issuer URL')
    await user.clear(issuer)
    // Pasted, not typed: typed key by key the whole form draws itself 45
    // times, and under the load of a full CI run that took the test past its
    // five seconds.
    await user.click(issuer)
    await user.paste('https://auth.example.com/application/o/deck/')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(calls.patch).toHaveLength(1))
    expect(calls.post).toEqual([])
    expect(calls.patch[0].path).toBe('/oidc/providers/7')
    // Everything else as it was, the settings that were off included.
    expect(calls.patch[0].body).toEqual({
      slug: 'authentik',
      label: 'authentik',
      issuer_url: 'https://auth.example.com/application/o/deck/',
      client_id: 'nexdeck',
      client_secret: '',
      scopes: 'openid profile email',
      enabled: true,
      auto_create: false,
      trusts_second_factor: true,
      default_role: 'guest',
    })
    // And the form is back to adding a new one.
    expect(await screen.findByRole('button', { name: 'Add provider' })).toBeInTheDocument()
    expect(screen.getByLabelText('Issuer URL')).toHaveValue('')
  })

  it('warn that a new short name needs a new redirect URI at the provider', async () => {
    const user = userEvent.setup()
    show()
    await user.click(await screen.findByRole('button', { name: 'Edit authentik' }, { timeout: 3000 }))
    expect(screen.queryByText(/changes the redirect URI/)).toBeNull()
    await user.type(screen.getByLabelText('Short name'), '2')
    expect(screen.getByText(/changes the redirect URI/)).toBeInTheDocument()
  })

  it('go back to adding one on cancel, without a word to the server', async () => {
    const user = userEvent.setup()
    show()
    await user.click(await screen.findByRole('button', { name: 'Edit authentik' }, { timeout: 3000 }))
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.getByLabelText('Short name')).toHaveValue('')
    expect(screen.getByRole('button', { name: 'Add provider' })).toBeInTheDocument()
    expect(calls.patch).toEqual([])
  })
})
