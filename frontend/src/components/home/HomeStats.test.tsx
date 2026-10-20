/**
 * Statistics cards on a home page in the browser: each style draws what the
 * server answers and writes what belongs under it, the period is switched
 * and asked again, what is missing says so (H of the board of sketches), and
 * cards are added, sized at their corner and given other sensors while
 * arranging. jsdom measures nothing; the cards are drawn at their own size.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, vi } from 'vitest'

import { axisRange, duration, reading, STAT_SIZES, statSize, type HomeAnswer, type HomeStat, type StatAnswer, type StatLine, type StatOffer } from '../../lib/home'
import { HomePage } from './HomePage'
import { timeLabels } from './StatChart'

type Sent = { url: string; method: string; body: Record<string, unknown> | null }

const HOUR = 3_600_000
const START = Date.UTC(2026, 9, 19, 10)
const LIVING = { rid: 'r-temp-living', entity_id: 'sensor.living_room_temperature', name: 'Living room temperature' }
const BED = { rid: 'r-temp-bed', entity_id: 'sensor.bedroom_temperature', name: 'Bedroom temperature' }
const ENERGY = { rid: 'r-energy', entity_id: 'sensor.house_energy', name: 'House energy' }

const card = (id: string, style: HomeStat['style'], sensors: HomeStat['sensors'], extra: Partial<HomeStat> = {}): HomeStat =>
  ({ id, type: 'stat', x: 16, y: 16, style, sensors, title: '', ...extra })

function line(sensor: { rid: string; entity_id: string; name: string }, extra: Partial<StatLine> = {}): StatLine {
  return {
    missing: false, ...sensor, unit: '°C', kind: 'mean', source: 'statistics', current: 21.3, unavailable: false, step: '5minute',
    points: Array.from({ length: 24 }, (_, hour) => [START + hour * HOUR, 20 + (hour % 6) / 4, 19.5 + (hour % 6) / 4, 20.5 + (hour % 6) / 4]),
    low: [19.5, START], high: [21.75, START + 5 * HOUR], mean: 20.6, total: null, ...extra,
  }
}

const stats = (series: StatAnswer['series'], extra: Partial<StatAnswer> = {}): StatAnswer =>
  ({ period: '24h', start: START, end: START + 24 * HOUR, now: START + 24 * HOUR, zone: 'Europe/Berlin', series, problem: null, ...extra })

const OFFER: StatOffer = {
  problem: null,
  sensors: [
    { ...BED, area: 'Bedroom', device: '', current: 18.9, unit: '°C', unavailable: false, device_class: 'temperature', kind: 'mean', source: 'history' },
    { ...ENERGY, area: '', device: '', current: 18342.6, unit: 'kWh', unavailable: false, device_class: 'energy', kind: 'sum', source: 'statistics' },
    { ...LIVING, area: 'Living room', device: '', current: 21.3, unit: '°C', unavailable: false, device_class: 'temperature', kind: 'mean', source: 'statistics' },
  ],
}

const page = (elements: HomeStat[]): HomeAnswer => ({ version: 1, problem: null, layout: { integration_id: 1, elements }, lights: {}, climates: {} })

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
beforeEach(() => vi.stubGlobal('localStorage', memoryStorage()))
afterEach(() => cleanup())

/** Shows a page of cards; ``answers`` says what each card's statistics are, by its id. */
function show(elements: HomeStat[], answers: Record<string, StatAnswer | ((period: string) => StatAnswer)>, { editing = false, canEdit = true } = {}) {
  const sent: Sent[] = []
  let answer = page(elements)
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : null
    sent.push({ url, method, body })
    const json = (value: unknown) => new Response(JSON.stringify(value), { status: 200, headers: { 'content-type': 'application/json' } })
    if (method === 'PUT') {
      answer = { ...answer, layout: { ...answer.layout, elements: body.elements }, version: answer.version + 1 }
      return json({ layout: answer.layout, version: answer.version })
    }
    const asked = url.match(/\/home\/stats\/([^?]+)\?period=(\w+)/)
    if (asked) {
      const said = answers[asked[1]]
      return json(typeof said === 'function' ? said(asked[2]) : said)
    }
    if (url.includes('/home/sensors')) return json(OFFER)
    return json(answer)
  }))
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <HomePage pageId={9} editing={editing} canEdit={canEdit} canAct onAddPage={() => undefined} onSettings={() => undefined} onDone={() => undefined} />
    </QueryClientProvider>,
  )
  return sent
}

