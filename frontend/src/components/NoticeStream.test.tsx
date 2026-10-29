/**
 * The bell counts on every page signed in, not only on a board (Abnahme 1).
 * Notices came only over a board's stream: on the settings, the chronicle or an
 * approval request the bell stood still until a reload. The browser's
 * EventSource is replaced by one the test can speak through.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useBoardStreams, useStream } from '../hooks/useStream'
import { useAuth } from '../stores/auth'
import { useNotices } from '../stores/notices'
import { serve, type Call } from '../test/mcpServer'
import { AppShell } from './AppShell'
import { NoticeStream } from './NoticeStream'

class FakeSource {
  static all: FakeSource[] = []
  url: string
  closed = false
  onerror: (() => void) | null = null
  private listeners: Record<string, ((event: MessageEvent) => void)[]> = {}
  constructor(url: string) {
    this.url = url
    FakeSource.all.push(this)
  }
  addEventListener(type: string, listener: (event: MessageEvent) => void) {
    ;(this.listeners[type] ??= []).push(listener)
  }
  emit(type: string, data: unknown = {}) {
    for (const listener of this.listeners[type] ?? []) listener(new MessageEvent(type, { data: JSON.stringify(data) }))
  }
  close() {
    this.closed = true
  }
}

const open = () => FakeSource.all.filter((source) => !source.closed)

function notice(id: number) {
  return { id, event: 'mcp_request', level: 'info', title: `Request ${id}`, body: '', link: `/mcp/requests/${id}`, created_at: '2026-10-28T18:00:00Z', read_at: null }
}

function Board() {
  useStream({ board: 'lab' })
  return null
}

/** A board that can be left, as a person goes from a board to the settings. */
function Leaving() {
  const [here, setHere] = useState(true)
  return (
    <>
      {here && <Board />}
      <button onClick={() => setHere(false)}>leave</button>
    </>
  )
}

let calls: Call[]

function start(children: React.ReactNode) {
  calls = serve({ 'GET /boards': () => [], 'GET /notices': () => [] })
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <NoticeStream />
        {children}
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  FakeSource.all = []
  vi.stubGlobal('EventSource', FakeSource)
  useAuth.setState({ user: { id: 1, username: 'sam', role: 'user' } as never })
  useNotices.setState({ notices: [], unread: 0, toast: null })
  useBoardStreams.setState({ open: 0 })
})
afterEach(() => {
  vi.unstubAllGlobals()
  useAuth.setState({ user: null })
})

describe('the bell outside a board', () => {
  it('counts a notice as it arrives, on a page that follows no board', async () => {
    start(
      <AppShell title="Settings">
        <p>settings</p>
      </AppShell>,
    )
    await waitFor(() => expect(open()).toHaveLength(1))
    expect(open()[0].url).toMatch(/\/stream$/)
    const bell = () => screen.getAllByRole('button', { name: 'Notices' })[0]
    act(() => open()[0].emit('hello'))
    // What came before the connection is read once from the list.
    await waitFor(() => expect(calls.some((call) => call.path.startsWith('/notices'))).toBe(true))
    expect(bell()).not.toHaveTextContent(/\d/)
    act(() => open()[0].emit('notice', notice(41)))
    expect(bell()).toHaveTextContent('1')
    act(() => open()[0].emit('notice', notice(42)))
    expect(bell()).toHaveTextContent('2')
  })

  it('opens no second stream while a board is open, and takes over when the board is left', async () => {
    start(<Leaving />)
    await waitFor(() => expect(open()).toHaveLength(1))
    expect(open()[0].url).toContain('board=lab')
    act(() => screen.getByRole('button', { name: 'leave' }).click())
    await waitFor(() => expect(open()).toHaveLength(1))
    expect(open()[0].url).toMatch(/\/stream$/)
  })

  it('opens nothing for nobody signed in', async () => {
    useAuth.setState({ user: null })
    start(<p>sign in</p>)
    await act(async () => undefined)
    expect(FakeSource.all).toHaveLength(0)
  })
})
