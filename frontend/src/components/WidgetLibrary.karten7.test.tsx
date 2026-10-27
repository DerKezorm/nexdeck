/**
 * A card put together from blocks in the library opened from key figures (KARTEN-7 AC-8): it is offered when it names
 * its main value, like "A number", and not without one.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { LibraryCard } from '../lib/customCards'
import { useAuth } from '../stores/auth'
import { WidgetLibrary } from './WidgetLibrary'

const SERVER = { kind: 'beszel', label: 'Beszel', icon: 'beszel' }
const BASE: LibraryCard = { slug: 'glance', name: 'Server at a glance', description: null, form: 'builder', version: '1.0.0', requires: [SERVER], fits: [{ id: 7, name: 'Beszel', kind: 'beszel' }] }

function library(cards: LibraryCard[], numbersOnly: boolean) {
  useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin' } as never, loading: false })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input).replace(/^.*\/api\/v1/, '')
      const json = (value: unknown) => new Response(JSON.stringify(value), { status: 200, headers: { 'content-type': 'application/json' } })
      if (url === '/cards/library') return json({ cards })
      return json([])
    }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <WidgetLibrary open onClose={() => undefined} pageId={1} onCreated={() => undefined} numbersOnly={numbersOnly} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('the library opened from key figures', () => {
  it('karten7 ac8 offers a card of blocks that names its main value', async () => {
    library([{ ...BASE, main: 'cpu' }], true)
    await waitFor(() => expect(screen.getByRole('button', { name: /Server at a glance/ })).toBeInTheDocument())
  })

  it('karten7 ac8 does not offer a card of blocks without a main value', async () => {
    library([{ ...BASE, slug: 'plain', name: 'Plain blocks' }, { ...BASE, main: 'cpu' }], true)
    await waitFor(() => expect(screen.getByRole('button', { name: /Server at a glance/ })).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /Plain blocks/ })).toBeNull()
  })

  it('karten7 ac8 offers every card of blocks when the library is opened as usual', async () => {
    library([{ ...BASE, slug: 'plain', name: 'Plain blocks' }], false)
    await waitFor(() => expect(screen.getByRole('button', { name: /Plain blocks/ })).toBeInTheDocument())
  })
})