const drawn = (id: string) =>
  waitFor(() => {
    const found = document.querySelector(`[data-stat="${id}"]`) as HTMLElement | null
    if (!found || found.querySelector('[data-chart], [data-empty], [data-value]') === null) throw new Error(`${id} is not drawn yet`)
    return found
  })
const puts = (sent: Sent[]) => sent.filter((one) => one.method === 'PUT')
const lastElements = (sent: Sent[]) => puts(sent).at(-1)!.body!.elements as Record<string, unknown>[]

it('draws a sensor as a line with now, low, high and mean, and asks again for another period', async () => {
  const sent = show([card('a', 'line', [LIVING])], { a: (period) => stats([line(LIVING)], { period: period as StatAnswer['period'] }) })
  const shown = await drawn('a')
  expect(shown.querySelector('b')).toHaveTextContent('Living room temperature')
  const numbers = shown.querySelector('[data-stats]') as HTMLElement
  expect(numbers).toHaveTextContent('now 21.3°')
  expect(numbers).toHaveTextContent('low 19.5°')
  expect(numbers).toHaveTextContent('high 21.8°')
  expect(numbers).toHaveTextContent('mean 20.6°')
  // The line runs on to where the sensor stands now: 24 points and the reading.
  expect((shown.querySelector('[data-line] path:last-of-type') as SVGPathElement).getAttribute('d')!.split('L')).toHaveLength(25)
  expect(sent.some((one) => one.url.endsWith('/pages/9/home/stats/a?period=24h'))).toBe(true)
  fireEvent.click(within(shown).getByRole('radio', { name: '7 d' }))
  await waitFor(() => expect(sent.some((one) => one.url.endsWith('/home/stats/a?period=7d'))).toBe(true))
  expect(within(shown).queryByRole('radio', { name: 'Day' })).not.toBeInTheDocument()
})

it('puts several rooms on one axis with a legend, and marks the sensor that is gone', async () => {
  const sent = show([card('b', 'rooms', [LIVING, BED, { rid: 'r-gone', entity_id: 'sensor.thrown_away', name: 'Old sensor' }], { title: 'Temperatures' })],
    { b: stats([line(LIVING), line(BED, { current: 18.4 }), { missing: true }]) })
  const shown = await drawn('b')
  expect(shown.querySelector('b')).toHaveTextContent('Temperatures')
  expect(shown.querySelectorAll('[data-line]')).toHaveLength(2)
  const legend = shown.querySelector('[data-legend]') as HTMLElement
  expect(legend).toHaveTextContent('Living room temperature 21.3°')
  expect(legend).toHaveTextContent('Bedroom temperature 18.4°')
  expect(legend).toHaveTextContent('Old sensor is gone from Home Assistant')
  // Several rooms start with their week, as on the board of sketches.
  expect(sent.some((one) => one.url.endsWith('/home/stats/b?period=7d'))).toBe(true)
  expect(within(shown).getByRole('radio', { name: '7 d' })).toHaveAttribute('aria-checked', 'true')
})

