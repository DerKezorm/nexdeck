/**
 * Why is this broken (roadmap M6): the page as agreed on 25.10.2026, and the
 * "Why?" that leads to it from a card, a row and a line. The server is
 * replaced; nothing is asked of a service.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AttentionCard } from '../components/AttentionCard'
import { ChronicleRow } from '../components/ChronicleLines'
import { WidgetCard } from '../components/WidgetCard'
import { useAssistant } from '../lib/assistant'
import { diagnosisPath, lengthOf, subjectOf, type Diagnosis } from '../lib/diagnosis'
import type { WidgetView } from '../lib/types'
import { useAuth } from '../stores/auth'
import { DiagnosisPage } from './DiagnosisPage'

const sent: { method: string; path: string; body?: unknown }[] = []
const NOW = 1_792_900_000

function page(extra: Partial<Diagnosis> = {}): Diagnosis {
  return {
    subject: { ref: 'integration:3', kind: 'integration', service: 'plex', name: 'Plex', detail: '10.0.0.65:32400', icon: 'plex', demo: false },
    state: 'now', level: 'bad', since: NOW - 20 * 60, until: null, reason: 'Connection refused',
    window: { from: NOW - 140 * 60, to: NOW },
    cause: { ref: 'integration:2', name: 'docker-live', down: true },
    lines: [
      { id: 1, when: NOW - 95 * 60, kind: 'version', level: 'info', name: 'docker-live', before: '27.1', after: '27.2', detail: '', board: '', whose: 'integration:2', via: 'docker-live' },
      { id: 2, when: NOW - 19 * 60, kind: 'outage', level: 'bad', name: 'Plex', before: '', after: '', detail: 'Connection refused', board: 'Lab', whose: 'self', via: '' },
    ],
    above: [
      { ref: 'integration:2', kind: 'integration', name: 'docker-live', down: true, detail: 'docker' },
      { ref: 'container:2:plex', kind: 'container', name: 'plex', down: true, detail: 'docker-live · plexinc/pms-docker' },
    ],
    below: [{ ref: 'integration:7', kind: 'integration', name: 'Tautulli', down: false, detail: 'tautulli' }],
    cards: [{ id: 4, title: 'Now playing', kind: 'plex.nowplaying', status: 'bad', reason: 'Connection refused', board: 'Lab', target: { board: 'lab', page: 'main', widget: 4 } }],
    checks: [{ id: 1, card: 'Now playing', kind: 'http', target: 'http://10.0.0.65:32400', enabled: true, ok: false, error: 'Connection refused', latency_ms: null, down_since: NOW - 20 * 60, checked: NOW }],
    log: { available: true, container: 'plex', engine: 'docker-live', ref: 'container:2:plex' },
    buttons: [{ widget_id: 5, card: 'Containers', item: 'plex', id: 'restart', label: 'Restart', icon: 'rotate-cw', params: { id: 'c1' }, confirm: true, danger: false }],
    runbook: { text: '1. Check **docker-live** first\n2. Then restart', link: 'https://notes.example.com/plex', updated: NOW - 3600, by: 'admin' },
    ...extra,
  }
}

let served: Diagnosis = page()

vi.mock('../api/client', async (original) => ({
  ...(await original<typeof import('../api/client')>()),
  get: vi.fn(async (path: string) => {
    sent.push({ method: 'GET', path })
    if (path === '/assistant') return { ready: true, provider: 'anthropic', model: 'x', leaves_the_house: true, keep_days: 30 }
    if (path.startsWith('/diagnosis?')) return served
    return []
  }),
  post: vi.fn(async (path: string, body?: unknown) => {
    sent.push({ method: 'POST', path, body })
    if (path === '/diagnosis/log') return { container: 'plex', engine: 'docker-live', lines: ['started', 'ERROR Database is locked', 'token=***'], read: NOW }
    if (path.endsWith('/impact')) return { impact: [{ fact: 'streams', count: 2, names: ['Living room', 'Tablet'] }] }
    if (path.startsWith('/widgets/')) return { message: 'Restarted.' }
    return {}
  }),
  put: vi.fn(async (path: string, body?: unknown) => {
    sent.push({ method: 'PUT', path, body })
    const { text, link } = body as { text: string; link: string }
    return { text, link, updated: NOW, by: 'admin' }
  }),
}))

function open(address = diagnosisPath('integration:3')) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[address]}>
        <Routes>
          <Route path="/diagnosis" element={<DiagnosisPage />} />
          <Route path="/b/:board/:page" element={<p>board</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  sent.length = 0
  served = page()
  useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin' } as never })
  useAssistant.setState({ state: { ready: true, provider: 'anthropic', model: 'x', leaves_the_house: true, keep_days: 30 }, open: false, asking: '', about: '' })
})

describe('the page', () => {
  it('says since when, the cause, and what happened before with whose it was', async () => {
    open()
    await screen.findByRole('heading', { name: 'Plex', level: 1 })
    expect(sent.find((one) => one.path.startsWith('/diagnosis'))?.path).toBe('/diagnosis?ref=integration%3A3')
    expect(screen.getByTestId('diagnosis-state').textContent).toContain('(20 min)')
    const cause = screen.getByTestId('diagnosis-cause')
    expect(cause.textContent).toContain('Probably because of docker-live')
    expect(within(cause).getByRole('link').getAttribute('href')).toBe('/diagnosis?ref=integration%3A2')
    const lines = screen.getByTestId('diagnosis-lines')
    const items = [...lines.querySelectorAll('li')]
    // The version first, then the mark where it began, then the outage.
    expect(items.map((one) => one.getAttribute('data-testid') ?? one.getAttribute('data-whose'))).toEqual(['above', 'diagnosis-mark', 'self'])
    expect(within(lines).getByText('hangs on: docker-live')).toBeTruthy()
    expect(screen.getAllByTestId('diagnosis-above').map((one) => one.textContent)).toEqual([expect.stringContaining('docker-live'), expect.stringContaining('plex')])
    expect(screen.getByTestId('diagnosis-me').textContent).toContain('this service')
  })

  it('reads the log only on asking', async () => {
    open()
    await screen.findByRole('heading', { name: 'Plex', level: 1 })
    expect(sent.some((one) => one.path === '/diagnosis/log')).toBe(false)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Show the log' }))
    })
    expect(sent.find((one) => one.path === '/diagnosis/log')?.body).toEqual({ ref: 'integration:3' })
    const shown = await screen.findByTestId('diagnosis-log-lines')
    expect(shown.textContent).toContain('ERROR Database is locked')
    expect(shown.querySelector('.text-bad')?.textContent).toBe('ERROR Database is locked')
  })

  it('says why there is no log', async () => {
    served = page({ log: { available: false, why: 'no_logs', engine: 'Unraid' } })
    open()
    expect((await screen.findByTestId('diagnosis-log')).textContent).toContain('Unraid gives no container logs.')
    expect(screen.queryByRole('button', { name: 'Show the log' })).toBeNull()
  })

  it('draws the runbook from markdown, and writes it', async () => {
    open()
    const runbook = await screen.findByTestId('diagnosis-runbook')
    await waitFor(() => expect(runbook.querySelector('ol strong')?.textContent).toBe('docker-live'))
    expect(within(runbook).getByRole('link').getAttribute('href')).toBe('https://notes.example.com/plex')
    fireEvent.click(within(runbook).getByRole('button', { name: 'Edit' }))
    fireEvent.change(within(runbook).getByLabelText('Link to a longer guide (optional)'), { target: { value: 'javascript:alert(1)' } })
    fireEvent.click(within(runbook).getByRole('button', { name: 'Save' }))
    expect(within(runbook).getByRole('alert').textContent).toBe('A link starts with http:// or https://.')
    expect(sent.some((one) => one.method === 'PUT')).toBe(false)
    fireEvent.change(within(runbook).getByLabelText('What to do'), { target: { value: 'Wait for the NAS' } })
    fireEvent.change(within(runbook).getByLabelText('Link to a longer guide (optional)'), { target: { value: '' } })
    await act(async () => {
      fireEvent.click(within(runbook).getByRole('button', { name: 'Save' }))
    })
    expect(sent.find((one) => one.method === 'PUT')).toEqual({ method: 'PUT', path: '/diagnosis/runbook', body: { ref: 'integration:3', text: 'Wait for the NAS', link: '' } })
    expect(within(runbook).queryByRole('link')).toBeNull()
  })

  it('asks before a button runs, with what it would hit', async () => {
    open()
    await screen.findByRole('heading', { name: 'Plex', level: 1 })
    fireEvent.click(within(screen.getByTestId('diagnosis-buttons')).getByRole('button', { name: 'Restart' }))
    await waitFor(() => expect(screen.getByTestId('action-impact')).toBeTruthy())
    expect(sent.some((one) => one.path === '/widgets/5/actions/restart')).toBe(false)
    await act(async () => {
      fireEvent.click(within(screen.getByRole('dialog')).getAllByRole('button').at(-1) as HTMLElement)
    })
    expect(sent.find((one) => one.path === '/widgets/5/actions/restart')?.body).toEqual({ params: { id: 'c1' } })
  })

  it('hands the question to the chat with the service it is about', async () => {
    open()
    await screen.findByRole('heading', { name: 'Plex', level: 1 })
    fireEvent.click(screen.getByRole('button', { name: 'Explain it' }))
    expect(useAssistant.getState()).toMatchObject({ open: true, asking: 'Why is Plex in trouble?', about: 'integration:3' })
  })

  it('shows a trouble that ended from its start to its end', async () => {
    served = page({ state: 'past', since: NOW - 3600, until: NOW - 3600 + 41 * 60 })
    open(diagnosisPath('integration:3', NOW - 3000))
    await screen.findByRole('heading', { name: 'Plex', level: 1 })
    expect(sent.find((one) => one.path.startsWith('/diagnosis'))?.path).toBe(`/diagnosis?ref=integration%3A3&at=${NOW - 3000}`)
    expect(screen.getByTestId('diagnosis-state').textContent).toMatch(/^Was red from .* to .*\(41 min\)$/)
    expect(screen.getAllByTestId('diagnosis-mark')).toHaveLength(2)
    expect(screen.getByTestId('diagnosis-cause').textContent).toContain('It was because of docker-live')
  })

  it('is nothing for anybody but an administrator', () => {
    useAuth.setState({ user: { id: 2, username: 'kim', role: 'user' } as never })
    open()
    expect(screen.queryByTestId('diagnosis-page')).toBeNull()
    expect(sent).toEqual([])
  })
})

describe('the way to it', () => {
  const VIEW: WidgetView = { id: 3, kind: 'plex.nowplaying', title: 'Plex', icon: '', link: '', renderer: 'list', options: {}, integration_id: 3, integration_name: 'Plex', refresh_seconds: 30 }

  it('stands on a red card for an administrator, and leads to its connection', () => {
    render(<MemoryRouter><WidgetCard widget={VIEW} data={{ status: 'unknown', error: 'Connection refused' }} /></MemoryRouter>)
    expect(screen.getByTestId('why-link').getAttribute('href')).toBe('/diagnosis?ref=integration%3A3')
  })

  it('is not there for a member, nor on a green card', () => {
    const { unmount } = render(<MemoryRouter><WidgetCard widget={VIEW} data={{ status: 'ok' }} /></MemoryRouter>)
    expect(screen.queryByTestId('why-link')).toBeNull()
    unmount()
    useAuth.setState({ user: { id: 2, username: 'kim', role: 'user' } as never })
    render(<MemoryRouter><WidgetCard widget={VIEW} data={{ status: 'unknown', error: 'Connection refused' }} /></MemoryRouter>)
    expect(screen.queryByTestId('why-link')).toBeNull()
  })

  it('stands on a row of the attention card and on a line of the chronicle', () => {
    render(
      <MemoryRouter>
        <AttentionCard widget={{ ...VIEW, kind: 'core.problems', renderer: 'attention', integration_id: null }} data={{ status: 'bad', items: [
          { title: 'Radarr', status: 'bad', source: 'card', subject: 'integration:4' },
          { title: 'Disk full', status: 'warn', source: 'bell', notice: 9 },
        ] }} />
        <ChronicleRow line={{ id: 1, when: NOW, kind: 'outage', level: 'bad', name: 'Wiki', before: '', after: '', detail: '', board: '', subject: 'tile:9' }} />
        <ChronicleRow line={{ id: 2, when: NOW, kind: 'version', level: 'info', name: 'Sonarr', before: '4.0', after: '4.1', detail: '', board: '', subject: 'integration:5' }} />
      </MemoryRouter>,
    )
    expect(screen.getAllByTestId('why-link').map((one) => one.getAttribute('href'))).toEqual([
      '/diagnosis?ref=integration%3A4',
      `/diagnosis?ref=tile%3A9&at=${NOW}`,
    ])
  })

  it('knows whom a card is about, and how long', () => {
    expect(subjectOf(VIEW)).toBe('integration:3')
    expect(subjectOf({ id: 8, integration_id: null, renderer: 'app' })).toBe('tile:8')
    expect(subjectOf({ id: 8, integration_id: null, renderer: 'clock' })).toBeNull()
    const t = (key: string, values?: Record<string, unknown>) => `${key.split('.').pop()} ${JSON.stringify(values)}`
    expect(lengthOf(41 * 60, t)).toBe('minutes {"minutes":41}')
    expect(lengthOf(6 * 3600 + 46 * 60, t)).toBe('hours {"hours":6,"minutes":46}')
    expect(lengthOf(30 * 3600, t)).toBe('hours {"hours":30,"minutes":0}')
    expect(lengthOf(50 * 3600, t)).toBe('days {"days":2,"hours":2}')
  })
})
