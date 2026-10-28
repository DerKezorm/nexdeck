/**
 * Approval requests: Allow and Decline right in the bell, and the page a
 * request opens on (`/mcp/requests/<id>`). The server is replaced by a table
 * of answers.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Notice } from '../../api/types'
import { McpRequestPage } from '../../pages/McpRequestPage'
import { useNotices } from '../../stores/notices'
import { refusal, request, serve, type Call } from '../../test/mcpServer'
import { NoticeList } from '../NoticeDrawer'
import type { McpRequest } from '../../lib/mcp'

let current: McpRequest
let calls: Call[]
let onApprove: () => Response | unknown

function notice(extra: Partial<Notice> = {}): Notice {
  return { id: 31, event: 'mcp_request', level: 'warn', title: 'Laptop asks to press Restart', body: 'Containers on Lab', link: '/mcp/requests/7', created_at: '2026-10-28T10:00:00Z', read_at: null, ...extra }
}

function start() {
  calls = serve({
    'GET /mcp/requests/7': () => current,
    'POST /mcp/requests/7/approve': () => onApprove(),
    'POST /mcp/requests/7/decline': () => {
      current = { ...current, status: 'declined' }
      return { status: 'declined', result: null }
    },
    'POST /notices/read': () => ({}),
    'GET /boards': () => [],
  })
}

const client = () => new QueryClient({ defaultOptions: { queries: { retry: false } } })

function bell(notices: Notice[]) {
  useNotices.setState({ notices, unread: notices.filter((n) => !n.read_at).length })
  return render(
    <QueryClientProvider client={client()}>
      <MemoryRouter>
        <NoticeList notices={notices} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function page(path = '/mcp/requests/7') {
  return render(
    <QueryClientProvider client={client()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/mcp/requests/:id" element={<McpRequestPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  current = request()
  onApprove = () => {
    current = { ...current, status: 'approved', result: { message: 'Restarted plex' } }
    return { status: 'approved', result: current.result }
  }
})
afterEach(() => vi.unstubAllGlobals())

describe('an approval request in the bell', () => {
  it('shows Allow and Decline under a request that is waiting', async () => {
    start()
    bell([notice()])
    const box = await screen.findByTestId('mcp-notice-7')
    expect(within(box).getByRole('button', { name: 'Allow' })).toBeEnabled()
    expect(within(box).getByRole('button', { name: 'Decline' })).toBeEnabled()
  })

  it('does not ask the server about any other notice', async () => {
    start()
    // Even with a link of that shape: the event decides, not the address.
    bell([notice({ id: 32, event: 'card_down', title: 'Plex is down' })])
    await screen.findByText('Plex is down')
    expect(calls).toEqual([])
    expect(screen.queryByRole('button', { name: 'Allow' })).toBeNull()
  })

  it('allows exactly that request, and marks its notice as read so the bell stops counting it', async () => {
    start()
    const user = userEvent.setup()
    bell([notice()])
    await user.click(await screen.findByRole('button', { name: 'Allow' }))
    await waitFor(() => expect(calls.some((call) => call.path === '/mcp/requests/7/approve' && call.method === 'POST')).toBe(true))
    await waitFor(() => expect(calls.find((call) => call.path === '/notices/read')?.body).toEqual({ ids: [31] }))
    expect(useNotices.getState().unread).toBe(0)
    // Answered: the buttons are gone and the state stands there.
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Allow' })).toBeNull())
    expect(screen.getByTestId('mcp-state')).toHaveTextContent('Allowed')
  })

  it('declines without running anything', async () => {
    start()
    const user = userEvent.setup()
    bell([notice()])
    await user.click(await screen.findByRole('button', { name: 'Decline' }))
    await waitFor(() => expect(calls.some((call) => call.path === '/mcp/requests/7/decline')).toBe(true))
    expect(calls.some((call) => call.path.endsWith('/approve'))).toBe(false)
    await waitFor(() => expect(screen.getByTestId('mcp-state')).toHaveTextContent('Declined'))
  })

  it.each([
    ['approved', 'Allowed'],
    ['declined', 'Declined'],
    ['expired', 'Ran out'],
    ['failed', 'Allowed, but it did not work'],
  ])('shows a request that is %s without buttons', async (status, words) => {
    current = request({ status })
    start()
    bell([notice()])
    expect(await screen.findByTestId('mcp-state')).toHaveTextContent(words)
    expect(screen.queryByRole('button', { name: 'Allow' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Decline' })).toBeNull()
  })

  it('treats a waiting request whose ten minutes are over as run out', async () => {
    current = request({ expires_at: new Date(Date.now() - 1000).toISOString() })
    start()
    bell([notice()])
    expect(await screen.findByTestId('mcp-state')).toHaveTextContent('Ran out')
    expect(screen.queryByRole('button', { name: 'Allow' })).toBeNull()
  })

  it('marks a dangerous button', async () => {
    current = request({ danger: true })
    start()
    bell([notice()])
    expect(await screen.findByTestId('mcp-danger')).toHaveTextContent('Dangerous button')
  })

  it('offers only Review and Decline for a dangerous button, so one click in the bell cannot allow it', async () => {
    current = request({ danger: true })
    start()
    const user = userEvent.setup()
    bell([notice()])
    const box = await screen.findByTestId('mcp-notice-7')
    expect(within(box).queryByRole('button', { name: 'Allow' })).toBeNull()
    expect(within(box).getByRole('link', { name: 'Review' })).toHaveAttribute('href', '/mcp/requests/7')
    await user.click(within(box).getByRole('button', { name: 'Decline' }))
    await waitFor(() => expect(calls.some((call) => call.path === '/mcp/requests/7/decline')).toBe(true))
    expect(calls.some((call) => call.path.endsWith('/approve'))).toBe(false)
  })

  it('keeps Allow for a harmless button in the bell, with no Review', async () => {
    start()
    bell([notice()])
    const box = await screen.findByTestId('mcp-notice-7')
    expect(within(box).getByRole('button', { name: 'Allow' })).toBeEnabled()
    expect(within(box).queryByRole('link', { name: 'Review' })).toBeNull()
  })

  it('says so when the server found it answered meanwhile, and shows the state it has now', async () => {
    onApprove = () => {
      current = { ...current, status: 'declined' }
      return refusal(409, 'request_closed', 'closed')
    }
    start()
    const user = userEvent.setup()
    bell([notice()])
    await user.click(await screen.findByRole('button', { name: 'Allow' }))
    await waitFor(() => expect(screen.getByTestId('mcp-state')).toHaveTextContent('Declined'))
  })
})

describe('the page of one request', () => {
  it('shows who asks, the card, the button, the parameters, what it would hit and until when', async () => {
    start()
    page()
    const box = await screen.findByTestId('mcp-request')
    expect(box).toHaveTextContent('Laptop asks to press a button')
    for (const word of ['Containers', 'Lab', 'Restart', 'press_button']) expect(box).toHaveTextContent(word)
    expect(screen.getByTestId('mcp-params')).toHaveTextContent('id: plex')
    expect(screen.getByTestId('mcp-impact')).toHaveTextContent('Living room, Tablet')
    expect(screen.getByRole('button', { name: 'Allow' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Decline' })).toBeEnabled()
    expect(screen.queryByTestId('mcp-danger')).toBeNull()
  })

  it('marks a dangerous button on the page too', async () => {
    current = request({ danger: true })
    start()
    page()
    expect(await screen.findByTestId('mcp-danger')).toBeInTheDocument()
  })

  it('asks a second time before it allows a dangerous button, and only the second yes runs it', async () => {
    current = request({ danger: true })
    start()
    const user = userEvent.setup()
    page()
    await user.click(await screen.findByRole('button', { name: 'Allow' }))
    const question = await screen.findByRole('dialog')
    expect(question).toHaveTextContent('Allow a dangerous button?')
    expect(question).toHaveTextContent('Restart on Containers')
    expect(calls.some((call) => call.path.endsWith('/approve'))).toBe(false)
    // Backing out runs nothing.
    await user.click(within(question).getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(calls.some((call) => call.path.endsWith('/approve'))).toBe(false)
    await user.click(screen.getByRole('button', { name: 'Allow' }))
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Yes, press it' }))
    await waitFor(() => expect(calls.filter((call) => call.path === '/mcp/requests/7/approve')).toHaveLength(1))
  })

  it('allows a harmless button on the page at once, without a second question', async () => {
    start()
    const user = userEvent.setup()
    page()
    await user.click(await screen.findByRole('button', { name: 'Allow' }))
    await waitFor(() => expect(calls.some((call) => call.path === '/mcp/requests/7/approve')).toBe(true))
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('shows the result after the request was allowed, and no buttons', async () => {
    current = request({ status: 'approved', result: { message: 'Restarted plex' } })
    start()
    page()
    expect(await screen.findByTestId('mcp-result')).toHaveTextContent('Restarted plex')
    expect(screen.getByTestId('mcp-status')).toHaveTextContent('Allowed')
    expect(screen.queryByRole('button', { name: 'Allow' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Decline' })).toBeNull()
  })

  it('shows a request that ran out with its state and no buttons', async () => {
    current = request({ status: 'expired' })
    start()
    page()
    expect(await screen.findByTestId('mcp-status')).toHaveTextContent('Ran out')
    expect(screen.queryByRole('button', { name: 'Allow' })).toBeNull()
  })

  it('answers the same for a request that is not there, whoever it belongs to', async () => {
    serve({ 'GET /mcp/requests/99': () => refusal(404, 'not_found', 'Not found') })
    page('/mcp/requests/99')
    expect(await screen.findByTestId('mcp-request-gone')).toHaveTextContent('This request does not exist.')
  })

  it('allows from the page and then shows the result', async () => {
    start()
    const user = userEvent.setup()
    page()
    await user.click(await screen.findByRole('button', { name: 'Allow' }))
    expect(await screen.findByTestId('mcp-result')).toHaveTextContent('Restarted plex')
    expect(screen.queryByRole('button', { name: 'Allow' })).toBeNull()
  })
})
