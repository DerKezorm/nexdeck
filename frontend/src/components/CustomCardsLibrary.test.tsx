/**
 * Custom cards in the widget library (KARTEN-11 AC-2, AC-12) and in the settings sheet of a placed card.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { FieldSpec } from '../api/types'
import type { LibraryCard } from '../lib/customCards'
import { useAuth } from '../stores/auth'
import { FieldInput } from './FieldInput'
import { WidgetLibrary } from './WidgetLibrary'

const SONARR = { kind: 'sonarr', label: 'Sonarr', icon: 'sonarr' }

const QUEUE: LibraryCard = {
  slug: 'queue-size',
  name: { en: 'Queue', de: 'Warteschlange' },
  description: 'How many items wait.',
  form: 'value',
  version: '1.0.0',
  requires: [SONARR],
  fits: [{ id: 7, name: 'Sonarr main', kind: 'sonarr' }],
}
const WALL: LibraryCard = { ...QUEUE, slug: 'poster-wall', name: 'Poster wall', description: null, form: 'posters', requires: [{ kind: 'plex', label: 'Plex', icon: 'plex' }], fits: [] }

const world = vi.hoisted(() => ({ cards: [] as unknown[], sent: [] as { url: string; method: string; body: Record<string, unknown> | null }[] }))

function stub(cards: LibraryCard[]) {
  world.cards = cards
  world.sent = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input).replace(/^.*\/api\/v1/, '')
      const method = init?.method ?? 'GET'
      world.sent.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null })
      const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } })
      if (url === '/adapters')
        return json([
          { kind: 'core', label: 'Core', category: 'basics', needs_integration: false, fields: [], widgets: [{ kind: 'core.clock', label: 'Clock', description: 'The time.', options: [], default_size: [2, 2], min_size: [1, 1], renderer: 'clock' }] },
          { kind: 'custom', label: 'Custom card', category: 'generic', needs_integration: true, fields: [], widgets: [{ kind: 'custom.value', label: 'Custom number', description: 'One value.', options: [], default_size: [2, 2], min_size: [1, 1], renderer: 'value' }] },
        ])
      if (url === '/integrations') return json([])
      if (url === '/apps') return json([])
      if (url === '/cards/library') return json({ cards: world.cards })
      if (method === 'POST') return json({ widget: { id: 11 } }, 201)
      return json({})
    }),
  )
}

function library(onCreated = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <WidgetLibrary open onClose={vi.fn()} pageId={5} onCreated={onCreated} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return onCreated
}

beforeEach(() => useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin' } as never }))
afterEach(() => vi.unstubAllGlobals())

describe('the library', () => {
  it('karten11 ac2: has a section "Custom cards" with the cards that fit a connection, by the name of the card', async () => {
    stub([QUEUE, WALL])
    library()
    const section = (await screen.findByRole('heading', { name: 'Custom cards' })).closest('section')!
    expect(within(section).getByText('Queue')).toBeInTheDocument()
    expect(within(section).getByText('How many items wait.')).toBeInTheDocument()
    expect(within(section).queryByText('Poster wall')).toBeNull()
    expect(screen.queryByText(/Custom number/)).toBeNull()
    expect(screen.getByText('Clock')).toBeInTheDocument()
  })

  it('karten11 ac2: a click places the card by its form and short name on the one connection that fits', async () => {
    stub([QUEUE])
    const created = library()
    await userEvent.click(await screen.findByRole('button', { name: /Queue/ }))
    await waitFor(() => expect(created).toHaveBeenCalledWith(11))
    const placed = world.sent.find((one) => one.method === 'POST')!
    expect(placed.url).toBe('/pages/5/widgets')
    expect(placed.body).toMatchObject({ kind: 'custom.value', integration_id: 7, options: { card: 'queue-size' }, title: '' })
  })

  it('karten11 ac2: the form of the card decides the kind it is placed as', async () => {
    stub([{ ...QUEUE, slug: 'recent', name: 'Recent', form: 'list' }])
    library()
    await userEvent.click(await screen.findByRole('button', { name: /Recent/ }))
    await waitFor(() => expect(world.sent.some((one) => one.method === 'POST')).toBe(true))
    expect(world.sent.find((one) => one.method === 'POST')!.body).toMatchObject({ kind: 'custom.list', options: { card: 'recent' } })
  })

  it('karten11 ac2: with several connections that fit, the connection is picked first', async () => {
    stub([{ ...QUEUE, fits: [{ id: 7, name: 'Sonarr main', kind: 'sonarr' }, { id: 9, name: 'Sonarr kids', kind: 'sonarr' }] }])
    const created = library()
    await userEvent.click(await screen.findByRole('button', { name: /Queue/ }))
    expect(world.sent.some((one) => one.method === 'POST')).toBe(false)
    await userEvent.selectOptions(screen.getByRole('combobox'), '9')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() => expect(created).toHaveBeenCalled())
    expect(world.sent.find((one) => one.method === 'POST')!.body).toMatchObject({ integration_id: 9 })
  })

  it('karten11 ac12: a card without a fitting connection stands apart, with "Add the integration"', async () => {
    stub([QUEUE, WALL])
    library()
    const section = (await screen.findByRole('heading', { name: "Need an integration you don't have" })).closest('section')!
    expect(within(section).getByText('Poster wall')).toBeInTheDocument()
    expect(within(section).queryByText('Queue')).toBeNull()
    expect(within(section).getByRole('link', { name: 'Add the integration' })).toHaveAttribute('href', '/system/integrations?add=plex')
  })

  it('karten11 ac12: somebody who is no administrator is told to ask one instead of being sent to a page he cannot use', async () => {
    useAuth.setState({ user: { id: 2, username: 'ann', role: 'user' } as never })
    stub([WALL])
    library()
    expect(await screen.findByText('Ask an administrator to add a Plex integration.')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Add the integration' })).toBeNull()
  })

  it('karten11 ac2: the search finds a custom card by its name', async () => {
    stub([QUEUE, WALL])
    library()
    await screen.findByText('Queue')
    await userEvent.type(screen.getByRole('textbox'), 'poster')
    expect(screen.queryByText('Queue')).toBeNull()
    expect(screen.getByText('Poster wall')).toBeInTheDocument()
  })
})

describe('the card field of a placed custom card', () => {
  const spec = { name: 'card', label: 'Card', type: 'text', required: true, secret: false, default: null, help: '', placeholder: '', options: [], helper: 'custom-card' } as FieldSpec

  it('karten11: shows the name of the card with its short name, and no text field', async () => {
    stub([QUEUE])
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <FieldInput spec={spec} value="queue-size" onChange={vi.fn()} />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(screen.getByTestId('custom-card-name')).toHaveTextContent('Queue'))
    expect(screen.getByTestId('custom-card-name')).toHaveTextContent('queue-size')
    expect(screen.queryByRole('textbox')).toBeNull()
  })

  it('karten11 ac6: a card that is no longer saved shows its short name', async () => {
    stub([])
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <FieldInput spec={spec} value="gone-card" onChange={vi.fn()} />
      </QueryClientProvider>,
    )
    expect(await screen.findByText('gone-card')).toBeInTheDocument()
  })
})
