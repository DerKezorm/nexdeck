/**
 * The card editor's page for the tests of its steps (KARTEN-9): one saved card opened by its address, with the server
 * stubbed. Answers are given per "METHOD /path"; what was sent is kept in `world.sent`.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { vi } from 'vitest'

import { CardEditorPage } from '../pages/cardEditor/CardEditorPage'
import { useCardEditor } from '../pages/cardEditor/store'
import { useAuth } from '../stores/auth'

export type Sent = { url: string; method: string; body: Record<string, unknown> | null }
export type Answer = { status: number; body: unknown } | ((body: Record<string, unknown> | null) => { status: number; body: unknown })

export const world: { sent: Sent[]; answers: Record<string, Answer> } = { sent: [], answers: {} }

export const SOURCES = [
  { kind: 'sonarr', label: 'Sonarr', icon: 'sonarr' },
  { kind: 'jellyfin', label: 'Jellyfin', icon: 'jellyfin' },
  { kind: 'homeassistant', label: 'Home Assistant', icon: 'homeassistant' },
]

export const INTEGRATIONS = [
  { id: 7, kind: 'sonarr', name: 'Sonarr (NAS)', label: 'Sonarr', icon: 'sonarr', config: {}, enabled: true },
  { id: 8, kind: 'jellyfin', name: 'Jellyfin', label: 'Jellyfin', icon: 'jellyfin', config: {}, enabled: true },
  { id: 9, kind: 'sonarr', name: 'Sonarr (old)', label: 'Sonarr', icon: 'sonarr', config: {}, enabled: false },
]

/** Stub the server with a card `text` saved under `queue` and the answers given. */
export function stub(text: string, answers: Record<string, Answer> = {}) {
  world.sent = []
  world.answers = answers
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input).replace(/^.*\/api\/v1/, '')
      const method = init?.method ?? 'GET'
      const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null
      world.sent.push({ url, method, body })
      const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } })
      const given = world.answers[`${method} ${url}`]
      if (given) {
        const one = typeof given === 'function' ? given(body) : given
        return json(one.body, one.status)
      }
      if (method === 'GET' && url === '/cards/queue') return json({ slug: 'queue', yaml: text, updated_at: '2026-10-25T10:00:00Z' })
      if (method === 'GET' && url === '/cards/sources') return json(SOURCES)
      if (method === 'GET' && url === '/integrations') return json(INTEGRATIONS)
      if (method === 'POST' && url === '/cards/check') return json({ ok: true })
      if (method === 'POST' && url === '/cards/preview') return json({ status: 'ok', primary: { value: 1, text: '1', format: 'number' }, meta: { custom: true } })
      if (method === 'GET') return json([])
      return json({})
    }),
  )
}

export const sent = (method: string, url: string) => world.sent.filter((one) => one.method === method && one.url === url)

/** Node's own half-made localStorage hides jsdom's in this runner; a plain map stands in. */
export function memoryStorage(): Storage {
  const items = new Map<string, string>()
  return {
    get length() {
      return items.size
    },
    clear: () => items.clear(),
    getItem: (key) => items.get(key) ?? null,
    key: (index) => [...items.keys()][index] ?? null,
    removeItem: (key) => void items.delete(key),
    setItem: (key, value) => void items.set(key, String(value)),
  }
}

export function prepare() {
  vi.stubGlobal('localStorage', memoryStorage())
  useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin' } as never, loading: false })
  useCardEditor.setState({ now: () => Date.now() })
}

/**
 * Open the saved card and wait for its editor, in "All settings" (the steps these tests are about) unless the guided
 * way is asked for. A card the guided way can show opens there, as it does for its author (umbau U1).
 */
export async function openCard(name: string, view: 'guided' | 'editor' = 'editor') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const rendered = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/system/custom-cards/queue/edit']}>
        <Routes>
          <Route path="/system/custom-cards/:slug/edit" element={<CardEditorPage />} />
          <Route path="*" element={<p>Somewhere else</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  await screen.findByRole('heading', { name, level: 1 })
  if (view === 'editor' && useCardEditor.getState().view === 'guided') await userEvent.click(screen.getByRole('button', { name: /^(All settings|Alle Einstellungen|Todos los ajustes|Tous les réglages|Tutte le impostazioni)$/ }))
  return rendered
}

/** Open a new card, which begins in the guided way, and wait for its first step. */
export async function openNew() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const rendered = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/system/custom-cards/new']}>
        <Routes>
          <Route path="/system/custom-cards/new" element={<CardEditorPage />} />
          <Route path="/system/custom-cards/:slug/edit" element={<CardEditorPage />} />
          <Route path="*" element={<p>Somewhere else</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  await screen.findByRole('heading', { level: 2, name: /Which service is the card for\?|Für welchen Dienst ist die Karte\?/ })
  return rendered
}

export const editor = () => useCardEditor.getState()
