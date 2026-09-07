/**
 * Putting the boards in an order.
 *
 * ⚠️ The two arrow buttons are gone, replaced by a handle you drag. A handle
 * is the only thing a pointer can use, so if it were the only thing at all,
 * this list could be sorted with a mouse and by no other means: not by
 * keyboard, not by a switch, not by voice control that drives the keyboard.
 * The same handle therefore answers the arrow keys.
 *
 * The whole order goes back in one call. Two boards swapping places sent as
 * two writes can land either way round, and the loser of that race is a menu
 * in an order nobody asked for.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { BoardsSettings } from './BoardsSettings'
import { moved } from '../../lib/reorder'
import { useAuth } from '../../stores/auth'

const BOARDS = [
  { id: 1, slug: 'arr', name: 'ARR' },
  { id: 2, slug: 'network', name: 'Network' },
  { id: 3, slug: 'launcher', name: 'Launcher' },
].map((one) => ({
  ...one,
  owner_id: 1,
  owner_name: 'admin',
  permission: 'owner',
  in_menu: true,
  provisioned: false,
  widget_count: 4,
  pages: [{ id: one.id * 10, slug: 'overview', name: 'Overview', widget_count: 4 }],
}))

const calls = vi.hoisted(() => ({ put: [] as { path: string; body: unknown }[] }))
vi.mock('../../api/client', () => ({
  ApiError: class ApiError extends Error {},
  get: vi.fn(async () => BOARDS),
  post: vi.fn(async () => ({})),
  patch: vi.fn(async () => ({})),
  del: vi.fn(async () => ({})),
  put: vi.fn(async (path: string, body: unknown) => {
    calls.put.push({ path, body })
    return {}
  }),
}))

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <BoardsSettings />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('moved', () => {
  it('takes an entry out and puts it back in one step', () => {
    expect(moved(['a', 'b', 'c'], 0, 2)).toEqual(['b', 'c', 'a'])
    expect(moved(['a', 'b', 'c'], 2, 0)).toEqual(['c', 'a', 'b'])
  })

  it('leaves the list alone when there is nowhere to go', () => {
    // ⚠️ Each of these is a way the three obvious lines go wrong: an index off
    // the end drops the entry, and a move onto its own place rewrites the list
    // for nothing, which here would mean a needless write to the server.
    expect(moved(['a', 'b'], 1, 1)).toEqual(['a', 'b'])
    expect(moved(['a', 'b'], 0, 5)).toEqual(['a', 'b'])
    expect(moved(['a', 'b'], -1, 0)).toEqual(['a', 'b'])
  })

  it('does not touch the list it was given', () => {
    const before = ['a', 'b', 'c']
    moved(before, 0, 2)
    expect(before).toEqual(['a', 'b', 'c'])
  })
})

describe('the board list', () => {
  beforeEach(() => {
    calls.put.length = 0
    useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin' } as never })
  })

  it('offers one handle per board and no arrow buttons', async () => {
    show()
    await screen.findByText('ARR')
    const handles = screen.getAllByRole('button', { name: /Drag to move/ })
    expect(handles).toHaveLength(3)
    expect(screen.queryByRole('button', { name: /Move .* up|Move .* down/ })).toBeNull()
  })

  it('moves a board with the arrow keys and sends the whole order', async () => {
    show()
    await screen.findByText('ARR')
    const handle = screen.getByRole('button', { name: 'Drag to move ARR' })
    handle.focus()
    await userEvent.keyboard('{ArrowDown}')

    await waitFor(() => expect(calls.put).toHaveLength(1))
    expect(calls.put[0].path).toBe('/boards/order')
    expect(calls.put[0].body).toEqual({ slugs: ['network', 'arr', 'launcher'] })
  })

  it('moves it back up again', async () => {
    // ⚠️ Both directions, not one. A mutation probe walked straight through
    // the up branch while every test was green, because every test pressed
    // down.
    show()
    await screen.findByText('Launcher')
    const handle = screen.getByRole('button', { name: 'Drag to move Launcher' })
    handle.focus()
    await userEvent.keyboard('{ArrowUp}')

    await waitFor(() => expect(calls.put).toHaveLength(1))
    expect(calls.put[0].body).toEqual({ slugs: ['arr', 'launcher', 'network'] })
  })

  it('writes nothing when the board is already at the top', async () => {
    show()
    await screen.findByText('ARR')
    const handle = screen.getByRole('button', { name: 'Drag to move ARR' })
    handle.focus()
    await userEvent.keyboard('{ArrowUp}')
    expect(calls.put).toHaveLength(0)
  })

  it('writes nothing when the board is already at the end', async () => {
    show()
    await screen.findByText('Launcher')
    const handle = screen.getByRole('button', { name: 'Drag to move Launcher' })
    handle.focus()
    await userEvent.keyboard('{ArrowDown}')
    expect(calls.put).toHaveLength(0)
  })

  it('leaves a modified arrow to the browser', async () => {
    show()
    await screen.findByText('ARR')
    const handle = screen.getByRole('button', { name: 'Drag to move ARR' })
    handle.focus()
    await userEvent.keyboard('{Control>}{ArrowDown}{/Control}')
    expect(calls.put).toHaveLength(0)
  })
})
