/**
 * System > Custom cards > Integrations (KARTEN-3, KARTEN-11 AC-11): the list of the integrations an administrator
 * described, with logo, name, short name, the number of connections, Edit and Delete, and "Describe an integration".
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { CustomCardsSettings } from './CustomCardsSettings'

const ROW = (extra: Record<string, unknown> = {}) => ({
  short: 'memos', kind: 'custom:memos', name: 'Memos', logo: 'memos', description: 'Notes you keep for yourself.', connections: 2, updated_at: '2026-10-26T10:00:00Z', updated_by: 'admin', ...extra,
})

const world = vi.hoisted(() => ({ rows: [] as unknown[], sent: [] as { url: string; method: string }[] }))

function stub() {
  world.sent = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input).replace(/^.*\/api\/v1/, '')
      const method = init?.method ?? 'GET'
      world.sent.push({ url, method })
      const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } })
      if (method === 'GET' && url === '/own-integrations') return json(world.rows)
      if (method === 'DELETE' && url.startsWith('/own-integrations/')) {
        world.rows = world.rows.filter((one) => (one as { short: string }).short !== decodeURIComponent(url.split('/')[2]))
        return new Response(null, { status: 204 })
      }
      if (method === 'GET' && url === '/cards') return json({ cards: [], limit: 200 })
      return json({})
    }),
  )
}

function Where() {
  return <p>Editor at {useLocation().pathname}</p>
}

function show(at = '/system/cards?tab=integrations') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[at]}>
        <Routes>
          <Route path="/system/cards" element={<CustomCardsSettings />} />
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  world.rows = [ROW(), ROW({ short: 'wiki', kind: 'custom:wiki', name: 'Wiki', logo: '', connections: 0 })]
  stub()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('the Integrations tab', () => {
  it('karten11 ac11: it is a tab of Custom cards with the count, and opens from the address', async () => {
    show()
    expect(await screen.findByRole('tab', { name: /^Integrations\s*2$/ })).toHaveAttribute('aria-selected', 'true')
    expect(await screen.findByTestId('own-integrations')).toBeInTheDocument()
  })

  it('karten11 ac11: each row has the name, the kind, the mark and the number of connections', async () => {
    show()
    const rows = within(await screen.findByTestId('own-integrations')).getAllByRole('listitem')
    expect(rows).toHaveLength(2)
    expect(within(rows[0]).getByText('Memos')).toBeInTheDocument()
    expect(within(rows[0]).getByText('custom:memos', { exact: false })).toBeInTheDocument()
    expect(within(rows[0]).getByText('Custom')).toBeInTheDocument()
    expect(within(rows[0]).getByText('2 connections')).toBeInTheDocument()
    expect(within(rows[1]).getByText('0 connections')).toBeInTheDocument()
  })

  it('karten3 ac12: it says how many of 50 are used', async () => {
    show()
    expect(await screen.findByText('2 of 50 integrations of your own. A change shows at once in every connection of it.')).toBeInTheDocument()
  })

  it('karten3: "Describe an integration" leads to the editor, Edit to the editor of that one', async () => {
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Describe an integration' }))
    expect(await screen.findByText('Editor at /system/custom-cards/integrations/new')).toBeInTheDocument()
  })

  it('karten3: Edit leads to the editor of that integration', async () => {
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Edit Memos' }))
    expect(await screen.findByText('Editor at /system/custom-cards/integrations/memos/edit')).toBeInTheDocument()
  })

  it('karten3 ec6: deleting asks first and says what happens to the connections and the cards', async () => {
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Memos' }))
    const dialog = await screen.findByRole('dialog', { name: 'Delete Memos?' })
    expect(dialog).toHaveTextContent('2 connections use it.')
    expect(dialog).toHaveTextContent('integration missing')
    expect(world.sent.filter((one) => one.method === 'DELETE')).toHaveLength(0)
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(world.sent.filter((one) => one.method === 'DELETE')).toHaveLength(0)
  })

  it('karten3 ec6: confirmed, it is deleted and the row goes', async () => {
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Memos' }))
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(world.sent.filter((one) => one.method === 'DELETE' && one.url === '/own-integrations/memos')).toHaveLength(1))
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Delete Memos' })).toBeNull())
  })

  it('karten3 ec6: one nobody uses says it is gone at once', async () => {
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Wiki' }))
    expect(await screen.findByRole('dialog', { name: 'Delete Wiki?' })).toHaveTextContent('No connection uses it. It is gone at once.')
  })

  it('karten11 ac11: none yet explains what to do and offers the same button', async () => {
    world.rows = []
    show()
    expect(await screen.findByText('No integrations of your own yet')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Describe an integration' }).length).toBeGreaterThan(0)
  })

  it('karten3 ac12: with 50 the button is closed', async () => {
    world.rows = Array.from({ length: 50 }, (_, n) => ROW({ short: `one-${n}`, kind: `custom:one-${n}`, name: `One ${n}` }))
    show()
    await screen.findByTestId('own-integrations')
    for (const button of screen.getAllByRole('button', { name: 'Describe an integration' })) expect(button).toBeDisabled()
  })
})