it('draws a counter as a bar a day with the total, the mean a day and today so far', async () => {
  const days = Array.from({ length: 7 }, (_, day) => [START + day * 24 * HOUR, [6.2, 7.8, 5.4, 9.1, 8.6, 7.2, 4.9][day]] as [number, number])
  show([card('d', 'bars', [ENERGY])], { d: stats([line(ENERGY, { unit: 'kWh', kind: 'sum', step: 'day', points: days, total: 49.2, mean: 7.03, low: null, high: null, latest: 4.9 })], { period: '7d' }) })
  const shown = await drawn('d')
  expect(shown.querySelectorAll('[data-bar]')).toHaveLength(7)
  const numbers = shown.querySelector('[data-stats]') as HTMLElement
  expect(numbers).toHaveTextContent('total 49.2 kWh')
  expect(numbers).toHaveTextContent('per day 7 kWh')
  expect(numbers).toHaveTextContent('today so far 4.9 kWh')
})

it('lays yesterday over today, dashed, and names the mean of each', async () => {
  const before = line(LIVING).points.map((point) => [point[0], point[1] - 0.4, point[2], point[3]] as [number, number, number, number])
  const sent = show([card('f', 'compare', [LIVING])], {
    f: (period) => stats([line(LIVING, { points: line(LIVING).points.slice(0, 14), previous: before, previous_summary: { low: null, high: null, mean: 20.2, total: null } })], { period: period as StatAnswer['period'] }),
  })
  const shown = await drawn('f')
  const paths = shown.querySelectorAll('[data-line]')
  expect(paths).toHaveLength(2)
  expect(paths[0].querySelector('path:last-of-type')).toHaveAttribute('stroke-dasharray', '3 3')
  const legend = shown.querySelector('[data-legend]') as HTMLElement
  expect(legend).toHaveTextContent('today, mean 20.6°')
  expect(legend).toHaveTextContent('yesterday, mean 20.2°')
  expect(sent.some((one) => one.url.endsWith('/home/stats/f?period=day'))).toBe(true)
  fireEvent.click(within(shown).getByRole('radio', { name: 'Week' }))
  await waitFor(() => expect(sent.some((one) => one.url.endsWith('/home/stats/f?period=week'))).toBe(true))
})

it('shows the small card as the value now with the low and high of the day', async () => {
  show([card('e', 'small', [LIVING])], { e: stats([line(LIVING)]) })
  const shown = await drawn('e')
  expect(shown.querySelector('[data-value]')).toHaveTextContent('21.3°')
  expect(shown).toHaveTextContent('24 h 19.5° · 21.8°')
  expect(shown.querySelectorAll('[role="radio"]')).toHaveLength(0)
})

it('says what is missing: a sensor without statistics, one that is gone, and a house that does not answer', async () => {
  show([card('h1', 'line', [BED]), card('h2', 'line', [{ rid: 'r-gone', entity_id: 'sensor.thrown_away', name: 'Old sensor' }], { y: 300 }), card('h3', 'band', [LIVING], { y: 600 })], {
    h1: stats([line(BED, { source: 'history', points: [], low: null, high: null, mean: null })]),
    h2: stats([{ missing: true }]),
    h3: stats([], { problem: { code: 'unreachable', message: 'Home Assistant could not be reached (OSError).', hint: '' } }),
  })
  expect(await drawn('h1')).toHaveTextContent('No statistics')
  expect(await drawn('h1')).toHaveTextContent('keeps no long-term statistics for “Bedroom temperature”')
  expect(await drawn('h2')).toHaveTextContent('Old sensor is gone from Home Assistant')
  expect((await drawn('h3')).querySelector('[data-empty]')).not.toBeNull()
})

