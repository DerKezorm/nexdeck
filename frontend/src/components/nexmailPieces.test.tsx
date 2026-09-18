/**
 * The three pieces the nexmail cards added to shared components: several
 * choices from the service at once, a total above a list, and a row that
 * wants attention without being a fault. Plus the library asking a
 * connection before it adds a card that could only show its hint.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { FieldSpec } from '../api/types'
import type { WidgetData, WidgetView } from '../lib/types'
import { DEMO_VIEWS } from '../demo/board'
import { FieldInput } from './FieldInput'
import { renderWidget } from './renderers'
import { WidgetLibrary } from './WidgetLibrary'

const COUNTS_ONLY = 'This key may only read counts.'

const api = vi.hoisted(() => ({
  posted: [] as string[],
  reason: '',
}))

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  mediaUrl: (id: number, path: string) => `/media/${id}/${path}`,
  fileUrl: (id: number, path: string) => `/file/${id}/${path}`,
  get: vi.fn(async (path: string) => {
    if (path === '/integrations/5/choices/mailboxes') {
      return [{ value: 'mb-home', label: 'Home' }, { value: 'mb-work', label: 'Work' }, { value: 'mb-club', label: 'Club' }]
    }
    if (path === '/adapters') {
      return [{
        kind: 'nexmail', label: 'nexmail', category: 'other', description: '', icon: 'nexmail', beta: true, docs_url: '',
        needs_integration: true, bars_widgets: true, fields: [],
        widgets: [{ kind: 'nexmail.latest', label: 'Latest mail', description: 'Sender and subject', renderer: 'list',
          default_size: [3, 3], min_size: [2, 2], options: [], refresh_seconds: 60, metrics: [], client_only: false }],
      }]
    }
    if (path === '/integrations') return [{ id: 3, kind: 'nexmail', name: 'nexmail' }]
    if (path === '/integrations/3/barred/latest') return { reason: api.reason }
    throw new Error(`unexpected request ${path}`)
  }),
  post: vi.fn(async (path: string) => {
    api.posted.push(path)
    return { widget: { id: 99 } }
  }),
}))

function mailboxes(value: unknown, onChange: (value: unknown) => void) {
  const spec = {
    name: 'mailboxes', label: 'Mailboxes', type: 'choices', required: false, secret: false,
    default: [], help: '', placeholder: '', options: [],
  } as unknown as FieldSpec
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <FieldInput spec={spec} value={value} onChange={onChange} integrationId={5} />
    </QueryClientProvider>,
  )
}

describe('several choices from the service', () => {
  it('starts with every mailbox on, and the first click leaves one out', async () => {
    const changes: unknown[] = []
    mailboxes([], (value) => changes.push(value))
    const home = await screen.findByRole('button', { name: 'Home' })
    for (const name of ['Home', 'Work', 'Club']) {
      expect(screen.getByRole('button', { name })).toHaveAttribute('aria-pressed', 'true')
    }
    await userEvent.click(home)
    expect(changes).toEqual([['mb-work', 'mb-club']])
  })

  it('stores everything ticked as nothing, so a new mailbox turns up by itself', async () => {
    const changes: unknown[] = []
    mailboxes(['mb-home', 'mb-work'], (value) => changes.push(value))
    const club = await screen.findByRole('button', { name: 'Club' })
    expect(club).toHaveAttribute('aria-pressed', 'false')
    await userEvent.click(club)
    expect(changes).toEqual([[]])
  })

  it('does not let the last mailbox go', async () => {
    const changes: unknown[] = []
    mailboxes(['mb-work'], (value) => changes.push(value))
    await userEvent.click(await screen.findByRole('button', { name: 'Work' }))
    expect(changes).toEqual([])
  })
})

describe('a list with a total on top', () => {
  const view = { ...DEMO_VIEWS[0], id: 11, renderer: 'list' } as WidgetView
  const rows = [{ title: 'Home', value: 4 }, { title: 'Work', value: 11 }]

  it('draws the total above the rows when the card asks for it', () => {
    const data = { status: 'ok', primary: { label: 'Unread', value: 15 }, items: rows, meta: { headline: true } } as unknown as WidgetData
    render(<>{renderWidget({ widget: view, data, canAct: false })}</>)
    expect(screen.getByTestId('list-headline')).toHaveTextContent('15')
  })

  it('leaves every other list as it was', () => {
    // ⚠️ Lists that carry a primary for their chart or gauge view must not
    // grow a number on top of their rows.
    const data = { status: 'ok', primary: { label: 'Unread', value: 15 }, items: rows } as unknown as WidgetData
    render(<>{renderWidget({ widget: view, data, canAct: false })}</>)
    expect(screen.queryByTestId('list-headline')).toBeNull()
  })

  it('makes a row that wants attention bold, with a dot in the accent colour', () => {
    const data = { status: 'ok', items: [{ title: 'Build server', emphasis: true }, { title: 'Library' }] } as unknown as WidgetData
    const { container } = render(<>{renderWidget({ widget: view, data, canAct: false })}</>)
    expect(screen.getByText('Build server')).toHaveClass('font-semibold')
    expect(screen.getByText('Library')).not.toHaveClass('font-semibold')
    expect([...container.querySelectorAll('.dot')].map((dot) => dot.getAttribute('data-status'))).toEqual(['accent', 'unknown'])
  })
})

describe('the library asks before it adds a card a connection bars', () => {
  beforeEach(() => {
    api.posted = []
  })

  function library() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <WidgetLibrary open onClose={() => undefined} pageId={1} onCreated={() => undefined} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
  }

  it('says why and adds nothing', async () => {
    api.reason = COUNTS_ONLY
    library()
    await screen.findByText('Latest mail', { exact: false })
    await waitFor(() => expect(screen.getByRole('button', { name: /Latest mail/ })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: /Latest mail/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent(COUNTS_ONLY)
    expect(api.posted).toEqual([])
  })

  it('adds the card when the connection has nothing against it', async () => {
    api.reason = ''
    library()
    await screen.findByText('Latest mail', { exact: false })
    await userEvent.click(screen.getByRole('button', { name: /Latest mail/ }))
    await waitFor(() => expect(api.posted).toEqual(['/pages/1/widgets']))
  })
})
