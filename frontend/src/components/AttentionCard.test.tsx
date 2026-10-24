/**
 * The attention card as the mock-up was taken on 24.10.2026: a sentence with
 * red and yellow, rows with where and since when, "Show N more" for what does
 * not fit, a row that leads to its card, and the quiet lines below.
 */
import { act, fireEvent, render, screen } from '@testing-library/react'
import i18next from 'i18next'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setLanguage } from '../i18n/index'
import type { WidgetData, WidgetView } from '../lib/types'
import { useAuth } from '../stores/auth'
import { useNotices } from '../stores/notices'
import { AttentionCard } from './AttentionCard'
import { WidgetCard } from './WidgetCard'

const VIEW: WidgetView = {
  id: 9,
  kind: 'core.problems',
  title: 'Needs attention',
  icon: '',
  link: '',
  renderer: 'attention',
  options: {},
  integration_id: null,
  refresh_seconds: 15,
}

const NOW = Date.now() / 1000
const ROWS = [
  { title: 'Paperless', subtitle: 'ConnectError', status: 'bad', source: 'check', value: 'Infrastructure', since: NOW - 60, target: { board: 'infra', page: 'overview', widget: 31 } },
  { title: 'Backup failed', subtitle: 'Task Photos', status: 'warn', source: 'bell', notice: 77, since: NOW - 7200 },
  { title: 'Synology', subtitle: 'Volume 1 is 91 % full', status: 'warn', source: 'card', value: 'Infrastructure', target: { board: 'infra', page: 'overview', widget: 32 }, url: 'http://nas.example.com/' },
]

function data(items: Record<string, unknown>[], meta: Record<string, unknown> = {}): WidgetData {
  return { status: items.length ? 'bad' : 'ok', items, meta: { owner: 1, opens: 'card', counted: { cards: 31, checks: 12, boards: 3 }, updates: [], maintenance: [], ...meta } }
}

function Where() {
  const location = useLocation()
  return <p data-testid="where">{`${location.pathname} ${JSON.stringify(location.state)}`}</p>
}

