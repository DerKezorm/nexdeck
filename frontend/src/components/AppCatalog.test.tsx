/**
 * The app catalog of issue #37 in the browser: a tile picks an app and one of
 * its addresses, a tile can be saved as an app, and System, Apps keeps them.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { vi } from 'vitest'

import { MemoryRouter } from 'react-router-dom'

import { AppsSettings } from '../pages/settings/AppsSettings'
import { useAuth } from '../stores/auth'
import { WidgetLibrary } from './WidgetLibrary'
import { WidgetSettingsSheet } from './WidgetSettingsSheet'

const PAPERLESS = {
  id: 4,
  name: 'Paperless',
  icon: 'paperless-ngx',
  description: 'Documents',
  addresses: [
    { label: 'Proxy', url: 'https://paperless.home.example' },
    { label: 'Tailscale', url: 'https://paperless.tailnet.example' },
  ],
  home: 'Proxy',
  away: 'Tailscale',
  tiles: 2,
}

const TILE = {
  id: 3, kind: 'core.app', title: 'Paperless (old)', icon: 'paperless-ngx', link: 'https://old.example',
  renderer: 'app', options: {}, integration_id: null, refresh_seconds: null, health: null,
}

type Sent = { url: string; method: string; body: Record<string, unknown> | null }

function server(sent: Sent[], apps: unknown[] = [PAPERLESS]) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    sent.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null })
    const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } })
    if (url.includes('/adapters')) return json([{ kind: 'core', label: 'Core', needs_integration: false, fields: [], widgets: [{ kind: 'core.app', label: 'App tile', options: [] }] }])
    if (url.includes('/integrations')) return json([])
    if (url.endsWith('/apps') && method === 'POST') return json({ ...PAPERLESS, id: 9, name: 'Films', addresses: [{ label: 'Main', url: 'https://films.example' }], home: '', away: '', tiles: 0 }, 201)
    if (url.endsWith('/apps')) return json(apps)
    if (url.includes('/pages/') && method === 'POST') return json({ widget: { id: 11 } }, 201)
    return json({})
  })
}

function wrap(node: ReactNode) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{node}</QueryClientProvider>)
}

function sheet(widget: unknown) {
  return wrap(<WidgetSettingsSheet widget={widget as never} pages={[{ id: 1, name: 'one' }]} onClose={vi.fn()} onSaved={vi.fn()} onDeleted={vi.fn()} />)
}

beforeEach(() => {
  useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin' } as never })
})

describe('an app tile and the catalog', () => {
  it('follows an app: its own name, icon and link make way, and the check follows too', async () => {
    const sent: Sent[] = []
    vi.stubGlobal('fetch', server(sent))
    sheet(TILE)
    const picker = await screen.findByLabelText(/app from the catalog/i)
    await waitFor(() => expect(within(picker).getByRole('option', { name: 'Paperless' })).toBeInTheDocument())
    await userEvent.selectOptions(picker, '4')
    // The automatic choice, since the app names an address for home and one for the road.
    expect(screen.getByLabelText(/^opens/i)).toHaveValue('auto')
    expect(screen.getByLabelText(/^title/i)).toHaveValue('')
    expect(screen.getByLabelText(/^title/i)).toHaveAttribute('placeholder', 'Paperless')
    await userEvent.click(screen.getByRole('button', { name: /save/i }))
    await waitFor(() => expect(sent.some((one) => one.url.includes('/health'))).toBe(true))
    const saved = sent.find((one) => one.method === 'PATCH')!.body!
    expect(saved).toMatchObject({ title: '', icon: '', link: '', options: { app_id: 4, address: 'auto' } })
    // An empty target follows the app on the server, at every check.
    expect(sent.find((one) => one.url.includes('/health'))!.body!.target).toBe('')
  })

  it('opens with the tile\'s own name, not the app\'s it shows', async () => {
    vi.stubGlobal('fetch', server([]))
    sheet({ ...TILE, title: 'Paperless', own_title: '', own_icon: '', link: '', options: { app_id: 4, address: 'Tailscale' }, app: { ...PAPERLESS, address: 'Tailscale', addresses: ['Proxy', 'Tailscale'], automatic: true }, service_link: 'https://paperless.tailnet.example' })
    const address = await screen.findByLabelText(/^opens/i)
    expect(screen.getByLabelText(/^title/i)).toHaveValue('')
    expect(address).toHaveValue('Tailscale')
    expect(within(address).getAllByRole('option').map((one) => one.getAttribute('value'))).toEqual(['auto', 'Proxy', 'Tailscale'])
  })

  it('saves a tile as an app and follows it', async () => {
    const sent: Sent[] = []
    vi.stubGlobal('fetch', server(sent, []))
    sheet({ ...TILE, title: 'Films', icon: 'radarr', link: 'https://films.example', options: { description: 'Movies' } })
    await userEvent.click(await screen.findByRole('button', { name: /save as app/i }))
    await waitFor(() => expect(sent.some((one) => one.method === 'POST' && one.url.endsWith('/apps'))).toBe(true))
    expect(sent.find((one) => one.method === 'POST' && one.url.endsWith('/apps'))!.body).toEqual({
      name: 'Films', icon: 'radarr', description: 'Movies', addresses: [{ label: 'Main', url: 'https://films.example' }],
    })
    await waitFor(() => expect(screen.getByLabelText(/^link/i)).toHaveValue(''))
  })

  it('is not offered to somebody who may not change the catalog', async () => {
    useAuth.setState({ user: { id: 2, username: 'kim', role: 'user' } as never })
    vi.stubGlobal('fetch', server([], []))
    sheet({ ...TILE, link: 'https://films.example' })
    await screen.findByLabelText(/app from the catalog/i)
    expect(screen.queryByRole('button', { name: /save as app/i })).toBeNull()
  })
})

describe('System, Apps', () => {
  // ⚠️ Types some 80 characters key by key, and every key draws the form
  // again: 1.6 s alone, but past the 5 s default in the full run on a busy
  // machine, three times in a row on 23.10.2026.
  it('lists the apps and adds one with its addresses', async () => {
    const sent: Sent[] = []
    vi.stubGlobal('fetch', server(sent))
    wrap(<AppsSettings />)
    expect(await screen.findByText('Paperless')).toBeInTheDocument()
    expect(screen.getByText(/2 tiles/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /add app/i }))
    await userEvent.type(screen.getByLabelText(/^name/i), 'Films')
    await userEvent.type(screen.getByLabelText('Label of address 1'), 'Proxy')
    await userEvent.type(screen.getByLabelText('Address 1'), 'https://films.example')
    await userEvent.click(screen.getByRole('button', { name: /add address/i }))
    await userEvent.type(screen.getByLabelText('Label of address 2'), 'Direct')
    await userEvent.type(screen.getByLabelText('Address 2'), 'http://10.0.0.5:7878')
    await userEvent.selectOptions(screen.getByLabelText(/at home/i), 'Direct')
    await userEvent.click(screen.getByRole('button', { name: /^save/i }))
    await waitFor(() => expect(sent.some((one) => one.method === 'POST')).toBe(true))
    expect(sent.find((one) => one.method === 'POST')!.body).toEqual({
      name: 'Films', icon: '', description: '',
      addresses: [{ label: 'Proxy', url: 'https://films.example' }, { label: 'Direct', url: 'http://10.0.0.5:7878' }],
      home: 'Direct', away: '',
    })
  }, 15_000)

  it('says what becomes of the tiles before an app is deleted', async () => {
    const sent: Sent[] = []
    vi.stubGlobal('fetch', server(sent))
    wrap(<AppsSettings />)
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Paperless' }))
    expect(screen.getByText(/2 tiles follow it\. They stay/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /^confirm$/i }))
    await waitFor(() => expect(sent.some((one) => one.method === 'DELETE' && one.url.endsWith('/apps/4'))).toBe(true))
  })
})

describe('adding a card', () => {
  it('places an app of the catalog straight away, already following it', async () => {
    const sent: Sent[] = []
    vi.stubGlobal('fetch', server(sent))
    const created = vi.fn()
    wrap(<MemoryRouter><WidgetLibrary open onClose={vi.fn()} pageId={1} onCreated={created} /></MemoryRouter>)
    expect(await screen.findByText('Apps from the catalog')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /paperless/i }))
    await waitFor(() => expect(created).toHaveBeenCalledWith(11))
    const body = sent.find((one) => one.method === 'POST' && one.url.includes('/pages/1/widgets'))!.body
    // No name of its own, so the app's shows and follows a rename.
    expect(body).toMatchObject({ kind: 'core.app', title: '', options: { app_id: 4, address: 'auto' } })
  })

  it('finds an app by what the search says', async () => {
    vi.stubGlobal('fetch', server([]))
    wrap(<MemoryRouter><WidgetLibrary open onClose={vi.fn()} pageId={1} onCreated={vi.fn()} /></MemoryRouter>)
    await screen.findByText('Apps from the catalog')
    await userEvent.type(screen.getByLabelText(/search/i), 'documents')
    expect(screen.getByRole('button', { name: /paperless/i })).toBeInTheDocument()
    await userEvent.clear(screen.getByLabelText(/search/i))
    await userEvent.type(screen.getByLabelText(/search/i), 'weather')
    expect(screen.queryByText('Apps from the catalog')).toBeNull()
  })
})
