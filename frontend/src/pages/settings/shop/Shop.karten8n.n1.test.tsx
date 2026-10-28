/** N1 (Etappe 8): the list of cards and the own integrations ask again once a catalog was read. */
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import i18next from 'i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { get } from '../../../api/client'
import { calls, entry, renderWith, reset, STATE_ON, stub, world } from '../../../test/shopWorld'
import { CustomCardsSettings } from '../CustomCardsSettings'
import { useShopUpdates } from './hooks'

beforeEach(() => {
  localStorage.clear()
  reset([entry()], STATE_ON)
  stub()
})
afterEach(async () => {
  vi.unstubAllGlobals()
  await i18next.changeLanguage('en')
})

/** The order in which the server was asked: "METHOD url". */
const order = () => world.asked.map((one) => `${one.method} ${one.url}`)

/** A page that has the list of cards, and later (the notes on the board) asks for the updates. */
function Board({ updates }: { updates: boolean }) {
  return (
    <>
      <Cards />
      {updates && <Updates />}
    </>
  )
}
function Cards() {
  useQuery({ queryKey: ['custom-cards'], queryFn: () => get('/cards') })
  return null
}
function Updates() {
  useShopUpdates()
  return null
}

/** The list of cards is in, then the updates are read. */
async function boardThenUpdates() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const page = (updates: boolean) => (
    <QueryClientProvider client={client}>
      <Board updates={updates} />
    </QueryClientProvider>
  )
  const shown = render(page(false))
  await waitFor(() => expect(calls('GET', '/cards')).toHaveLength(1))
  await new Promise((resolve) => setTimeout(resolve, 20))
  shown.rerender(page(true))
}

describe('N1: the lists ask again after a catalog was read', () => {
  it('karten8n_n1: the list of cards and the own integrations are asked again once the catalog is in', async () => {
    renderWith(<CustomCardsSettings />, '/system/cards?tab=shop')
    await screen.findByTestId('shop-list')
    await waitFor(() => expect(calls('GET', '/cards').length).toBeGreaterThanOrEqual(2))
    await waitFor(() => expect(calls('GET', '/own-integrations').length).toBeGreaterThanOrEqual(2))
    const asked = order()
    expect(asked.lastIndexOf('GET /cards')).toBeGreaterThan(asked.indexOf('GET /workshop/catalog'))
  })

  it('karten8n_n1: the same when the updates were read (the board and the bell ask for those)', async () => {
    await boardThenUpdates()
    await waitFor(() => expect(calls('GET', '/cards').length, order().join(', ')).toBeGreaterThanOrEqual(2))
    const asked = order()
    expect(asked.lastIndexOf('GET /cards')).toBeGreaterThan(asked.indexOf('GET /workshop/updates'))
  })

  it('karten8n_n1: when the shop knows no catalog yet, nothing is asked again', async () => {
    world.updates = { enabled: true, catalog_known: false, updates: [], removed: [] }
    await boardThenUpdates()
    await waitFor(() => expect(calls('GET', '/workshop/updates')).toHaveLength(1))
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(calls('GET', '/cards')).toHaveLength(1)
  })
})
