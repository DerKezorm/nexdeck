/**
 * The two field types that answer out of nexdeck itself rather than out of a
 * service: a board, and a colour.
 *
 * ⚠️ The board picker exists because the field type that asks a service needs
 * a connection to ask, and a card that belongs to no service has none. The
 * button card is exactly that card.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { FieldInput } from './FieldInput'
import type { FieldSpec } from '../api/types'

const calls = vi.hoisted(() => ({
  boards: [
    { id: 1, slug: 'home', name: 'Home', pages: [{ id: 1, slug: 'overview', name: 'Overview' }, { id: 2, slug: 'media', name: 'Media' }] },
    { id: 2, slug: 'network', name: 'Network', pages: [{ id: 3, slug: 'overview', name: 'Overview' }] },
  ] as unknown[],
}))

vi.mock('../api/client', () => ({
  get: vi.fn(async (path: string) => {
    if (path === '/boards') return calls.boards
    throw new Error(`unexpected request ${path}`)
  }),
}))

function spec(over: Partial<FieldSpec>): FieldSpec {
  return {
    name: 'board', label: 'Which board', type: 'board', required: false, secret: false,
    default: null, help: '', placeholder: '', options: [], ...over,
  } as FieldSpec
}

function show(one: FieldSpec, value: unknown, onChange: (value: unknown) => void) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <FieldInput spec={one} value={value} onChange={onChange} />
    </QueryClientProvider>,
  )
}

describe('the board picker', () => {
  beforeEach(() => {
    calls.boards = [
      { id: 1, slug: 'home', name: 'Home', pages: [{ id: 1, slug: 'overview', name: 'Overview' }, { id: 2, slug: 'media', name: 'Media' }] },
      { id: 2, slug: 'network', name: 'Network', pages: [{ id: 3, slug: 'overview', name: 'Overview' }] },
    ]
  })

  it('offers every board, and the pages of the ones that have more than one', async () => {
    // ⚠️ A board with a single page is that page. Offering both would be two
    // entries that do exactly the same thing, one line apart.
    show(spec({}), '', () => undefined)
    const picker = await screen.findByRole('combobox')
    await waitFor(() => expect(picker.querySelectorAll('option').length).toBeGreaterThan(1))
    const offered = [...picker.querySelectorAll('option')].map((one) => one.getAttribute('value'))
    expect(offered).toEqual(['', 'home', 'home/overview', 'home/media', 'network'])
  })

  it('hands back what an address is made of', async () => {
    const picked: unknown[] = []
    show(spec({}), '', (value) => picked.push(value))
    const picker = await screen.findByRole('combobox')
    await waitFor(() => expect(picker.querySelectorAll('option').length).toBeGreaterThan(1))
    await userEvent.selectOptions(picker, 'home/media')
    expect(picked).toEqual(['home/media'])
  })

  it('says so when there is no board to pick', async () => {
    calls.boards = []
    show(spec({}), '', () => undefined)
    expect(await screen.findByText('There are no boards yet.')).toBeInTheDocument()
  })
})

describe('the colour field', () => {
  it('starts on none, and can be cleared again', async () => {
    const picked: unknown[] = []
    show(spec({ name: 'colour', label: 'Colour', type: 'colour' }), '', (value) => picked.push(value))
    // ⚠️ "None" needs its own control: a colour input cannot be empty, it
    // shows black, and picking black to mean "leave it alone" is not
    // something anybody guesses.
    expect(screen.getByText('Board colour')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Clear' })).toBeDisabled()
  })

  it('offers to clear once a colour is set', async () => {
    const picked: unknown[] = []
    show(spec({ name: 'colour', label: 'Colour', type: 'colour' }), '#ff8800', (value) => picked.push(value))
    expect(screen.getByText('#ff8800')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Clear' }))
    expect(picked).toEqual([''])
  })
})
