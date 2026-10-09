/**
 * Changing an identity provider instead of deleting it and adding it again
 * (issue #10). Deleting it drops every account linked to it, so a typo in the
 * issuer URL cost every linked person their way in.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
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
  links: 0,
}

const STEPS = {
  ok: true,
  steps: [
    { key: 'reached', ok: true, detail: 'authentik 2026.8.1' },
    { key: 'filled', ok: true, detail: 'added the sign-in provider' },
  ],
}

const calls = vi.hoisted(() => ({ patch: [] as { path: string; body: unknown }[], post: [] as unknown[], setup: [] as unknown[], links: 0 }))
vi.mock('../../api/client', () => ({
  ApiError: class ApiError extends Error {},
  get: vi.fn(async (path: string) => {
    if (path === '/oidc/providers') return [PROVIDER]
    // The count of linked accounts as the server has it now, not as the list had it.
    if (path === '/oidc/providers/7') return { ...PROVIDER, links: calls.links }
    return { public_url: 'https://deck.example.com' }
  }),
  post: vi.fn(async (path: string, body: unknown) => {
    if (path === '/oidc/authentik/setup') {
      calls.setup.push(body)
      return STEPS
    }
    calls.post.push(body)
    return {}
  }),
  patch: vi.fn(async (path: string, body: unknown) => {
    calls.patch.push({ path, body })
    return {}
  }),
  del: vi.fn(async () => ({})),
  serverUrl: (path: string) => path,
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
    calls.setup.length = 0
    calls.links = 0
  })

  it('set authentik up with a one-time token and forget the token afterwards', async () => {
    const user = userEvent.setup()
    show()
    const button = await screen.findByRole('button', { name: 'Set up' }, { timeout: 3000 })
    expect(button).toBeDisabled()
    await user.click(screen.getByLabelText('Address of authentik'))
    await user.paste('https://auth.example.com')
    await user.click(screen.getByLabelText('API token'))
    await user.paste('one-time')
    await user.click(button)

    await waitFor(() => expect(calls.setup).toEqual([{ url: 'https://auth.example.com', token: 'one-time' }]))
    expect(await screen.findByText(/authentik reached: authentik 2026.8.1/)).toBeInTheDocument()
    expect(screen.getByText(/link your account with authentik once under Profile/)).toBeInTheDocument()
    expect(screen.getByLabelText('API token')).toHaveValue('')
    expect(screen.getByRole('link', { name: 'Download a blueprint instead' })).toHaveAttribute('href', '/api/v1/oidc/authentik/blueprint')
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

  it('ask before another issuer drops the links, and say how many', async () => {
    calls.links = 3
    const user = userEvent.setup()
    show()
    await user.click(await screen.findByRole('button', { name: 'Edit authentik' }, { timeout: 3000 }))
    const issuer = screen.getByLabelText('Issuer URL')
    await user.clear(issuer)
    await user.click(issuer)
    await user.paste('https://id.example.com/realms/home')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('Another issuer is another provider. 3 accounts will have to link again afterwards.')).toBeInTheDocument()
    expect(calls.patch).toEqual([])
    // Cancel keeps everything as it is.
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }))
    expect(calls.patch).toEqual([])
    expect(screen.getByLabelText('Issuer URL')).toHaveValue('https://id.example.com/realms/home')

    await user.click(screen.getByRole('button', { name: 'Save' }))
    await user.click(await screen.findByRole('button', { name: 'Change the issuer' }))
    await waitFor(() => expect(calls.patch).toHaveLength(1))
    expect(calls.patch[0].body).toMatchObject({ issuer_url: 'https://id.example.com/realms/home' })
  })

  it('do not ask when the issuer is only written differently', async () => {
    calls.links = 3
    const user = userEvent.setup()
    show()
    await user.click(await screen.findByRole('button', { name: 'Edit authentik' }, { timeout: 3000 }))
    const issuer = screen.getByLabelText('Issuer URL')
    await user.clear(issuer)
    await user.click(issuer)
    // Without the slash at the end. Spaces never reach the value: an input of type url strips them.
    await user.paste('https://auth.example.com/application/o/nexdeck')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(calls.patch).toHaveLength(1))
    expect(screen.queryByText(/Another issuer is another provider/)).toBeNull()
  })

  it('hand out no accounts unless told to', async () => {
    const user = userEvent.setup()
    show()
    const toggle = await screen.findByRole('switch', { name: 'Create accounts on first sign-in' }, { timeout: 3000 })
    expect(toggle).toHaveAttribute('aria-checked', 'false')
    expect(screen.getByText(/Off: only invited people and linked accounts come in through this provider/)).toBeInTheDocument()
    for (const [label, value] of [['Short name', 'pocket'], ['Button label', 'Pocket ID'], ['Issuer URL', 'https://pocket.example.com'], ['Client ID', 'nexdeck']]) {
      await user.click(screen.getByLabelText(label))
      await user.paste(value)
    }
    await user.click(screen.getByRole('button', { name: 'Add provider' }))
    await waitFor(() => expect(calls.post).toHaveLength(1))
    expect(calls.post[0]).toMatchObject({ slug: 'pocket', auto_create: false })
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
