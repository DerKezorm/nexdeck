/**
 * Own integrations when a connection is added or listed (KARTEN-3 AC-8, AC-9, EC-2, EC-4, EC-6, EC-9): the kind stands
 * beside the built-in ones with the mark "Custom", its fields make the form, the test answers in words, and a
 * connection whose kind was deleted says "integration missing".
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import deScreen from '../../i18n/de.json'
import { useAuth } from '../../stores/auth'
import { IntegrationsSettings } from './IntegrationsSettings'

const field = (extra: Record<string, unknown>) => ({ label: '', type: 'text', required: false, secret: false, default: null, help: '', placeholder: '', options: [], ...extra })

const ADAPTERS = [
  { kind: 'sonarr', label: 'Sonarr', category: 'downloads', description: '', icon: 'sonarr', beta: false, docs_url: '', needs_integration: true, fields: [field({ name: 'url', label: 'Address', required: true })], widgets: [] },
  {
    kind: 'custom:memos', label: 'Memos', category: 'other', description: 'Notes you keep for yourself.', icon: 'memos', beta: false, custom: true, docs_url: '', needs_integration: true,
    fields: [field({ name: 'url', label: 'Address', required: true }), field({ name: 'token', label: 'Access token', type: 'password', secret: true, required: true })],
    widgets: [],
  },
]

const CONNECTION = (extra: Record<string, unknown>) => ({
  id: 7, kind: 'sonarr', label: 'Sonarr', icon: 'sonarr', beta: false, name: 'Sonarr', config: {}, enabled: true, demo: false, admin_only: false, muted: false,
  last_ok_at: '2026-10-26T10:00:00Z', last_error: '', widget_count: 0, created_at: '2026-10-01T10:00:00Z', ...extra,
})

const world = vi.hoisted(() => ({ connections: [] as unknown[], versions: {} as unknown, test: {} as unknown, sent: [] as { url: string; method: string; body: Record<string, unknown> | null }[] }))

function stub() {
  world.sent = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input).replace(/^.*\/api\/v1/, '')
      const method = init?.method ?? 'GET'
      world.sent.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null })
      const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } })
      if (url === '/adapters') return json(ADAPTERS)
      if (url === '/integrations' && method === 'GET') return json(world.connections)
      if (url === '/integrations/test') return json(world.test)
      if (url === '/about') return json({ version: '0.48.0', demo: false, demo_forced: false, demo_data: false })
      if (url === '/integrations/versions') return json(world.versions)
      if (url === '/boards') return json([{ id: 3, slug: 'home', name: 'Home' }])
      if (url === '/integrations/found') return json({ found: [], ignored: 0, looked_at: null })
      return json({})
    }),
  )
}

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <IntegrationsSettings />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** The way to a kind: the Add button opens the catalog, and a tile of it opens the form of that kind. */
async function pick(kind: RegExp, add = 'Add an integration') {
  await userEvent.click(await screen.findByRole('button', { name: add }))
  await userEvent.click(await screen.findByRole('button', { name: kind }))
}

beforeEach(() => {
  world.connections = []
  world.test = { ok: true, message: 'Connected.' }
  stub()
  useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin' } as never, loading: false })
})

afterEach(async () => {
  vi.unstubAllGlobals()
  await i18next.changeLanguage('en')
})

