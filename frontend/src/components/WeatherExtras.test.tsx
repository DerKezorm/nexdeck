/** The weather card's hourly strip and air chips: what they draw, and that a card which asked for neither is as it was. */
import { render, screen, within } from '@testing-library/react'

import type { WidgetData, WidgetView } from '../lib/types'
import { renderWidget } from './renderers'
import { AirChips, clockText, HourlyStrip, hourText, levelKey, type Air, type Hourly } from './WeatherExtras'

const widget: WidgetView = { id: 5, kind: 'weather.current', title: 'Weather', icon: 'cloud', link: '', renderer: 'weather', options: {}, integration_id: null, refresh_seconds: null }

function hours(count: number, from = 16): Hourly {
  const items = Array.from({ length: count }, (_, index) => {
    const hour = (from + index) % 24
    return { at: `2026-10-27T${String(hour).padStart(2, '0')}:00`, temperature: 10 + (index % 7), rain: index === 3 ? 70 : 0, night: hour < 7 || hour >= 17 }
  })
  return { hours: count, items, sun: [{ index: 1, kind: 'sunset', time: '16:46' }, { index: 14, kind: 'sunrise', time: '06:55' }] }
}

function data(meta: Record<string, unknown>): WidgetData {
  return { status: 'ok', primary: { label: 'Berlin', value: 14.8, unit: '°C' }, items: [], meta: { condition: 'overcast', is_day: true, ...meta } } as unknown as WidgetData
}

describe('the hourly strip', () => {
  it('draws one column per hour and marks the night ones', () => {
    render(<HourlyStrip hourly={hours(12)} />)
    const columns = screen.getAllByTestId('hourly-hour')
    expect(columns).toHaveLength(12)
    expect(columns.map((column) => column.getAttribute('data-night'))).toEqual(['false', 'true', 'true', 'true', 'true', 'true', 'true', 'true', 'true', 'true', 'true', 'true'])
  })

  it('puts the sun at the hour it rises and sets, and says when', () => {
    render(<HourlyStrip hourly={hours(24)} />)
    const columns = screen.getAllByTestId('hourly-hour')
    expect(within(columns[1]).getByTestId('sun-sunset')).toBeInTheDocument()
    expect(within(columns[14]).getByTestId('sun-sunrise')).toBeInTheDocument()
    expect(screen.getAllByTestId(/^sun-/)).toHaveLength(2)
    expect(screen.getByText(/Sunset/)).toHaveTextContent(clockText('16:46', 'en'))
    expect(screen.getByText(/Sunrise/)).toHaveTextContent(clockText('06:55', 'en'))
  })

  it('names the hour with the most rain, and says so when there is none', () => {
    const { unmount } = render(<HourlyStrip hourly={hours(12)} />)
    expect(screen.getByText(/Rain up to 70 %/)).toHaveTextContent(hourText('2026-10-27T19:00', 'en'))
    unmount()
    const dry = hours(12)
    dry.items.forEach((row) => (row.rain = 0))
    render(<HourlyStrip hourly={dry} />)
    expect(screen.getByText('No rain expected')).toBeInTheDocument()
  })

  it('leaves a missing temperature a gap and a missing rain value out of the sentence', () => {
    const gappy = hours(12)
    gappy.items[2].temperature = null
    gappy.items.forEach((row) => (row.rain = null))
    render(<HourlyStrip hourly={gappy} />)
    const columns = screen.getAllByTestId('hourly-hour')
    expect(columns[2].querySelector('i')).toBeNull()
    expect(columns[3].querySelector('i')).not.toBeNull()
    expect(screen.queryByText(/Rain up to/)).toBeNull()
    expect(screen.queryByText('No rain expected')).toBeNull()
  })

  it('writes the hour of the place and does not convert it', () => {
    expect(hourText('2026-10-27T03:00', 'de')).toBe(new Date(2000, 0, 1, 3).toLocaleTimeString('de', { hour: 'numeric' }))
    expect(hourText('2026-10-27T03:00', 'en')).toMatch(/^3\s?AM$/)
    expect(hourText('nonsense', 'en')).toBe('nonsense')
  })
})

describe('the air chips', () => {
  const air: Air = {
    aqi: { value: 31, level: 'fair' },
    uv: { value: 0.1, level: 'low', peak: 2 },
    pollen: { level: 'very-high', items: [{ kind: 'birch', value: 240, level: 'very-high' }, { kind: 'grass', value: 61, level: 'high' }] },
  }

  it('shows each thing that came, with its level and its colour', () => {
    render(<AirChips air={air} />)
    const chips = screen.getByTestId('air-chips')
    expect(chips.querySelector('[data-kind="aqi"]')).toHaveTextContent('Air quality 31 · Fair')
    expect(chips.querySelector('[data-kind="aqi"] .dot')).toHaveAttribute('data-status', 'ok')
    expect(chips.querySelector('[data-kind="uv"]')).toHaveTextContent(/UV 0\.1 · Low · peak 2/)
    expect(chips.querySelector('[data-kind="pollen"]')).toHaveTextContent('Pollen Birch 240, Grass 61')
    expect(chips.querySelector('[data-kind="pollen"] .dot')).toHaveAttribute('data-status', 'bad')
  })

  it('says "none" for a pollen-free season and draws nothing for what did not come', () => {
    const { unmount } = render(<AirChips air={{ pollen: { level: 'none', items: [] } }} />)
    expect(screen.getByTestId('air-chips')).toHaveTextContent('Pollen None')
    expect(screen.getByTestId('air-chips').querySelectorAll('.chip')).toHaveLength(1)
    unmount()
    const { container } = render(<AirChips air={{}} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('admits that the air data is missing when the service failed', () => {
    render(<AirChips air={{}} unavailable />)
    expect(screen.getByText('Air data unavailable')).toBeInTheDocument()
  })

  it('turns a level word into the key it is stored under', () => {
    expect(levelKey('very-poor')).toBe('veryPoor')
    expect(levelKey('extremely-poor')).toBe('extremelyPoor')
    expect(levelKey('good')).toBe('good')
  })
})

describe('the weather card', () => {
  it('draws the strip and the chips for a card that asked, after they have loaded', async () => {
    render(<>{renderWidget({ widget, data: data({ hourly: hours(12), air: { aqi: { value: 31, level: 'fair' } } }) })}</>)
    expect(await screen.findByTestId('hourly-strip')).toBeInTheDocument()
    expect(await screen.findByTestId('air-chips')).toBeInTheDocument()
  })

  it('stays what it was for a card that asked for nothing', () => {
    const { container } = render(<>{renderWidget({ widget, data: data({}) })}</>)
    expect(screen.queryByTestId('hourly-strip')).toBeNull()
    expect(screen.queryByTestId('air-chips')).toBeNull()
    expect(container.querySelector('.scroll')).toBeNull()
  })

  it('says the air data is missing even when nothing else came', async () => {
    render(<>{renderWidget({ widget, data: data({ air: {}, air_unavailable: true }) })}</>)
    expect(await screen.findByText('Air data unavailable')).toBeInTheDocument()
  })
})