it('adds one card for several rooms with its name, and one card each for a style of one sensor', async () => {
  const sent = show([], {}, { editing: true })
  // On an empty page twice: in the middle of it and in the bar.
  fireEvent.click((await screen.findAllByRole('button', { name: 'Statistics' }))[0])
  const dialog = await screen.findByRole('dialog')
  await within(dialog).findByText('House energy')
  expect(within(dialog).getByText('history only')).toBeInTheDocument()
  expect(within(dialog).getByText('counter')).toBeInTheDocument()
  fireEvent.change(within(dialog).getByRole('combobox'), { target: { value: 'rooms' } })
  fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Living room temperature' }))
  fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Bedroom temperature' }))
  fireEvent.change(within(dialog).getByPlaceholderText("empty: the sensor's name"), { target: { value: ' Upstairs ' } })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Add card' }))
  await waitFor(() => expect(puts(sent)).toHaveLength(1))
  expect(lastElements(sent)).toEqual([expect.objectContaining({ type: 'stat', style: 'rooms', title: 'Upstairs', x: 16, y: 16,
    sensors: [expect.objectContaining({ entity_id: 'sensor.living_room_temperature' }), expect.objectContaining({ entity_id: 'sensor.bedroom_temperature' })] })])
  expect(localStorage.getItem('nexdeck.homeStatStyle')).toBe('rooms')

  fireEvent.click(screen.getByRole('button', { name: 'Statistics' }))
  const again = await screen.findByRole('dialog')
  await within(again).findByText('House energy')
  fireEvent.change(within(again).getByRole('combobox'), { target: { value: 'line' } })
  fireEvent.click(within(again).getByRole('checkbox', { name: 'Living room temperature' }))
  fireEvent.click(within(again).getByRole('checkbox', { name: 'House energy' }))
  fireEvent.click(within(again).getByRole('button', { name: 'Add 2 cards' }))
  await waitFor(() => expect(puts(sent)).toHaveLength(2))
  const cards = lastElements(sent).slice(1)
  expect(cards.map((one) => [one.style, (one.sensors as { entity_id: string }[]).map((sensor) => sensor.entity_id)])).toEqual([
    ['line', ['sensor.living_room_temperature']], ['line', ['sensor.house_energy']]])
  // Below the rooms card, side by side, never on top of each other.
  expect(cards[0].y).toBeGreaterThanOrEqual(16 + STAT_SIZES.rooms.height)
  expect(cards[1].x).toBeGreaterThanOrEqual((cards[0].x as number) + STAT_SIZES.line.width)
})

it('sizes a card at its corner, on the step and inside its bounds', async () => {
  const sent = show([card('a', 'line', [LIVING], { x: 40, y: 40 })], { a: stats([line(LIVING)]) }, { editing: true })
  const shown = await drawn('a')
  const corner = shown.parentElement!.querySelector('[data-resize="both"]') as HTMLElement
  expect(corner).not.toBeNull()
  const element = document.querySelector('[data-element="a"]') as HTMLElement
  fireEvent.pointerDown(corner, { pointerId: 1, button: 0, clientX: 500, clientY: 500 })
  fireEvent.pointerMove(element, { pointerId: 1, clientX: 550, clientY: 530 })
  fireEvent.pointerMove(element, { pointerId: 1, clientX: 603, clientY: 541 })
  expect((document.querySelector('[data-stat="a"]') as HTMLElement).style.height).toBe('232px')
  fireEvent.pointerUp(element, { pointerId: 1, clientX: 603, clientY: 541 })
  await waitFor(() => expect(puts(sent)).toHaveLength(1))
  // 360 + 103 is 463, on the step 464 with nothing near to line up with; 190 + 41 on the step is 232; the place stays.
  expect(lastElements(sent)[0]).toMatchObject({ x: 40, y: 40, width: 464, height: 232 })
  fireEvent.pointerDown(corner, { pointerId: 2, button: 0, clientX: 500, clientY: 500 })
  fireEvent.pointerMove(element, { pointerId: 2, clientX: -2000, clientY: -2000 })
  fireEvent.pointerUp(element, { pointerId: 2, clientX: -2000, clientY: -2000 })
  await waitFor(() => expect(puts(sent)).toHaveLength(2))
  expect(lastElements(sent)[0]).toMatchObject({ width: 150, height: 80 })
})

