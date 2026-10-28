/**
 * A stand-in for the Card shop routes (`/api/v1/workshop/...`) for the tests of the shop screens: what the server
 * would answer, what was asked, and a small entry to start from.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

import type { ShopEntry, ShopState, ShopUpdates } from '../lib/cardShop'

export type Asked = { url: string; method: string; body: Record<string, unknown> | null }
export type Given = { status: number; body: unknown }

export const world = {
  state: null as unknown as ShopState,
  catalog: null as unknown as { fetched_at: string; generated_at: string; entries: ShopEntry[]; warning: { code: string; message: string } | null },
  updates: null as unknown as ShopUpdates,
  asked: [] as Asked[],
  /** Fixed answers by "METHOD /path" (the part after /api/v1), taken before anything else. */
  given: {} as Record<string, Given | ((asked: Asked) => Given)>,
  /** Whatever else a test wants to answer, tried after `given`; return undefined to pass. */
  other: null as null | ((asked: Asked) => Given | undefined),
}

export const STATE_ON: ShopState = { enabled: true, repo: 'DerKezorm/nexdeck-workshop', token_set: false, risk_acknowledged: false, nexdeck_version: '0.51.0', catalog: { fetched_at: '2026-10-28T10:00:00Z', generated_at: '2026-10-28T09:00:00Z', count: 1 } }
export const STATE_OFF: ShopState = { ...STATE_ON, enabled: false, catalog: null }

export const entry = (over: Partial<ShopEntry> = {}): ShopEntry => ({
  id: '123/queue-size',
  author_id: '123',
  slug: 'queue-size',
  type: 'card',
  name: { en: 'Queue size', de: 'Warteschlange' },
  description: 'Shows how many episodes wait in the queue.',
  author: { id: '123', login: 'someone' },
  version: '1.2.0',
  min_nexdeck: null,
  category: 'media',
  requires: [{ kind: 'sonarr', label: 'Sonarr', icon: 'sonarr' }],
  class: 'read',
  reads: [{ kind: 'sonarr', path: '/api/v3/queue' }],
  buttons: [],
  thumbs: 12,
  discussion: null,
  based_on: null,
  updated_at: '2026-10-20T10:00:00Z',
  license: 'MIT',
  removed: null,
  needs_newer: false,
  fits: true,
  connections: [{ id: 3, name: 'Sonarr home', kind: 'sonarr' }],
  installed: null,
  images: { light: '/api/v1/workshop/entries/123/queue-size/image/light', dark: '/api/v1/workshop/entries/123/queue-size/image/dark' },
  ...over,
})

export function reset(entries: ShopEntry[] = [entry()], state: ShopState = STATE_ON) {
  world.state = { ...state }
  world.catalog = { fetched_at: '2026-10-28T10:00:00Z', generated_at: '2026-10-28T09:00:00Z', entries, warning: null }
  world.updates = { enabled: state.enabled, catalog_known: true, updates: [], removed: [] }
  world.asked = []
  world.given = {}
  world.other = null
}

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } })
export const failure = (status: number, code: string, message = code, extra: Record<string, unknown> = {}): Given => ({ status, body: { detail: { code, message, ...extra } } })

/** Installs the stand-in `fetch`. Unknown routes answer an empty object. */
export function stub() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input).replace(/^.*\/api\/v1/, '')
      const method = init?.method ?? 'GET'
      const asked: Asked = { url, method, body: init?.body ? JSON.parse(String(init.body)) : null }
      world.asked.push(asked)
      const key = `${method} ${url}`
      const given = world.given[key]
      if (given) {
        const answer = typeof given === 'function' ? given(asked) : given
        return json(answer.body, answer.status)
      }
      const more = world.other?.(asked)
      if (more) return json(more.body, more.status)
      if (key === 'GET /workshop/state') return json(world.state)
      if (key === 'PUT /workshop/settings') {
        world.state = { ...world.state, enabled: Boolean(asked.body?.enabled) }
        world.updates = { ...world.updates, enabled: world.state.enabled }
        return json(world.state)
      }
      if (key === 'GET /workshop/catalog') return world.state.enabled ? json(world.catalog) : json({ detail: { code: 'shop_off', message: 'The Card shop is off.' } }, 409)
      if (key === 'GET /workshop/updates') return json(world.updates)
      if (key === 'GET /cards') return json({ cards: [], limit: 200 })
      if (key === 'GET /own-integrations') return json([])
      if (key === 'GET /boards') return json([])
      if (key === 'GET /cards/library') return json({ cards: [] })
      return json({}, method === 'POST' ? 201 : 200)
    }),
  )
}

export const calls = (method: string, url: string) => world.asked.filter((one) => one.method === method && one.url === url)
/** Every request that would make the server ask GitHub (the catalog and the files of entries). */
export const githubWasAsked = () => world.asked.filter((one) => one.url.startsWith('/workshop/catalog') || one.url.startsWith('/workshop/entries'))

export function renderWith(node: ReactElement, at = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[at]}>{node}</MemoryRouter>
    </QueryClientProvider>,
  )
}
