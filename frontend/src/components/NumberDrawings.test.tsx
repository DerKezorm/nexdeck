/**
 * The LED bars and the seven segments of issue #39. The LEDs must light as
 * far as the share goes and colour by the lines drawn for them; the digits
 * must show the number as it is, without the grouping of a language.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { vi } from 'vitest'

import type { WidgetData, WidgetView } from '../lib/types'
import { ChartCard, GaugeCard, ledColour, MeterCard, SegmentsCard, segmentText } from './renderers'

const VIEW = { id: 1, renderer: 'value' } as unknown as WidgetView

function lights(container: HTMLElement): string[] {
  return [...container.querySelectorAll('[data-led]')].map((led) => led.getAttribute('data-led') ?? '')
}

function lightColours(container: HTMLElement): string[] {
  return [...container.querySelectorAll('[data-led="on"]')].map((led) => (led as HTMLElement).style.background)
}

describe('MeterCard', () => {
  it('lights as far as the share goes and keeps the measured number', () => {
    const { container } = render(
      <MeterCard widget={VIEW} data={{ status: 'ok', primary: { label: 'Download', value: 30, unit: 'MB/s' }, meta: { renderer: 'meter', gauge: { share: 25, max: 120 }, meter: { direction: 'across' } } } as WidgetData} />,
    )
    const row = lights(container)
    expect(row).toHaveLength(24)
    expect(row.filter((one) => one === 'on')).toHaveLength(6)
    // Lit from the start of the row, not scattered.
    expect(row.slice(0, 6).every((one) => one === 'on')).toBe(true)
    expect(screen.getByText('30MB/s')).toBeInTheDocument()
    expect(screen.getByText(/120MB\/s/)).toBeInTheDocument()
    expect(screen.getByRole('meter')).toHaveAttribute('aria-valuenow', '25')
  })

  it('stands upright when asked, with fewer lights', () => {
    const { container } = render(
      <MeterCard widget={VIEW} data={{ status: 'ok', primary: { label: 'CPU', value: 50, unit: '%' }, meta: { renderer: 'meter', gauge: { share: 50 }, meter: { direction: 'upright' } } } as WidgetData} />,
    )
    expect(lights(container)).toHaveLength(14)
    expect(lights(container).filter((one) => one === 'on')).toHaveLength(7)
  })

  it('colours the stretch past the lines, and only the lit lights', () => {
    const { container } = render(
      <MeterCard widget={VIEW} data={{ status: 'ok', primary: { label: 'CPU', value: 100, unit: '%' }, meta: { renderer: 'meter', gauge: { share: 100 }, meter: { direction: 'upright', zones: { warn: 50, bad: 75 } } } } as WidgetData} />,
    )
    const colours = lightColours(container)
    expect(colours.slice(0, 7).every((one) => one === 'var(--nd-ok)')).toBe(true)
    expect(colours.at(-1)).toBe('var(--nd-bad)')
    expect(colours).toContain('var(--nd-warn)')
  })

  it('without lines lights every lamp in the colour of the card', () => {
    const { container } = render(
      <MeterCard widget={VIEW} data={{ status: 'warn', primary: { label: 'CPU', value: 80, unit: '%' }, meta: { renderer: 'meter', gauge: { share: 80 }, meter: {} } } as WidgetData} />,
    )
    expect(new Set(lightColours(container))).toEqual(new Set(['var(--nd-warn)']))
  })
})

describe('ledColour', () => {
  it('turns round when red lies below yellow, as for free space', () => {
    const meter = { zones: { warn: 20, bad: 10 }, low_is_bad: true }
    expect(ledColour(5, meter, 'x')).toBe('var(--nd-bad)')
    expect(ledColour(15, meter, 'x')).toBe('var(--nd-warn)')
    expect(ledColour(60, meter, 'x')).toBe('var(--nd-ok)')
  })
})

describe('segmentText', () => {
  it('writes plain digits with the point after the right one, and no grouping', () => {
    expect(segmentText(1234.5)).toEqual({ chars: ['1', '2', '3', '4', '5'], points: new Set([3]) })
    expect(segmentText(-7)).toEqual({ chars: ['-', '7'], points: new Set() })
    expect(segmentText(0.25).chars).toEqual(['0', '2', '5'])
  })
})

describe('SegmentsCard', () => {
  it('lights the segments of each digit', () => {
    const { container } = render(
      <SegmentsCard widget={VIEW} data={{ status: 'ok', primary: { label: 'Temperature', value: 18, unit: '°C' } } as WidgetData} />,
    )
    const groups = [...container.querySelectorAll('svg > g > g')]
    expect(groups).toHaveLength(2)
    const lit = groups.map((group) => group.querySelectorAll('[data-segment="on"]').length)
    // "1" lights two segments, "8" all seven.
    expect(lit).toEqual([2, 7])
    expect(screen.getByRole('img')).toHaveAttribute('aria-label', '18°C')
    expect(screen.getByText('°C')).toBeInTheDocument()
  })

  it('takes its colour from the lines drawn for it, not from the status', () => {
    const { container } = render(
      <SegmentsCard widget={VIEW} data={{ status: 'ok', primary: { label: 'Load', value: 9, unit: '' }, meta: { renderer: 'segments', level: 'bad' } } as WidgetData} />,
    )
    const fills = [...container.querySelectorAll('[data-segment="on"]')].map((one) => one.getAttribute('fill'))
    expect(new Set(fills)).toEqual(new Set(['var(--nd-bad)']))
  })

  it('draws a word as a number card would', () => {
    render(<SegmentsCard widget={VIEW} data={{ status: 'ok', primary: { label: 'State', value: 'online' } } as WidgetData} />)
    expect(screen.queryByTestId('segments')).toBeNull()
  })
})

describe('GaugeCard colour', () => {
  it('follows the lines drawn for it', () => {
    const { container } = render(
      <GaugeCard widget={VIEW} data={{ status: 'ok', primary: { label: 'CPU', value: 90, unit: '%' }, meta: { renderer: 'gauge', gauge: { share: 90 }, level: 'warn' } } as WidgetData} />,
    )
    expect(container.querySelectorAll('path')[1]?.getAttribute('stroke')).toBe('var(--nd-warn)')
  })
})

describe('a floor and a stretch of history', () => {
  it('says what the dial runs between once a floor is named', () => {
    render(<GaugeCard widget={VIEW} data={{ status: 'ok', primary: { label: 'Room', value: 22, unit: '°C' }, meta: { renderer: 'gauge', gauge: { share: 50, min: 15, max: 29 } } } as WidgetData} />)
    expect(screen.getByText(/15°C to 29°C/)).toBeInTheDocument()
  })

  it('fetches the hours the chart was asked for and draws them', async () => {
    const asked: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      asked.push(String(input))
      return new Response(JSON.stringify({ cpu: [[1, 10], [2, 30], [3, 20]] }), { status: 200, headers: { 'content-type': 'application/json' } })
    }))
    render(<ChartCard widget={{ ...VIEW, id: 5 } as WidgetView} series={{}} data={{ status: 'ok', primary: { label: 'CPU', value: 20, unit: '%' }, metrics: { cpu: 20 }, meta: { renderer: 'chart', chart_hours: 6 } } as WidgetData} />)
    await waitFor(() => expect(asked.some((url) => url.includes('/widgets/5/history?hours=6'))).toBe(true))
    // The fetched line is drawn: lowest and highest of it, not "collecting".
    expect(await screen.findByText(/last 6 hours/)).toBeInTheDocument()
    expect(screen.getByText(/min 10/i)).toBeInTheDocument()
  })
})
