/**
 * Long history and forecasts on the card (roadmap M4): the quiet line at the
 * foot, the range buttons on a chart card, and the chart over weeks with its
 * band and the forecast carried on, dashed, to its limit.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import i18n from 'i18next'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { lineText } from '../lib/chronicle'
import { carriesOn, forecastTone, forecastWords, type Forecast } from '../lib/forecast'
import type { WidgetData, WidgetView } from '../lib/types'
import { ChartCard } from './renderers'
import { WidgetCard } from './WidgetCard'

const asked: string[] = []
const DAY = 86400
const now = Math.floor(Date.now() / 1000)
const LONG = Array.from({ length: 30 }, (_, index) => [now - (30 - index) * DAY, 60 + index, 58 + index, 63 + index])

vi.mock('../api/client', async (original) => ({
  ...(await original<typeof import('../api/client')>()),
  get: vi.fn(async (path: string) => {
    asked.push(path)
    if (path.includes('/history/long')) return { used: LONG }
    return { used: [[now - 60, 80], [now, 81]] }
  }),
}))

vi.mock('../lib/useBoxSize', () => ({ useBoxSize: () => ({ width: 400, height: 200 }) }))

const t = i18n.getFixedT('en')

const FULL: Forecast = { kind: 'full', metric: 'used', row: 'Volume 1', days: 32.4, at: now + 32 * DAY, limit: 100, slope: 0.5, now: 89 }

const VIEW: WidgetView = {
  id: 7, kind: 'synology.volumes', title: 'NAS', icon: '', link: '', renderer: 'chart', options: {}, integration_id: 1, integration_name: 'NAS', refresh_seconds: 60,
}

describe('the words of a forecast', () => {
  it('names the row, the days and the day it comes to', () => {
    const { text, when } = forecastWords(FULL, t, 'en')
    expect(text).toBe('Volume 1 full in about 32 days')
    expect(when).toMatch(/^around /)
    expect(forecastWords({ ...FULL, row: null, days: 0.6 }, t, 'en').text).toBe('Full in about a day')
    expect(forecastWords({ kind: 'level', metric: 'cpu', line: 'bad', days: 9 }, t, 'en').text).toBe('Reaches red in about 9 days')
    expect(forecastWords({ kind: 'slower', metric: 'duration:photos', row: 'photos', per_week: 125 }, t, 'en').text).toBe('photos takes longer every week, +2 min a week')
  })

  it('is red under the two weeks it is told at, yellow for a line, quiet otherwise', () => {
    expect(forecastTone(FULL)).toBe('quiet')
    expect(forecastTone({ ...FULL, days: 6 })).toBe('bad')
    expect(forecastTone({ kind: 'level', metric: 'cpu', line: 'bad', days: 23 })).toBe('warn')
    expect(forecastTone({ kind: 'slower', metric: 'x' })).toBe('quiet')
  })

  it('is carried on only on the line it was worked out on', () => {
    expect(carriesOn(FULL, 'used')).toBe(true)
    expect(carriesOn(FULL, 'other')).toBe(false)
    expect(carriesOn({ kind: 'slower', metric: 'used' }, 'used')).toBe(false)
    expect(carriesOn(null, 'used')).toBe(false)
  })

  it('reads in the chronicle', () => {
    const line = { id: 1, at: now, kind: 'forecast', level: 'warn', name: 'Volume 1 (NAS)', before: 'full', after: '6', detail: '' }
    expect(lineText(line as never, t, 'en')).toBe('Volume 1 (NAS) will be full in about 6 days')
    expect(lineText({ ...line, before: 'bad', after: '1' } as never, t, 'en')).toBe('Volume 1 (NAS) reaches red in about a day')
  })
})

/** Node's own half-made localStorage hides jsdom's in this runner; a plain map stands in (as in player.test). */
function memoryStorage(): Storage {
  const items = new Map<string, string>()
  return {
    get length() {
      return items.size
    },
    clear: () => items.clear(),
    getItem: (key) => items.get(key) ?? null,
    key: (index) => [...items.keys()][index] ?? null,
    removeItem: (key) => void items.delete(key),
    setItem: (key, value) => void items.set(key, String(value)),
  }
}

