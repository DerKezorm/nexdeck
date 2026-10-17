/**
 * System, Sign-in as the shared sign-in module lays it out: three cards in their order, the form as a
 * dialog with the fields in the module's order, the questions before an address or an issuer changes and before
 * an entry goes, and the steps of the authentik button with names and reasons instead of codes.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { SignInSettings } from './SignInSettings'

const ENTRY = {
  id: 7,
  slug: 'authentik',
  label: 'authentik',
  issuer: 'https://auth.example.com/application/o/nexdeck/',
  client_id: 'nexdeck',
  has_secret: true,
  scopes: 'openid profile email',
  enabled: true,
  auto_create: false,
  trusts_second_factor: true,
  managed: 'authentik',
  position: 0,
  redirect_uri: 'https://deck.example.com/api/v1/auth/oidc/authentik/callback',
  links: 3,
  editable: true,
  registered_redirect_uri: '',
  redirect_stale: false,
}

const ADDRESS = {
  public_url: 'https://deck.example.com',
  seen: 'https://deck.example.com',
  forwarded_proto: '',
  forwarded_host: '',
  proxy_ignored: false,
  callback_path: '/api/v1/auth/oidc/authentik/callback',
  redirect_uri: 'https://deck.example.com/api/v1/auth/oidc/authentik/callback',
  registered_redirect_uri: '',
  stale: false,
}

const calls = vi.hoisted(() => ({
  patch: [] as unknown[],
  put: [] as { path: string; body: unknown }[],
  post: [] as { path: string; body: unknown }[],
  del: [] as string[],
  setup: { ok: false, steps: [] as unknown[], count: 0 },
  askAddress: true,
}))

vi.mock('../../api/client', () => {
  class ApiError extends Error {
    code: string
    status: number
    detail: Record<string, unknown>
    constructor(status: number, code: string, message: string, _hint?: string, detail: Record<string, unknown> = {}) {
      super(message)
      this.status = status
      this.code = code
      this.detail = detail
    }
  }
  return {
    ApiError,
    get: vi.fn(async (path: string) => {
      if (path === '/oidc/admin/providers') return [ENTRY]
      if (path.startsWith('/oidc/admin/providers/7/impact')) return { issuer_change: 3, count: 3, only: 1 }
      if (path === '/oidc/authentik/address') return ADDRESS
      return { public_url: 'https://deck.example.com', require_two_factor: false, password_login: true, provider_active: true }
    }),
    patch: vi.fn(async (_path: string, body: Record<string, unknown>) => {
      calls.patch.push(body)
      if ('public_url' in body && !body.confirm_address && calls.askAddress) {
        throw new ApiError(409, 'public_url_change', 'asked', undefined, { count: 1, address: 'https://old.example.com/cb', hand: 2 })
      }
      return {}
    }),
    put: vi.fn(async (path: string, body: unknown) => {
      calls.put.push({ path, body })
      return {}
    }),
    post: vi.fn(async (path: string, body: unknown) => {
      calls.post.push({ path, body })
      if (path === '/oidc/authentik/setup') return calls.setup
      return {}
    }),
    del: vi.fn(async (path: string) => {
      calls.del.push(path)
      return {}
    }),
    serverUrl: (path: string) => path,
  }
})

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <SignInSettings />
    </QueryClientProvider>,
  )
}

describe('System, Sign-in', () => {
  beforeEach(() => {
    calls.patch.length = 0
    calls.put.length = 0
    calls.post.length = 0
    calls.del.length = 0
    calls.askAddress = true
  })

  it('shows the three cards in the order of the module, with the marks of an entry', async () => {
    show()
    const headings = await screen.findAllByRole('heading', { level: 2 })
    expect(headings.map((heading) => heading.textContent)).toEqual(['Sign-in', 'Sign-in providers', 'authentik in one step'])
    const list = await screen.findByTestId('provider-list')
    expect(within(list).getByText('on')).toBeInTheDocument()
    expect(within(list).getByText('set up through authentik')).toBeInTheDocument()
    expect(within(list).getByText(ENTRY.issuer)).toBeInTheDocument()
  })

  it('asks before the public address changes what providers know, and sends the yes', async () => {
    show()
    const field = await screen.findByLabelText('Public address')
    await waitFor(() => expect(field).toHaveValue('https://deck.example.com'))
    await userEvent.clear(field)
    await userEvent.type(field, 'https://new.example.com')
    await userEvent.click(within(screen.getByTestId('sign-in-card')).getByRole('button', { name: 'Save' }))
    const question = await screen.findByTestId('address-question')
    expect(question).toHaveTextContent('authentik still knows the redirect address https://old.example.com/cb')
    expect(question).toHaveTextContent('For 2 providers entered by hand, change the redirect address there yourself.')
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(calls.patch.at(-1)).toEqual({ public_url: 'https://new.example.com', confirm_address: true }))
  })

  it('opens the form as a dialog with the fields in the order of the module', async () => {
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Add a provider' }))
    const form = screen.getByTestId('provider-form')
    const labels = within(form)
      .getAllByText(/^(Name on the button|Short name|Issuer|Client ID|Client secret|Redirect address for the provider|On|New people get an account|The provider checks the second factor itself)$/)
      .map((label) => label.textContent)
    expect(labels).toEqual([
      'Name on the button',
      'Short name',
      'Issuer',
      'Client ID',
      'Client secret',
      'Redirect address for the provider',
      'On',
      'New people get an account',
      'The provider checks the second factor itself',
    ])
    await userEvent.type(within(form).getByLabelText('Name on the button'), 'Pocket ID')
    expect(within(form).getByLabelText('Short name')).toHaveValue('pocket-id')
    expect(within(form).getByTestId('provider-redirect')).toHaveTextContent('/api/v1/oidc/pocket-id/callback')
    // New entries: nobody gets an account on their own, the provider is trusted with the second factor.
    const switches = within(form).getAllByRole('switch')
    expect(switches.map((item) => item.getAttribute('aria-checked'))).toEqual(['true', 'false', 'true'])
  })

  it('asks with the number of accounts before another issuer drops their links', async () => {
    show()
    const list = await screen.findByTestId('provider-list')
    await userEvent.click(within(list).getByRole('button', { name: 'Edit' }))
    const form = screen.getByTestId('provider-form')
    expect(within(form).queryByLabelText('Short name')).not.toBeInTheDocument()
    const issuer = within(form).getByLabelText('Issuer')
    await userEvent.clear(issuer)
    await userEvent.type(issuer, 'https://other.example.com')
    await userEvent.click(screen.getAllByRole('button', { name: 'Save' }).at(-1)!)
    expect(await screen.findByText('Another issuer is another provider. 3 accounts will have to link again afterwards.')).toBeInTheDocument()
    expect(calls.put).toEqual([])
  })

  it('asks with the numbers before an entry goes', async () => {
    show()
    const list = await screen.findByTestId('provider-list')
    await userEvent.click(within(list).getByRole('button', { name: 'Remove' }))
    expect(await screen.findByText('Remove “authentik”? 3 accounts lose the link; for 1 of them it is the only way in.')).toBeInTheDocument()
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(calls.del).toEqual(['/oidc/admin/providers/7']))
  })

  it('names every step of the authentik button and why the failed one failed', async () => {
    calls.setup = {
      ok: false,
      count: 0,
      steps: [
        { key: 'reached', ok: true },
        { key: 'signingKey', ok: false, reason: 'token', status: 403 },
      ],
    }
    show()
    await userEvent.type(await screen.findByLabelText('Address of authentik'), 'https://auth.example.com')
    await userEvent.type(screen.getByLabelText('API token'), 'made-up')
    await userEvent.click(screen.getByRole('button', { name: 'Set up' }))
    const steps = await screen.findByTestId('authentik-steps')
    expect(steps).toHaveTextContent('Connection to authentik')
    expect(steps).toHaveTextContent('Signing key')
    expect(steps).toHaveTextContent('authentik did not accept the token (answer 403).')
    expect(steps).not.toHaveTextContent('signingKey')
    // The token was for this run only.
    expect(screen.getByLabelText('API token')).toHaveValue('')
  })
})
