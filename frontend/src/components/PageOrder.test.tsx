/**
 * Putting the pages of a board in an order (issue #50), by the same handle as
 * the list of boards: dragged, or moved with the arrow keys, and the whole
 * order sent back in one call.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { BoardWithLive } from '../api/types'
import { BoardSettingsSheet } from './BoardSettingsSheet'

const calls = vi.hoisted(() => ({ put: [] as { path: string; body: unknown }[], hold: false }))
vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  get: vi.fn(async () => []),
  post: vi.fn(async () => ({})),
  patch: vi.fn(async () => ({})),
  del: vi.fn(async () => ({})),
  upload: vi.fn(async () => ({})),
  put: vi.fn((path: string, body: unknown) => {
    calls.put.push({ path, body })
    // Held: the server is still being told, and the list shows what was dropped.
    return calls.hold ? new Promise(() => undefined) : Promise.resolve({})
  }),
}))

const page = (id: number, name: string) => ({ id, name, slug: name.toLowerCase(), widgets: [], layouts: {}, position: id })
const BOARD = { id: 1, slug: 'home', name: 'Home', settings: {}, background: null, pages: [page(1, 'Overview'), page(2, 'Media'), page(3, 'Network')] } as unknown as BoardWithLive

async function pagesTab(onChanged = vi.fn()) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <BoardSettingsSheet open board={BOARD} boards={[]} canEdit onClose={vi.fn()} onChanged={onChanged} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  await userEvent.click(screen.getByRole('button', { name: 'Pages' }))
  return onChanged
}

beforeEach(() => {
  calls.put = []
  calls.hold = false
})

describe('the order of the pages', () => {
  it('has a handle for every page', async () => {
    await pagesTab()
    expect(screen.getAllByRole('button', { name: /Drag to move/ })).toHaveLength(3)
  })

  it('moves a page down with the arrow keys and sends the whole order', async () => {
    const onChanged = await pagesTab()
    screen.getByRole('button', { name: 'Drag to move Overview' }).focus()
    await userEvent.keyboard('{ArrowDown}')
    await waitFor(() => expect(calls.put).toHaveLength(1))
    expect(calls.put[0]).toEqual({ path: '/boards/home/pages/order', body: { ids: [2, 1, 3] } })
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
  })

  it('shows the new order at once, while the server is still being told', async () => {
    calls.hold = true
    await pagesTab()
    screen.getByRole('button', { name: 'Drag to move Overview' }).focus()
    await userEvent.keyboard('{ArrowDown}')
    await waitFor(() => expect(calls.put).toHaveLength(1))
    const names = screen.getAllByRole('button', { name: /Drag to move/ }).map((handle) => handle.getAttribute('aria-label'))
    expect(names).toEqual(['Drag to move Media', 'Drag to move Overview', 'Drag to move Network'])
  })

  it('moves a page up as well', async () => {
    await pagesTab()
    screen.getByRole('button', { name: 'Drag to move Network' }).focus()
    await userEvent.keyboard('{ArrowUp}')
    await waitFor(() => expect(calls.put).toHaveLength(1))
    expect(calls.put[0].body).toEqual({ ids: [1, 3, 2] })
  })
})
