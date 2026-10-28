/**
 * Importing a board file that carries custom cards (KARTEN-12 AC-6, AC-7): the section "Custom cards in this board"
 * says what is missing, the same and different; only an administrator can have the missing ones created, and
 * everyone else's import asks for none.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuth } from '../../stores/auth'
import { BoardsSettings } from './BoardsSettings'

const FILE = 'nexdeck: 1\nboard:\n  name: Shared\ncustom_cards: []\n'

const DEFINITIONS = [
  { type: 'card', id: 'queue', name: 'Queue', state: 'missing' },
  { type: 'card', id: 'speed', name: { en: 'Speed', de: 'Tempo' }, state: 'same' },
  { type: 'integration', id: 'memos', name: 'Memos', state: 'different' },
]

type Sent = { url: string; method: string; body: Record<string, unknown> | null }
const world = vi.hoisted(() => ({ sent: [] as { url: string; method: string; body: Record<string, unknown> | null }[], check: { status: 200, body: {} as unknown } }))

function stub(definitions: unknown[] | null) {
  world.sent = []
  world.check = definitions === null ? { status: 400, body: { detail: { code: 'invalid_yaml', message: 'Not a board file.' } } } : { status: 200, body: { definitions } }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input).replace(/^.*\/api\/v1/, '')
      const method = init?.method ?? 'GET'
      world.sent.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null })
      const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } })
      if (method === 'POST' && url === '/boards/import/check') return json(world.check.body, world.check.status)
      if (method === 'POST' && url === '/boards/import') return json({ slug: 'shared' })
      return json([])
    }),
  )
}

const sent = (method: string, url: string) => world.sent.filter((one: Sent) => one.method === method && one.url === url)

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <BoardsSettings />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function paste(text = FILE) {
  const field = await screen.findByRole('textbox', { name: 'Import a board' })
  await userEvent.click(field)
  await userEvent.paste(text)
}

const importButton = () => screen.getAllByRole('button', { name: 'Import' }).at(-1)!

const as = (role: 'admin' | 'user') => useAuth.setState({ user: { id: role === 'admin' ? 1 : 2, username: role, role } as never })

beforeEach(() => as('admin'))
afterEach(() => vi.unstubAllGlobals())

describe('a board file with custom cards', () => {
  it('karten12 ac6: an administrator sees what is missing, the same and different, with "Create the missing ones" ticked', async () => {
    stub(DEFINITIONS)
    show()
    await paste()
    const section = await screen.findByTestId('board-definitions')
    expect(sent('POST', '/boards/import/check')[0].body).toEqual({ yaml_text: FILE })
    expect(within(section).getByRole('heading', { name: 'Custom cards in this board' })).toBeInTheDocument()
    const rows = within(section).getAllByRole('listitem').map((one) => one.textContent)
    expect(rows).toEqual(['CardQueuemissing', 'CardSpeedalready here', 'IntegrationMemosdiffers, yours is kept'])
    expect(within(section).getByRole('checkbox', { name: 'Create the missing ones' })).toBeChecked()
  })

  it('karten12 ac6: with the tick the import asks for the missing ones to be created, without it not', async () => {
    stub(DEFINITIONS)
    show()
    await paste()
    await userEvent.click(await screen.findByRole('checkbox', { name: 'Create the missing ones' }))
    await userEvent.click(importButton())
    await waitFor(() => expect(sent('POST', '/boards/import')).toHaveLength(1))
    expect(sent('POST', '/boards/import')[0].body).toEqual({ yaml_text: FILE, definitions: 'skip' })

    await userEvent.click(screen.getByRole('checkbox', { name: 'Create the missing ones' }))
    await userEvent.click(importButton())
    await waitFor(() => expect(sent('POST', '/boards/import')).toHaveLength(2))
    expect(sent('POST', '/boards/import')[1].body).toEqual({ yaml_text: FILE, definitions: 'create' })
  })

  it('karten12 ac7: someone who is not an administrator is told an administrator can create them, and asks for none', async () => {
    as('user')
    stub(DEFINITIONS)
    show()
    await paste()
    const section = await screen.findByTestId('board-definitions')
    expect(within(section).queryByRole('checkbox')).toBeNull()
    expect(within(section).getByRole('note')).toHaveTextContent('An administrator can create the missing ones. Until then these cards show “definition missing”.')
    await userEvent.click(importButton())
    await waitFor(() => expect(sent('POST', '/boards/import')).toHaveLength(1))
    expect(sent('POST', '/boards/import')[0].body).toEqual({ yaml_text: FILE, definitions: 'skip' })
  })

  it('karten12 ac6: when nothing is missing there is no tick, and nothing is created', async () => {
    stub([{ type: 'card', id: 'speed', name: 'Speed', state: 'same' }])
    show()
    await paste()
    const section = await screen.findByTestId('board-definitions')
    expect(within(section).queryByRole('checkbox')).toBeNull()
    await userEvent.click(importButton())
    await waitFor(() => expect(sent('POST', '/boards/import')).toHaveLength(1))
    expect(sent('POST', '/boards/import')[0].body).toEqual({ yaml_text: FILE, definitions: 'skip' })
  })

  it('karten12 ec4: a board file without custom cards shows no section and is sent as it always was', async () => {
    stub([])
    show()
    await paste()
    await waitFor(() => expect(sent('POST', '/boards/import/check')).toHaveLength(1))
    expect(screen.queryByTestId('board-definitions')).toBeNull()
    await userEvent.click(importButton())
    await waitFor(() => expect(sent('POST', '/boards/import')).toHaveLength(1))
    expect(sent('POST', '/boards/import')[0].body).toEqual({ yaml_text: FILE })
  })

  it('karten12 ac6: a text the check does not understand shows no section; the import itself answers', async () => {
    stub(null)
    show()
    await paste()
    await waitFor(() => expect(sent('POST', '/boards/import/check')).toHaveLength(1))
    expect(screen.queryByTestId('board-definitions')).toBeNull()
    expect(importButton()).toBeEnabled()
  })

  it('karten12 ac6: a list belongs to the text it was asked for: once the text changes it is gone until asked again', async () => {
    stub(DEFINITIONS)
    show()
    await paste()
    await screen.findByTestId('board-definitions')
    await userEvent.type(screen.getByRole('textbox', { name: 'Import a board' }), ' ')
    expect(screen.queryByTestId('board-definitions')).toBeNull()
    expect(await screen.findByTestId('board-definitions')).toBeInTheDocument()
    expect(sent('POST', '/boards/import/check')).toHaveLength(2)
  })
})
