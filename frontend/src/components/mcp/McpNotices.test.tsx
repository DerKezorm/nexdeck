/**
 * Notices about MCP in the language on screen (Abnahme 2 to 4).
 *
 * The server writes them in English for its channels: "Laptop asks to press
 * Stop (sonarr) on Running containers" stood in a German bell, and the result
 * of a press named the action id ("restart on Containers") without the row or
 * the program. The bell words them from the fields the server sends along;
 * the request page names the row its button sits on.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import i18next from 'i18next'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Notice } from '../../api/types'
import { setLanguage } from '../../i18n'
import { noticeWords, type McpNoticeFacts } from '../../lib/mcp'
import { McpRequestPage } from '../../pages/McpRequestPage'
import { useNotices } from '../../stores/notices'
import { request, serve } from '../../test/mcpServer'
import { NoticeList, NoticeToast } from '../NoticeDrawer'

const asked: McpNoticeFacts = { kind: 'mcp_request', program: 'Claude Code', label: 'Stop', row: 'sonarr', card: 'Running containers', board: 'Homelab' }
const pressed: McpNoticeFacts = { kind: 'mcp_press', program: 'Claude Code', label: 'Restart', row: 'radarr', card: 'Running containers', approved_by: '' }

function notice(extra: Partial<Notice> = {}): Notice {
  return {
    id: 31,
    event: 'mcp_request',
    level: 'warn',
    title: 'Claude Code asks to press Stop (sonarr) on Running containers',
    body: 'Board Homelab. Allow or decline in nexdeck.',
    link: '/mcp/requests/7',
    created_at: '2026-10-28T10:00:00Z',
    read_at: null,
    ...extra,
  }
}

function result(extra: Partial<McpNoticeFacts> = {}): Notice {
  return notice({ id: 32, event: 'action_done', level: 'info', title: 'Restart (radarr) on Running containers, by Claude Code (MCP)', body: 'Demo mode: restart would have run now.', link: '', facts: { ...pressed, ...extra } })
}

function wrap(children: React.ReactNode, path = '/') {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>{children}</MemoryRouter>
    </QueryClientProvider>,
  )
}

const words = (key: string, options?: Record<string, unknown>) => i18next.t(key, options)

afterEach(async () => {
  vi.unstubAllGlobals()
  useNotices.setState({ notices: [], unread: 0, toast: null })
  await setLanguage('en')
})

describe('the words of a notice about MCP', () => {
  it('names the program, the button with its row, and the card', () => {
    expect(noticeWords(words, asked)).toEqual({ title: 'Claude Code asks to press Stop (sonarr) on Running containers', body: 'Board Homelab.' })
    expect(noticeWords(words, { ...asked, row: '' }).title).toBe('Claude Code asks to press Stop on Running containers')
  })

  it('says of a press the button, not its action id, the row, the card and the program, and who allowed it', () => {
    expect(noticeWords(words, pressed)).toEqual({ title: 'Restart (radarr) on Running containers, by Claude Code (MCP)' })
    expect(noticeWords(words, { ...pressed, approved_by: 'Sam' }).title).toBe('Restart (radarr) on Running containers, by Claude Code (MCP), approved by Sam')
    expect(noticeWords(words, { ...pressed, failed: true }).title).toBe('Restart (radarr) on Running containers failed, by Claude Code (MCP)')
    expect(noticeWords(words, { ...pressed, failed: true, approved_by: 'Sam' }).title).toBe('Restart (radarr) on Running containers failed, by Claude Code (MCP), approved by Sam')
  })
})

describe('in a German bell', () => {
  it('says the request in German from the fields it came with', async () => {
    await setLanguage('de')
    serve({ 'GET /mcp/requests/7': () => request({ label: 'Stop', danger: true }) })
    wrap(<NoticeList notices={[notice({ facts: { ...asked } })]} />)
    expect(await screen.findByText('Claude Code möchte Stoppen (sonarr) auf Running containers drücken')).toBeInTheDocument()
    expect(screen.getByText('Board Homelab.')).toBeInTheDocument()
    expect(screen.queryByText(/asks to press/)).toBeNull()
  })

  it('words a request from before the fields were sent from the request itself', async () => {
    await setLanguage('de')
    serve({ 'GET /mcp/requests/7': () => request({ key_name: 'Claude Code', label: 'Stop', row: 'sonarr', card: 'Running containers', board: 'Homelab' }) })
    wrap(<NoticeList notices={[notice()]} />)
    expect(await screen.findByText('Claude Code möchte Stoppen (sonarr) auf Running containers drücken')).toBeInTheDocument()
  })

  it('says the result of a press in German and keeps the answer of the service', async () => {
    await setLanguage('de')
    serve({})
    wrap(<NoticeList notices={[result(), { ...result({ approved_by: 'admin' }), id: 33 }]} />)
    expect(await screen.findByText('Neustarten (radarr) auf Running containers, durch Claude Code (MCP)')).toBeInTheDocument()
    expect(screen.getByText('Neustarten (radarr) auf Running containers, durch Claude Code (MCP), erlaubt von admin')).toBeInTheDocument()
    expect(screen.getAllByText('Demo mode: restart would have run now.')).toHaveLength(2)
  })

  it('leaves every other notice as the server wrote it', async () => {
    await setLanguage('de')
    const calls = serve({})
    wrap(<NoticeList notices={[notice({ event: 'down', title: 'Plex is down', body: 'No answer', link: '/b/lab' })]} />)
    expect(screen.getByText('Plex is down')).toBeInTheDocument()
    await new Promise((settle) => setTimeout(settle, 20))
    expect(calls).toHaveLength(0)
  })

  it('says it in the toast as well', async () => {
    await setLanguage('de')
    serve({})
    useNotices.setState({ toast: result() })
    wrap(<NoticeToast />)
    expect(await screen.findByText('Neustarten (radarr) auf Running containers, durch Claude Code (MCP)')).toBeInTheDocument()
  })
})

describe('the request page', () => {
  it('names the row the button sits on, and says whose Docker words the impact quotes', async () => {
    serve({ 'GET /mcp/requests/7': () => request({ row: 'sonarr', impact: [{ fact: 'up', text: 'Up 3 days' }] }), 'GET /boards': () => [] })
    wrap(
      <Routes>
        <Route path="/mcp/requests/:id" element={<McpRequestPage />} />
      </Routes>,
      '/mcp/requests/7',
    )
    const box = await screen.findByTestId('mcp-request')
    await waitFor(() => expect(box).toHaveTextContent('Rowsonarr'))
    expect(screen.getByTestId('mcp-impact')).toHaveTextContent('sonarr: Up 3 days')
    expect(screen.getByTestId('mcp-impact')).not.toHaveTextContent('Docker')
  })

  it('shows no row for a button of the card itself', async () => {
    serve({ 'GET /mcp/requests/7': () => request({ row: '', impact: [{ fact: 'up', text: 'Up 3 days' }] }), 'GET /boards': () => [] })
    wrap(
      <Routes>
        <Route path="/mcp/requests/:id" element={<McpRequestPage />} />
      </Routes>,
      '/mcp/requests/7',
    )
    const box = await screen.findByTestId('mcp-request')
    expect(box).not.toHaveTextContent('Row')
    expect(screen.getByTestId('mcp-impact')).toHaveTextContent('Docker: Up 3 days')
  })
})
