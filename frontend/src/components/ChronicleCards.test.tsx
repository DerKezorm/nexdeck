/**
 * The chronicle's cards and page (roadmap M2): lines that lead to their card,
 * the daily report's facts, filters and paging, and "since" on a card.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { WidgetView } from '../lib/types'
import { ChroniclePage } from '../pages/ChroniclePage'
import { useAuth } from '../stores/auth'
import { ChronicleCard, ReportCard } from './ChronicleCards'
import { WidgetCard } from './WidgetCard'

const asked: string[] = []
let answer: (path: string) => unknown = () => ({ events: [], more: false })
vi.mock('../api/client', async (original) => ({
  ...(await original<typeof import('../api/client')>()),
  get: vi.fn(async (path: string) => {
    // The page's frame asks for the boards and the like; only the chronicle is counted.
    if (!path.startsWith('/chronicle')) return []
    asked.push(path)
    return answer(path)
  }),
}))

const VIEW: WidgetView = { id: 3, kind: 'core.chronicle', title: 'What happened', icon: '', link: '', renderer: 'chronicle', options: {}, integration_id: null, refresh_seconds: 30 }
const NOW = Date.now() / 1000
const LINES = [
  { id: 9, when: NOW - 60, kind: 'card', level: 'bad', name: 'Paperless', before: 'ok', after: 'bad', detail: 'The service could not be reached.', board: 'Infrastructure', target: { board: 'infra', page: 'overview', widget: 31 } },
  { id: 8, when: NOW - 3600, kind: 'version', level: 'info', name: 'Sonarr', before: '4.0.15', after: '4.0.16', detail: '', board: '' },
]

function Where() {
  const location = useLocation()
  return <p data-testid="where">{`${location.pathname} ${JSON.stringify(location.state)}`}</p>
}

function within(node: React.ReactNode, path = '/b/media') {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="*" element={<>{node}<Where /></>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('the chronicle card', () => {
  beforeEach(() => {
    useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin' } as never })
  })

  it('shows its lines and leads to the card a line is about', () => {
    within(<ChronicleCard widget={VIEW} data={{ status: 'ok', items: LINES }} />)
    const text = screen.getByTestId('chronicle-card').textContent ?? ''
    expect(text).toContain('Paperless turned red')
    expect(text).toContain('Sonarr runs 4.0.16 instead of 4.0.15')
    fireEvent.click(screen.getByText('Paperless turned red'))
    expect(screen.getByTestId('where').textContent).toBe('/b/infra/overview {"focus":31}')
  })

  it('says when nothing happened', () => {
    within(<ChronicleCard widget={VIEW} data={{ status: 'ok', items: [] }} />)
    expect(screen.getByText('Nothing happened yet.')).toBeTruthy()
  })
})

describe('the daily report card', () => {
  const quiet = { outages: [], red: [], now_red: [], versions: [], containers: [], restarted: [], backups: [] }

  it('counts and names what happened', () => {
    within(<ReportCard widget={{ ...VIEW, renderer: 'report' }} data={{ status: 'ok', meta: { report: { ...quiet, outages: ['Nextcloud'], now_red: ['Paperless'], versions: [{ name: 'Sonarr', before: '4.0.15', after: '4.0.16' }] } } }} />)
    const text = screen.getByTestId('report-card').textContent ?? ''
    expect(text).toContain('1outage')
    expect(text).toContain('Red now: Paperless')
    expect(text).toContain('New versions: Sonarr 4.0.15 → 4.0.16')
  })

  it('says a quiet day is quiet', () => {
    within(<ReportCard widget={{ ...VIEW, renderer: 'report' }} data={{ status: 'ok', meta: { report: quiet } }} />)
    expect(screen.getByText('Nothing happened in the last 24 hours, and nothing is red.')).toBeTruthy()
  })
})

describe('the chronicle page', () => {
  beforeEach(() => {
    asked.length = 0
    answer = () => ({ events: LINES, more: true })
    useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin' } as never })
  })

  it('heads the lines by day, filters and pages back', async () => {
    await act(async () => {
      within(<ChroniclePage />, '/chronicle')
    })
    expect(screen.getByText('Today')).toBeTruthy()
    expect(asked[0]).toBe('/chronicle?days=7&group=all&limit=100')

    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Versions and containers' })))
    expect(asked.at(-1)).toBe('/chronicle?days=7&group=versions&limit=100')
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'A year' })))
    expect(asked.at(-1)).toBe('/chronicle?days=365&group=versions&limit=100')

    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'sonarr' } })
    await act(async () => fireEvent.submit(screen.getByRole('searchbox').closest('form') as HTMLFormElement))
    expect(asked.at(-1)).toBe('/chronicle?days=365&group=versions&limit=100&q=sonarr')

    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Show older lines' })))
    expect(asked.at(-1)).toBe('/chronicle?days=365&group=versions&limit=100&q=sonarr&before=8')
  })

  it('offers the changes in nexdeck to an administrator only', async () => {
    useAuth.setState({ user: { id: 2, username: 'mia', role: 'user' } as never })
    await act(async () => {
      within(<ChroniclePage />, '/chronicle')
    })
    expect(screen.queryByRole('button', { name: 'Changes in nexdeck' })).toBeNull()
  })
})

describe('a yellow or red card says since when', () => {
  it('next to its reason', () => {
    const view: WidgetView = { id: 5, kind: 'demo.value', title: 'Synology', icon: '', link: '', renderer: 'value', options: { show_findings: true }, integration_id: null, refresh_seconds: 30 }
    render(<MemoryRouter><WidgetCard widget={view} data={{ status: 'warn', since: NOW - 120, meta: { status_reason: 'Volume 1 is 91 % full' } }} /></MemoryRouter>)
    expect(screen.getByTestId('card-reason').textContent).toMatch(/^Volume 1 is 91 % full · since /)
  })

  it('and a green card says nothing of it', () => {
    const view: WidgetView = { id: 6, kind: 'demo.value', title: 'Synology', icon: '', link: '', renderer: 'value', options: { show_findings: true }, integration_id: null, refresh_seconds: 30 }
    const { container } = render(<MemoryRouter><WidgetCard widget={view} data={{ status: 'ok', since: NOW - 120 }} /></MemoryRouter>)
    expect(screen.queryByTestId('card-reason')).toBeNull()
    expect(container.querySelector('.dot')?.getAttribute('title')).not.toContain('since')
  })
})
