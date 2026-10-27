/** The calendar card as a week and a month: the days, today, the colours, the paging and the day that is picked. */
import { act, fireEvent, render, screen, within } from '@testing-library/react'

import i18n from '../i18n'
import type { Entry } from '../lib/calendarGrid'
import type { WidgetData, WidgetView } from '../lib/types'
import CalendarGrid from './CalendarGrid'
import { renderWidget } from './renderers'

const RANGE = { from: '2026-08-26', to: '2027-02-28' }

const entries: Entry[] = [
  { date: '2026-10-27', title: 'Standup', time: '09:30', source: 'Work', slot: 1, subtitle: 'Room 4' },
  { date: '2026-10-27', title: 'Holiday', source: 'Family', slot: 0, subtitle: 'all day' },
  { date: '2026-10-31', title: 'Plumber', time: '08:00', source: 'Family', slot: 0 },
  { date: '2026-10-31', title: 'Lunch', time: '12:30', source: 'Family', slot: 0 },
  { date: '2026-10-31', title: 'Sync', time: '15:30', source: 'Work', slot: 1 },
  { date: '2026-10-31', title: 'Football', time: '18:00', source: 'Family', slot: 0 },
  { date: '2026-10-31', title: 'Show', source: 'Sonarr', slot: 2 },
  { date: '2026-11-12', title: 'Next month', source: 'Family', slot: 0 },
]

const props = { items: entries, range: RANGE, nameOf: (entry: Entry) => String(entry.title), placeOf: (entry: Entry) => String(entry.subtitle ?? ''), sourceOf: (entry: Entry) => String(entry.source ?? '') }
const cell = (iso: string) => document.querySelector(`[data-testid="calendar-day"][data-day="${iso}"]`) as HTMLElement
const title = () => screen.getByTestId('calendar-title').textContent

beforeEach(async () => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 9, 27, 12, 0))
  await act(() => i18n.changeLanguage('de'))
})

afterEach(async () => {
  vi.useRealTimers()
  await act(() => i18n.changeLanguage('en'))
})