describe('on the card', () => {
  beforeEach(() => {
    asked.length = 0
    vi.stubGlobal('localStorage', memoryStorage())
  })

  it('stands as a quiet line at the foot, and not on a card that failed', () => {
    const view = { ...VIEW, renderer: 'value' }
    const { rerender } = render(<WidgetCard widget={view} data={{ status: 'ok', primary: { label: 'Used', value: 89 }, forecast: { ...FULL, days: 6, told: true } }} />)
    const line = screen.getByTestId('forecast')
    expect(line.textContent).toContain('Volume 1 full in about 6 days')
    expect(line.textContent).toContain('told')
    expect(line.className).toContain('text-bad')
    rerender(<WidgetCard widget={view} data={{ status: 'unknown', error: 'down', forecast: FULL }} />)
    expect(screen.queryByTestId('forecast')).toBeNull()
  })

  it('switches a chart card to a month and back, kept for this browser only', async () => {
    const data: WidgetData = { status: 'ok', primary: { label: 'Used', value: 89, metric: 'used' }, metrics: { used: 89 }, meta: { renderer: 'chart', chart_hours: 24 }, forecast: FULL }
    render(<ChartCard widget={VIEW} data={data} series={{}} />)
    expect(screen.getAllByRole('button').map((button) => button.textContent)).toEqual(['24 h', '7 d', '30 d', '1 y'])
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '30 d' }))
    })
    await waitFor(() => expect(screen.getByTestId('long-chart')).toBeTruthy())
    expect(asked.some((path) => path === '/widgets/7/history/long?days=30')).toBe(true)
    expect(localStorage.getItem('nexdeck.chart.7')).toBe('720')
    expect(screen.getByTestId('long-chart-band')).toBeTruthy()
    expect(screen.getByTestId('long-chart-ahead').textContent).toContain('reached around')
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '24 h' }))
    })
    expect(localStorage.getItem('nexdeck.chart.7')).toBeNull()
    expect(screen.queryByTestId('long-chart')).toBeNull()
  })

  it('draws no forecast over a week, where the limit lies far outside', async () => {
    localStorage.setItem('nexdeck.chart.7', '168')
    const data: WidgetData = { status: 'ok', metrics: { used: 89 }, meta: { renderer: 'chart', chart_hours: 24 }, forecast: FULL }
    render(<ChartCard widget={VIEW} data={data} series={{}} />)
    await waitFor(() => expect(screen.getByTestId('long-chart')).toBeTruthy())
    expect(screen.queryByTestId('long-chart-ahead')).toBeNull()
  })

  it('says what a point was on hover', async () => {
    localStorage.setItem('nexdeck.chart.7', '720')
    const data: WidgetData = { status: 'ok', metrics: { used: 89 }, meta: { renderer: 'chart', chart_hours: 24 } }
    render(<ChartCard widget={VIEW} data={data} series={{}} />)
    const chart = await screen.findByTestId('long-chart')
    chart.getBoundingClientRect = () => ({ left: 0, top: 0, width: 400, height: 200, right: 400, bottom: 200, x: 0, y: 0, toJSON: () => ({}) })
    fireEvent.pointerMove(chart.querySelector('svg') as SVGElement, { clientX: 200 })
    expect(screen.getByTestId('long-chart-tip').textContent).toMatch(/to/)
  })
})

describe('over a year', () => {
  beforeEach(() => {
    asked.length = 0
    vi.stubGlobal('localStorage', memoryStorage())
  })

  it('names the day the limit is reached, not only its month', async () => {
    localStorage.setItem('nexdeck.chart.7', '8760')
    const data: WidgetData = { status: 'ok', metrics: { used: 89 }, meta: { renderer: 'chart', chart_hours: 24 }, forecast: { ...FULL, days: 20, at: now + 20 * DAY } }
    render(<ChartCard widget={VIEW} data={data} series={{}} />)
    const ahead = await screen.findByTestId('long-chart-ahead')
    expect(asked).toContain('/widgets/7/history/long?days=365')
    expect(ahead.textContent).toMatch(/\d/)
  })
})
