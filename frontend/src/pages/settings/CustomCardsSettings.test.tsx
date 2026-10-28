/**
 * System > Custom cards (KARTEN-11): the list with its tabs and counts, who may place a card, where it stands, the way to
 * build, copy and delete one. Building and editing happen in the editor (`pages/cardEditor`), which has its own tests.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import deScreen from '../../i18n/de.json'
import { answerWithFile, catchDownloads } from '../../test/downloads'
import type { CustomCardRow } from '../../lib/customCards'
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
      if (method === 'GET' && url === '/own-integrations') return json([])
      if (method === 'GET' && url === '/cards') return json({ cards: world.cards, limit: 200 })
      if (method === 'GET' && url.startsWith('/cards/')) return json({ ...(world.cards[0] as object), yaml: 'nexdeck-card: 1\nslug: queue-size\n' })
      return json({}, method === 'POST' ? 201 : 200)
    }),
  )
}

/** Stands in for the editor's page: says where the list led. */
function Where() {
  return <p>Editor at {useLocation().pathname}</p>
}

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/system/cards']}>
        <Routes>
          <Route path="/system/cards" element={<CustomCardsSettings />} />
          <Route path="*" element={<Where />} />
        </Routes>
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
    const importing = screen.getByRole('button', { name: /^Import\./ })
    expect(importing).toBeDisabled()
    expect(importing).toHaveAttribute('title', 'Importing a card comes with a later version of nexdeck.')
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
    for (const name of ['Card shop', 'My submissions']) {
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

  it('karten11 ac8: a copy refused because there are 200 cards says so in the language of the viewer', async () => {
    i18next.addResourceBundle('de', 'translation', deScreen, true, true)
    await i18next.changeLanguage('de')
    stub([card()], { 'POST /cards/queue-size/copy': { status: 409, body: { detail: { code: 'too_many_cards', message: 'There are 200 custom cards already.' } } } })
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Warteschlange duplizieren' }))
    expect(await screen.findByText('Es gibt schon 200 eigene Karten, mehr hält nexdeck nicht. Lösche zuerst eine.')).toBeInTheDocument()
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

describe('the way into the editor', () => {
  it('karten9 decision 9: "Build a card" leads to the editor of a new card', async () => {
    stub([card()])
    show()
    await userEvent.click(await screen.findByRole('button', { name: /build a card/i }))
    expect(await screen.findByText('Editor at /system/custom-cards/new')).toBeInTheDocument()
  })

  it('karten9 decision 9: "Edit" leads to the editor of that card, and the old window for pasting is gone', async () => {
    stub([card()])
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Edit Queue' }))
    expect(await screen.findByText('Editor at /system/custom-cards/queue-size/edit')).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: /Card text/ })).toBeNull()
    expect(sent('GET', '/cards/queue-size')).toHaveLength(0)
  })
})

describe('export', () => {
  const asked = (mock: ReturnType<typeof answerWithFile>, address: string) => mock.mock.calls.filter(([input]) => String(input).endsWith(address))

  it('karten12 ac1: the export of a card asks for its file and saves it under the name the server gave', async () => {
    const saved = catchDownloads()
    stub([card()])
    const fetched = answerWithFile('/cards/queue-size/export', 'nexdeck-card: 1\nslug: queue-size\n', { 'Content-Type': 'text/yaml', 'Content-Disposition': 'attachment; filename="queue-today.nexdeck.yaml"' })
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Export Queue' }))
    await waitFor(() => expect(saved.names).toEqual(['queue-today.nexdeck.yaml']))
    expect(asked(fetched, '/cards/queue-size/export')).toHaveLength(1)
    saved.restore()
  })

  it('karten12 ac1: a file without a name from the server is saved as <short name>.nexdeck.yaml', async () => {
    const saved = catchDownloads()
    stub([card()])
    answerWithFile('/cards/queue-size/export', 'nexdeck-card: 1\n', { 'Content-Type': 'text/yaml' })
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Export Queue' }))
    await waitFor(() => expect(saved.names).toEqual(['queue-size.nexdeck.yaml']))
    saved.restore()
  })

  it('karten12 ac1: a name from the server with a path in it is cut down to the file name', async () => {
    const saved = catchDownloads()
    stub([card()])
    answerWithFile('/cards/queue-size/export', 'x', { 'Content-Disposition': 'attachment; filename="..\\..\\evil/queue.nexdeck.yaml"' })
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Export Queue' }))
    await waitFor(() => expect(saved.names).toEqual(['queue.nexdeck.yaml']))
    saved.restore()
  })

  it('karten12 ac1: a refused export says why and saves nothing', async () => {
    const saved = catchDownloads()
    stub([card()])
    answerWithFile('/cards/queue-size/export', JSON.stringify({ detail: { code: 'forbidden', message: 'Only administrators may export.' } }), { 'Content-Type': 'application/json' }, 403)
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Export Queue' }))
    expect(await screen.findByText('Only administrators may export.')).toBeInTheDocument()
    expect(saved.names).toEqual([])
    saved.restore()
  })
})