describe('own integrations when a connection is added', () => {
  it('karten3 ac8: the own kind stands beside the built-in ones with the mark Custom; the built-in one has none', async () => {
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Add an integration' }))
    const own = await screen.findByRole('button', { name: /Memos/ })
    expect(within(own).getByText('Custom')).toBeInTheDocument()
    expect(within(screen.getByRole('button', { name: /Sonarr/ })).queryByText('Custom')).toBeNull()
  })

  it('karten3 ac8: choosing it opens the form of its fields, the secret one hidden, with the mark', async () => {
    show()
    await pick(/Memos/)
    const sheet = await screen.findByRole('dialog')
    expect(within(sheet).getByText('Custom')).toBeInTheDocument()
    expect(within(sheet).getByText('Access token')).toBeInTheDocument()
    expect(sheet.querySelector('input[type="password"]')).not.toBeNull()
  })

  it.each([
    ['sign_in_no_ticket', 'The sign-in answer comes without a ticket.', 'Check where the description of the integration looks for the ticket.'],
    ['sign_in_web_page', 'The sign-in leads to a web page.', 'Use a key, or an address that goes around it.'],
    ['auth_failed', 'The service refused the sign-in details.', 'Check the key, or the user and password.'],
    ['unreachable', 'The service could not be reached.', 'Check the address, and that nexdeck can reach it.'],
    ['unexpected_answer', 'The service answered in a way the integration does not expect.', 'Check the test address'],
    ['sign_in_failed', 'Signing in failed.', 'Check the user and password.'],
  ])('karten3 ac9: the test says %s in a sentence and a hint', async (code, sentence, hint) => {
    world.test = { ok: false, code, message: 'server words', hint: 'server hint' }
    show()
    await pick(/Memos/)
    await userEvent.click(await screen.findByRole('button', { name: 'Test connection' }))
    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent(sentence)
    expect(status).toHaveTextContent(hint)
    expect(status).not.toHaveTextContent('server words')
    expect(world.sent.find((one) => one.url === '/integrations/test')?.body).toMatchObject({ kind: 'custom:memos' })
  })

  it('karten3 ec4: a paused sign-in keeps the sentence of the server, which names the time', async () => {
    world.test = { ok: false, code: 'sign_in_paused', message: 'Signing in is paused until 14:05.', hint: '' }
    show()
    await pick(/Memos/)
    await userEvent.click(await screen.findByRole('button', { name: 'Test connection' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Signing in is paused until 14:05.')
  })

  it('karten3 ac9: a green test stays as the server says it', async () => {
    show()
    await pick(/Memos/)
    await userEvent.click(await screen.findByRole('button', { name: 'Test connection' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Connected.')
  })

  it('karten3 ac9: the sentences come in German', async () => {
    i18next.addResourceBundle('de', 'translation', deScreen, true, true)
    await i18next.changeLanguage('de')
    world.test = { ok: false, code: 'sign_in_no_ticket', message: 'x' }
    show()
    await pick(/Memos/, deScreen.settings.integrations.add)
    await userEvent.click(await screen.findByRole('button', { name: 'Verbindung testen' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Die Antwort auf die Anmeldung enthält kein Ticket.')
  })
})

describe('a connection whose kind was deleted', () => {
  it('karten3 ec6: says "integration missing" and cannot be edited, while the others are normal', async () => {
    world.connections = [CONNECTION({ id: 7 }), CONNECTION({ id: 8, kind: 'custom:gone', label: 'Gone', name: 'Old notes' })]
    show()
    const row = (await screen.findByText('Old notes')).closest('li')!
    expect(within(row).getByText('integration missing')).toBeInTheDocument()
    expect(within(row).getByRole('button', { name: 'Edit Old notes' })).toBeDisabled()
    const normal = screen.getAllByText('Sonarr', { selector: 'span' })[0].closest('li')!
    expect(within(normal).queryByText('integration missing')).toBeNull()
    expect(within(normal).getByRole('button', { name: 'Edit Sonarr' })).toBeEnabled()
  })

  it('karten3 ec6: the server may say it too', async () => {
    world.connections = [CONNECTION({ id: 9, missing: true })]
    show()
    expect(await screen.findByText('integration missing')).toBeInTheDocument()
  })

  it('karten3 ec6: a connection can still be deleted', async () => {
    world.connections = [CONNECTION({ id: 8, kind: 'custom:gone', name: 'Old notes' })]
    show()
    const row = (await screen.findByText('Old notes')).closest('li')!
    expect(within(row).getByRole('button', { name: 'Remove Old notes' })).toBeEnabled()
  })
})

describe('the version of a connection of an own kind (KARTEN-4)', () => {
  const reading = (extra: Record<string, unknown>) => ({ running: '1.2.0', newest: null, url: '', published: null, problem: '', asked: true, state: 'unknown', major: false, unread: false, upstream: 'usememos/memos', ...extra })

  beforeEach(() => {
    world.versions = {}
  })

  it('karten4 ac2: the version it runs stands in the list', async () => {
    world.connections = [CONNECTION({ id: 8, kind: 'custom:memos', name: 'Notes' })]
    world.versions = { 8: reading({}) }
    show()
    expect(await screen.findByText('Runs 1.2.0')).toBeInTheDocument()
  })

  it('karten4 ec2: a project without a release is no comparison, and the list says why', async () => {
    world.connections = [CONNECTION({ id: 8, kind: 'custom:memos', name: 'Notes' })]
    world.versions = { 8: reading({}) }
    show()
    const note = await screen.findByText('Newest not known')
    expect(note.getAttribute('title')).toMatch(/no release/i)
  })

  it('karten4 ec1: a version that cannot be read is said as not given, not as a fault', async () => {
    world.connections = [CONNECTION({ id: 8, kind: 'custom:memos', name: 'Notes' })]
    world.versions = { 8: reading({ running: null, problem: 'The service does not say which version it runs.', unread: false }) }
    show()
    expect(await screen.findByText('Version not given')).toBeInTheDocument()
  })
})