it('gives a card other sensors and another style while arranging, and nothing of that to who only looks', async () => {
  const sent = show([card('b', 'rooms', [LIVING], { title: 'Rooms' })], { b: stats([line(LIVING)]) }, { editing: true })
  const shown = await drawn('b')
  const tools = shown.parentElement as HTMLElement
  fireEvent.click(within(tools).getByRole('button', { name: 'Choose sensors' }))
  const dialog = await screen.findByRole('dialog')
  await within(dialog).findByText('House energy')
  expect(within(dialog).getByRole('checkbox', { name: 'Living room temperature' })).toBeChecked()
  expect(within(dialog).getByDisplayValue('Rooms')).toBeInTheDocument()
  fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Bedroom temperature' }))
  fireEvent.click(within(dialog).getByRole('button', { name: 'Apply' }))
  await waitFor(() => expect(puts(sent)).toHaveLength(1))
  expect((lastElements(sent)[0].sensors as { entity_id: string }[]).map((one) => one.entity_id)).toEqual(['sensor.living_room_temperature', 'sensor.bedroom_temperature'])
  fireEvent.click(within(tools).getByRole('button', { name: 'Choose a style' }))
  fireEvent.click(within(tools).getByRole('menuitemradio', { name: 'Band' }))
  await waitFor(() => expect(puts(sent)).toHaveLength(2))
  expect(lastElements(sent)[0]).toMatchObject({ style: 'band', title: 'Rooms' })
  cleanup()

  show([card('b', 'rooms', [LIVING])], { b: stats([line(LIVING)]) }, { canEdit: false })
  const looked = await drawn('b')
  expect(within(looked.parentElement as HTMLElement).queryByRole('button', { name: 'Choose sensors' })).not.toBeInTheDocument()
  expect(looked.parentElement!.querySelector('[data-resize]')).toBeNull()
})

// ---------------------------------------------------------------------------
// The arithmetic
// ---------------------------------------------------------------------------

it('keeps a card inside its bounds and writes values as a card does', () => {
  expect(statSize(card('a', 'small', [LIVING]))).toEqual(STAT_SIZES.small)
  expect(statSize(card('a', 'line', [LIVING], { width: 5000, height: 2 }))).toEqual({ width: 1200, height: 80 })
  expect(reading(21.34, '°C')).toBe('21.3°')
  expect(reading(58, '%')).toBe('58 %')
  expect(reading(18342.6, 'kWh')).toBe('18343 kWh')
  expect(reading(null, 'kWh')).toBe('–')
  expect(duration(3 * 3600 + 20 * 60)).toBe('3 h 20')
  expect(duration(45 * 60)).toBe('45 min')
  expect(axisRange([20.1, 21.9])).toEqual([19, 23])
  expect(axisRange([4.9, 9.1], true)).toEqual([0, 11])
  expect(axisRange([21, 21])).toEqual([20, 22])
})

it('labels a chart by the hours, days and months of the house, not of the browser', () => {
  // 19.10.2026 12:00 in Berlin is 10:00 UTC; in New York it is 6:00.
  const from = Date.UTC(2026, 9, 19, 10)
  const day = timeLabels('24h', from, from + 24 * HOUR, 'Europe/Berlin', 'de', 360, 'jetzt')
  expect(day.map((one) => one[1])).toEqual(['12:00', '18:00', '0:00', '6:00', 'jetzt'])
  expect(timeLabels('24h', from, from + 24 * HOUR, 'America/New_York', 'de', 360, 'jetzt').map((one) => one[1])).toEqual(['6:00', '12:00', '18:00', '0:00', 'jetzt'])
  const week = timeLabels('7d', from, from + 7 * 24 * HOUR, 'Europe/Berlin', 'en', 360, 'now')
  expect(week.map((one) => one[1])).toEqual(['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'])
  const months = timeLabels('1y', from - 365 * 24 * HOUR, from, 'Europe/Berlin', 'en', 600, 'now')
  expect(months[0][1]).toBe('Nov')
  expect(months.map((one) => one[1]).at(-1)).toBe('Oct')
  expect(months).toHaveLength(12)
})
