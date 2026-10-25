/**
 * System > Custom cards (KARTEN-11): the list with its tabs and counts, who may place a card, where it stands, the way to
 * build, copy and delete one, and what the sheet says about a text with problems or a card deleted meanwhile.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { STARTER, type CustomCardRow } from '../../lib/customCards'
import { CustomCardsSettings } from './CustomCardsSettings'

const SONARR = { kind: 'sonarr', label: 'Sonarr', icon: 'sonarr' }
const RADARR = { kind: 'radarr', label: 'Radarr', icon: 'radarr' }

const card = (over: Partial<CustomCardRow> = {}): CustomCardRow => ({
  slug: 'queue-size',
  name: { en: 'Queue', de: 'Warteschlange' },
  description: null,
  form: 'value',
  version: '1.0.0',
  author: null,
  requires: [SONARR, RADARR],
  origin: 'local',
  shop_version: '',
  boards: [],
  users_may_place: false,
  updated_at: '2026-10-25T10:00:00Z',
  ...over,
})

type Sent = { url: string; method: string; body: Record<string, unknown> | null }

const world = vi.hoisted(() => ({ cards: [] as unknown[], sent: [] as { url: string; method: string; body: Record<string, unknown> | null }[], answers: {} as Record<string, { status: number; body: unknown }> }))

function stub(cards: CustomCardRow[], answers: Record<string, { status: number; body: unknown }> = {}) {
  world.cards = cards
  world.sent = []
  world.answers = answers
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input).replace(/^.*\/api\/v1/, '')
      const method = init?.method ?? 'GET'
      world.sent.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null })
      const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } })
      const given = world.answers[`${method} ${url}`]
      if (given) return json(given.body, given.status)
      if (method === 'GET' && url === '/cards') return json({ cards: world.cards, limit: 200 })
      if (method === 'GET' && url.startsWith('/cards/')) return json({ ...(world.cards[0] as object), yaml: 'nexdeck-card: 1\nslug: queue-size\n' })
      return json({}, method === 'POST' ? 201 : 200)
    }),
  )
}

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CustomCardsSettings />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const sent = (method: string, url: string) => world.sent.filter((one: Sent) => one.method === method && one.url === url)

beforeEach(() => stub([]))
afterEach(async () => {
  vi.unstubAllGlobals()
  await i18next.changeLanguage('en')
})

describe('the list', () => {
  it('karten11 ac1: says name, form, source, where it came from, where it stands and whether users may place it', async () => {
    stub([
      card({ boards: [{ id: 1, slug: 'home', name: 'Home' }, { id: 2, slug: 'wall', name: 'Wall' }] }),
      card({ slug: 'speed', name: 'Speed', form: 'list', requires: [RADARR], origin: 'shop', shop_version: '2.1.0', author: 'Example Author', users_may_place: true }),
    ])
    show()
    const row = (await screen.findByText('Queue')).closest('li')!
    expect(within(row).getByText('Number')).toBeInTheDocument()
    expect(within(row).getByText('Sonarr, Radarr')).toBeInTheDocument()
    expect(within(row).getByText('Local')).toBeInTheDocument()
    expect(within(row).getByRole('button', { name: '2 boards' })).toBeInTheDocument()
    expect(within(row).getByRole('switch')).toHaveAttribute('aria-checked', 'false')
    const shop = screen.getByText('Speed').closest('li')!
    expect(within(shop).getByText('Card shop · 2.1.0')).toBeInTheDocument()
    expect(within(shop).getByText('Example Author')).toBeInTheDocument()
    expect(within(shop).getByText('Not placed')).toBeInTheDocument()
    expect(within(shop).getByRole('switch')).toHaveAttribute('aria-checked', 'true')
  })

  it('karten11 ac1: the name is the one the author wrote in the language of the viewer', async () => {
    await i18next.changeLanguage('de')
    stub([card()])
    show()
    expect(await screen.findByText('Warteschlange')).toBeInTheDocument()
  })

  it('karten11 ac10: has "Build a card" on top, the four tabs with a count on the first two, and says how many of 200 are used', async () => {
    stub([card(), card({ slug: 'two', name: 'Two' })])
    show()
    await screen.findByText('Queue')
    expect(screen.getByRole('button', { name: /build a card/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^import$/i })).toBeNull()
    expect(screen.getByRole('tab', { name: /^Cards\s*2$/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: /^Integrations\s*0$/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Card shop' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'My submissions' })).toBeInTheDocument()
    expect(screen.getByText('2 of 200 custom cards. A change to a card shows on every board at once.')).toBeInTheDocument()
  })

  it('karten11 ac10: the tabs that come later say so in one sentence', async () => {
    stub([card()])
    show()
    await screen.findByText('Queue')
    for (const name of ['Integrations', 'Card shop', 'My submissions']) {
      await userEvent.click(screen.getByRole('tab', { name: new RegExp(name) }))
      expect(screen.getByText('This part of Custom cards comes with a later version of nexdeck.')).toBeInTheDocument()
      expect(screen.queryByText('Queue')).toBeNull()
    }
  })

  it('karten11 ec2: an empty list explains what custom cards are, with "Build a card" and "Open the Card shop"', async () => {
    show()
    expect(await screen.findByText(/A custom card shows what you pick out of the answers of a service/)).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /build a card/i }).length).toBeGreaterThan(0)
    await userEvent.click(screen.getByRole('button', { name: 'Open the Card shop' }))
    expect(screen.getByRole('tab', { name: 'Card shop' })).toHaveAttribute('aria-selected', 'true')
  })

  it('karten11 ec3: a card on many boards shows the number, and a click shows the boards', async () => {
    stub([card({ boards: [{ id: 1, slug: 'home', name: 'Home' }, { id: 2, slug: 'wall', name: 'Wall' }, { id: 3, slug: 'lab', name: 'Lab' }] })])
    show()
    await userEvent.click(await screen.findByRole('button', { name: '3 boards' }))
    const list = screen.getByRole('list', { name: 'Boards with Queue' })
    expect(within(list).getAllByRole('link').map((one) => [one.textContent, one.getAttribute('href')])).toEqual([
      ['Home', '/b/home'],
      ['Wall', '/b/wall'],
      ['Lab', '/b/lab'],
    ])
  })

  it('karten11 ec5: from twenty cards on there is a search by name and source, below twenty there is none', async () => {
    const many = (count: number) => Array.from({ length: count }, (_, at) => card({ slug: `card-${at}`, name: `Card ${at}`, requires: [at === 7 ? RADARR : SONARR] }))
    stub(many(19))
    const small = show()
    await screen.findByText('Card 0')
    expect(screen.queryByRole('textbox', { name: 'Search by name or source' })).toBeNull()
    small.unmount()
    stub(many(20))
    show()
    const search = await screen.findByRole('textbox', { name: 'Search by name or source' })
    await userEvent.type(search, 'radarr')
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
    expect(screen.getByText('Card 7')).toBeInTheDocument()
    await userEvent.clear(search)
    await userEvent.type(search, 'card 1')
    expect(screen.getByText('Card 12')).toBeInTheDocument()
    expect(screen.queryByText('Card 2')).toBeNull()
  })
})

describe('changing a card', () => {
  it('karten11 ac3: the switch lets users place a card, and takes it back', async () => {
    stub([card()])
    show()
    await userEvent.click(await screen.findByRole('switch', { name: 'Users may place Queue' }))
    await waitFor(() => expect(sent('PUT', '/cards/queue-size/users')).toHaveLength(1))
    expect(sent('PUT', '/cards/queue-size/users')[0].body).toEqual({ allowed: true })
  })

  it('karten11 ac5: duplicate asks for a copy of the card', async () => {
    stub([card()])
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Duplicate Queue' }))
    await waitFor(() => expect(sent('POST', '/cards/queue-size/copy')).toHaveLength(1))
  })

  it('karten11 ac6: delete asks first, says on how many boards the card stands, and then deletes', async () => {
    stub([card({ boards: [{ id: 1, slug: 'home', name: 'Home' }] })])
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Queue' }))
    expect(screen.getByText(/It stands on 1 board\. There it will say that the definition is missing/)).toBeInTheDocument()
    expect(sent('DELETE', '/cards/queue-size')).toHaveLength(0)
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(sent('DELETE', '/cards/queue-size')).toHaveLength(1))
  })

  it('karten11 ac6: a card on no board is gone at once and the question says so', async () => {
    stub([card()])
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Queue' }))
    expect(screen.getByText('No board shows it. It is gone at once.')).toBeInTheDocument()
  })
})

describe('the sheet', () => {
  it('karten11: "Build a card" opens the text of a working card and saves it as a new one', async () => {
    stub([card()])
    show()
    await userEvent.click(await screen.findByRole('button', { name: /build a card/i }))
    const text = await screen.findByRole('textbox', { name: /Card text/ })
    expect(text).toHaveValue(STARTER)
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(sent('POST', '/cards')).toHaveLength(1))
    expect(sent('POST', '/cards')[0].body).toEqual({ yaml: STARTER })
  })

  it('karten11: "Edit" opens the saved text and saves it over the same card', async () => {
    stub([card()])
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Edit Queue' }))
    const text = await screen.findByRole('textbox', { name: /Card text/ })
    expect(text).toHaveValue('nexdeck-card: 1\nslug: queue-size\n')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(sent('PUT', '/cards/queue-size')).toHaveLength(1))
  })

  it('karten11: a text with problems stays open and lists every problem by line and field', async () => {
    stub([card()], {
      'POST /cards': {
        status: 400,
        body: {
          detail: {
            code: 'card_invalid',
            message: 'The field version is required.',
            problems: [
              { code: 'card_missing_field', message: 'The field version is required.', path: 'version', line: 3, params: { field: 'version' } },
              { code: 'card_something_new', message: 'A sentence only the server knows.', path: 'rules[0]', line: 9, params: {} },
            ],
          },
        },
      },
    })
    show()
    await userEvent.click(await screen.findByRole('button', { name: /build a card/i }))
    await userEvent.click(await screen.findByRole('button', { name: 'Save' }))
    expect(await screen.findByText('The field version is required.')).toBeInTheDocument()
    expect(screen.getByText('Line 3')).toBeInTheDocument()
    expect(screen.getByText('A sentence only the server knows.')).toBeInTheDocument()
    expect(screen.getByText('Line 9')).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: /Card text/ })).toBeInTheDocument()
  })

  it('karten11 ec6: saving a card deleted meanwhile says so and offers "Save as new"', async () => {
    stub([card()], { 'PUT /cards/queue-size': { status: 404, body: { detail: { code: 'card_deleted', message: 'This card was deleted meanwhile.' } } } })
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Edit Queue' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Save' }))
    expect(await screen.findByText('Deleted meanwhile')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Save as new' }))
    await waitFor(() => expect(sent('POST', '/cards')).toHaveLength(1))
    expect(sent('POST', '/cards')[0].body).toEqual({ yaml: 'nexdeck-card: 1\nslug: queue-size\n' })
  })
})