function show(given: WidgetData) {
  return render(
    <MemoryRouter initialEntries={['/b/media']}>
      <Routes>
        <Route path="*" element={<><AttentionCard widget={VIEW} data={given} /><Where /></>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('AttentionCard', () => {
  let opened: string[] = []
  const original = window.open
  beforeEach(() => {
    opened = []
    window.open = ((url: string | URL | undefined) => {
      opened.push(String(url))
      return null
    }) as typeof window.open
    useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin' } as never })
  })
  afterEach(async () => {
    window.open = original
    await i18next.changeLanguage('en')
  })

  it('says all is good, what it looked at and the waiting updates on a quiet line', () => {
    show(data([], { updates: [{ title: 'Sonarr', value: '4.0.16' }, { title: 'Immich', value: '2.2.0' }] }))
    expect(screen.getByTestId('attention-fine').textContent).toContain('All good')
    expect(screen.getByTestId('attention-fine').textContent).toContain('31 cards, 12 checks, 3 boards')
    expect(screen.getByTestId('attention-updates').textContent).toContain('2 updates waiting: Sonarr 4.0.16, Immich 2.2.0')
  })

  it('opens with the sentence and the count of red and yellow, then where and since when', () => {
    show(data(ROWS))
    expect(screen.getByTestId('attention-head').textContent).toBe('3 things need attention')
    const text = screen.getByTestId('attention-rows').textContent ?? ''
    expect(text).toContain('1 red')
    expect(text).toContain('2 yellow')
    expect(text).toContain('Infrastructure · Check · since')
    expect(text).toContain('Notice · Bell')
    // A card that was yellow before anybody looked says no "since".
    expect(text).toMatch(/Infrastructure · Card(?! · since)/)
  })

  it('speaks German', async () => {
    await setLanguage('de')
    show(data(ROWS))
    expect(screen.getByTestId('attention-head').textContent).toBe('3 Dinge brauchen Aufmerksamkeit')
    expect(screen.getByTestId('attention-rows').textContent).toContain('Infrastructure · Prüfung · seit')
  })

  it('leads to the card on its board', () => {
    show(data(ROWS))
    fireEvent.click(screen.getByText('Synology'))
    expect(screen.getByTestId('where').textContent).toBe('/b/infra/overview {"focus":32}')
    expect(opened).toEqual([])
  })

  it('lights up a card that is on the page already, without going anywhere', () => {
    const card = document.createElement('section')
    card.setAttribute('data-widget', '32')
    card.scrollIntoView = vi.fn()
    document.body.appendChild(card)
    try {
      show(data(ROWS))
      fireEvent.click(screen.getByText('Synology'))
      expect(card.classList.contains('nd-focus')).toBe(true)
      expect(screen.getByTestId('where').textContent).toBe('/b/media null')
    } finally {
      card.remove()
    }
  })

  it('opens the service when the card is told to', () => {
    show(data(ROWS, { opens: 'service' }))
    fireEvent.click(screen.getByText('Synology'))
    expect(opened).toEqual(['http://nas.example.com/'])
  })

  it('lets the owner mark a warning of the bell as read, and nobody else', async () => {
    const markRead = vi.fn(async () => undefined)
    useNotices.setState({ markRead })
    show(data(ROWS))
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Mark as read' })))
    expect(markRead).toHaveBeenCalledWith([77])
    expect(screen.queryByText('Backup failed')).toBeNull()
    expect(screen.getByTestId('attention-head').textContent).toBe('2 things need attention')
  })

  it('shows no mark-as-read to somebody who is not the owner', () => {
    useAuth.setState({ user: { id: 2, username: 'kim', role: 'user' } as never })
    show(data(ROWS))
    expect(screen.queryByRole('button', { name: 'Mark as read' })).toBeNull()
  })

  it('turns what does not fit into "Show N more", which opens the whole list', () => {
    // jsdom lays nothing out: the list is 100 pixels high, each row 40.
    const height = vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockImplementation(function (this: HTMLElement) {
      return this.dataset.testid === 'attention-list' ? 100 : 0
    })
    const top = vi.spyOn(HTMLElement.prototype, 'offsetTop', 'get').mockImplementation(function (this: HTMLElement) {
      return Array.from(this.parentElement?.children ?? []).indexOf(this) * 40
    })
    const tall = vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(40)
    try {
      show(data(ROWS))
      expect(screen.getByTestId('attention-more').textContent).toBe('Show 1 more')
      fireEvent.click(screen.getByTestId('attention-more'))
      expect(screen.getByTestId('attention-whole').textContent).toContain('Synology')
    } finally {
      height.mockRestore()
      top.mockRestore()
      tall.mockRestore()
    }
  })

  it('takes the colour of the worst it lists, unless it has one of its own', () => {
    const { container, rerender } = render(<MemoryRouter><WidgetCard widget={VIEW} data={data(ROWS)} /></MemoryRouter>)
    const frame = container.querySelector('section') as HTMLElement
    expect(frame.dataset.status).toBe('bad')
    expect(frame.className).toContain('look-tint')
    expect(frame.getAttribute('style')).toContain('--nd-bad')
    rerender(<MemoryRouter><WidgetCard widget={{ ...VIEW, options: { card_colour: 'blue' } }} data={data(ROWS)} /></MemoryRouter>)
    expect(frame.getAttribute('style')).toContain('--nd-c-blue')
    rerender(<MemoryRouter><WidgetCard widget={VIEW} data={data([])} /></MemoryRouter>)
    expect(frame.className).not.toContain('look-tint')
  })

  it('names what is in maintenance on a quiet line', () => {
    show(data([], { maintenance: [{ title: 'Synology', until: new Date(2026, 9, 24, 22, 0).toISOString() }] }))
    expect(screen.getByTestId('attention-away').textContent).toMatch(/In maintenance: Synology until 22:00|In maintenance: Synology until 10:00/)
  })
})