describe('the month', () => {
  it('begins its week on Monday in German and writes month and weekdays in German', () => {
    render(<CalendarGrid {...props} view="month" />)
    expect(title()).toBe('Oktober 2026')
    const heads = [...screen.getByTestId('calendar-grid').querySelectorAll('[aria-hidden="true"] span')].map((node) => node.textContent)
    expect(heads).toEqual(['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'])
    expect(screen.getAllByTestId('calendar-day')).toHaveLength(35)
    expect(screen.getAllByTestId('calendar-day')[0]).toHaveAttribute('data-day', '2026-09-28')
  })

  it('marks today and only today', () => {
    render(<CalendarGrid {...props} view="month" />)
    const marked = screen.getAllByTestId('calendar-day').filter((day) => day.hasAttribute('data-today'))
    expect(marked.map((day) => day.getAttribute('data-day'))).toEqual(['2026-10-27'])
  })

  it('draws three dots and a +2 for a crowded day, and two bars and a +3 on a wide card', () => {
    render(<CalendarGrid {...props} view="month" />)
    const day = cell('2026-10-31')
    const dots = within(day).getByTestId('calendar-dots')
    expect(dots.querySelectorAll('i')).toHaveLength(3)
    expect(dots).toHaveTextContent('+2')
    const bars = within(day).getByTestId('calendar-bars')
    expect(bars.querySelectorAll('span')).toHaveLength(2)
    expect(bars).toHaveTextContent('Plumber')
    expect(bars).toHaveTextContent('+3')
    // A day with one entry has nothing to count, and an empty day nothing at all.
    expect(within(cell('2026-10-27')).getByTestId('calendar-dots')).not.toHaveTextContent('+')
    expect(within(cell('2026-10-29')).queryByTestId('calendar-dots')).toBeNull()
  })

  it('colours an entry by its source', () => {
    render(<CalendarGrid {...props} view="month" />)
    const dots = [...within(cell('2026-10-27')).getByTestId('calendar-dots').querySelectorAll('i')].map((dot) => (dot as HTMLElement).style.background)
    // Holiday (source 0) is first as an all-day entry; the standup is source 1.
    expect(dots).toEqual(['var(--nd-accent)', 'var(--nd-c-violet)'])
  })

  it('shows the entries of the day that is clicked, and hides them when it is clicked again', () => {
    render(<CalendarGrid {...props} view="month" />)
    expect(screen.queryByTestId('calendar-picked')).toBeNull()
    fireEvent.click(cell('2026-10-31'))
    const picked = screen.getByTestId('calendar-picked')
    expect(picked).toHaveTextContent('Plumber')
    expect(picked).toHaveTextContent('Show')
    expect(picked.querySelectorAll('time')).toHaveLength(4)
    expect(cell('2026-10-31')).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(cell('2026-10-31'))
    expect(screen.queryByTestId('calendar-picked')).toBeNull()
  })

  it('says so when a picked day is empty', () => {
    render(<CalendarGrid {...props} view="month" />)
    fireEvent.click(cell('2026-10-29'))
    expect(screen.getByTestId('calendar-picked')).toHaveTextContent('Nothing on this day')
  })

  it('names every day with its number of entries for a screen reader', () => {
    render(<CalendarGrid {...props} view="month" />)
    expect(cell('2026-10-31').getAttribute('aria-label')).toMatch(/5$/)
    expect(cell('2026-10-29').getAttribute('aria-label')).toMatch(/0$/)
  })

  it('pages to the next month and back, drops the picked day, and offers a way home', () => {
    render(<CalendarGrid {...props} view="month" />)
    expect(screen.queryByRole('button', { name: 'Today' })).toBeNull()
    fireEvent.click(cell('2026-10-31'))
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(title()).toBe('November 2026')
    expect(screen.queryByTestId('calendar-picked')).toBeNull()
    expect(cell('2026-11-12')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Today' }))
    expect(title()).toBe('Oktober 2026')
    fireEvent.click(screen.getByRole('button', { name: 'Previous' }))
    expect(title()).toBe('September 2026')
  })

  it('stops paging where the entries stop', () => {
    render(<CalendarGrid {...props} view="month" range={{ from: '2026-10-01', to: '2026-11-30' }} />)
    expect(screen.getByRole('button', { name: 'Next' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
    expect(title()).toBe('Dezember 2026')
    fireEvent.click(screen.getByRole('button', { name: 'Today' }))
    fireEvent.click(screen.getByRole('button', { name: 'Previous' }))
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
  })

  it('keeps each viewer on their own page', () => {
    const { unmount } = render(<CalendarGrid {...props} view="month" />)
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    unmount()
    render(<CalendarGrid {...props} view="month" />)
    expect(title()).toBe('Oktober 2026')
  })

  it('names the sources in a key when there are several, and keeps them back in showcase mode', () => {
    const { unmount } = render(<CalendarGrid {...props} view="month" />)
    expect(screen.getByTestId('calendar-legend')).toHaveTextContent('Family')
    expect(screen.getByTestId('calendar-legend')).toHaveTextContent('Work')
    unmount()
    render(<CalendarGrid {...props} view="month" sourceOf={() => ''} />)
    expect(screen.queryByTestId('calendar-legend')).toBeNull()
  })
})

describe('the week', () => {
  it('has seven days from Monday with the entries and the times of each', () => {
    render(<CalendarGrid {...props} view="week" />)
    const days = screen.getAllByTestId('calendar-day')
    expect(days.map((day) => day.getAttribute('data-day'))).toEqual(['2026-10-26', '2026-10-27', '2026-10-28', '2026-10-29', '2026-10-30', '2026-10-31', '2026-11-01'])
    expect(days[1]).toHaveAttribute('data-today', 'true')
    expect(within(days[1]).getByText('Standup')).toBeInTheDocument()
    expect(within(days[1]).getByText('9:30')).toBeInTheDocument()
    expect(within(days[5]).getAllByText(/Plumber|Lunch|Sync|Football|Show/)).toHaveLength(5)
    expect(title()).toMatch(/26/)
  })

  it('pages by a week and picks a day by its heading', () => {
    render(<CalendarGrid {...props} view="week" />)
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getAllByTestId('calendar-day')[0]).toHaveAttribute('data-day', '2026-11-02')
    fireEvent.click(screen.getByRole('button', { name: 'Previous' }))
    fireEvent.click(within(cell('2026-10-27')).getByRole('button'))
    expect(screen.getByTestId('calendar-picked')).toHaveTextContent('Room 4')
  })

  it('begins on Sunday for English in the United States', async () => {
    await act(() => i18n.changeLanguage('en'))
    Object.defineProperty(window.navigator, 'language', { value: 'en-US', configurable: true })
    render(<CalendarGrid {...props} view="week" />)
    expect(screen.getAllByTestId('calendar-day')[0]).toHaveAttribute('data-day', '2026-10-25')
  })
})

describe('the calendar card', () => {
  const widget: WidgetView = { id: 8, kind: 'calendar.upcoming', title: 'Calendar', icon: 'calendar', link: '', renderer: 'calendar', options: {}, integration_id: null, refresh_seconds: null }
  const data = (meta: Record<string, unknown>, items: unknown[] = entries): WidgetData => ({ status: 'ok', items, meta }) as unknown as WidgetData

  it('draws the grid the server says, once it has loaded', async () => {
    render(<>{renderWidget({ widget, data: data({ view: 'month', range: RANGE }) })}</>)
    expect(await screen.findByTestId('calendar-grid')).toHaveAttribute('data-view', 'month')
  })

  it('draws the week when the server says week', async () => {
    render(<>{renderWidget({ widget, data: data({ view: 'week', range: RANGE }) })}</>)
    expect(await screen.findByTestId('calendar-grid')).toHaveAttribute('data-view', 'week')
  })

  it('is the list it was when the data names no view, and an empty list still says nothing is coming', () => {
    const { container } = render(<>{renderWidget({ widget, data: data({}) })}</>)
    expect(container.querySelector('[data-testid="calendar-grid"]')).toBeNull()
    expect(container.querySelectorAll('time').length).toBeGreaterThan(0)
    const { container: empty } = render(<>{renderWidget({ widget, data: data({}, []) })}</>)
    expect(empty).toHaveTextContent('Nothing coming up')
  })

  it('draws an empty grid rather than the empty message', async () => {
    render(<>{renderWidget({ widget, data: data({ view: 'month', range: RANGE }, []) })}</>)
    expect(await screen.findByTestId('calendar-grid')).toBeInTheDocument()
  })
})
