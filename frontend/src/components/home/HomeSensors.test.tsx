/**
 * Doors, windows, temperature and humidity on a home page in the browser:
 * each style says open for how long, closed, offline or gone, a battery that
 * runs out, the trend of the last hour; cards of several list what is open
 * and draw the house by its rooms; hints come from what stands on the page;
 * the picker makes one element each or one card of them all.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, vi } from 'vitest'

import {
  outdoors, pageHints, pairReadings, since, withNews,
  type ContactInfo, type HomeAnswer, type HomeElement, type ReadingInfo, type SensorState,
} from '../../lib/home'
import { HomePage } from './HomePage'

type Sent = { url: string; method: string; body: Record<string, unknown> | null }

const NOW = Date.now()
const MIN = 60_000

function contact(entity: string, name: string, area: string, extra: Partial<ContactInfo> = {}): ContactInfo {
  return { rid: `r-${entity}`, entity_id: `binary_sensor.${entity}`, name, area, device: '', device_id: `d-${entity}`, device_class: 'window', battery: null,
    open: false, since: NOW - 300 * MIN, unavailable: false, ...extra }
}
function sensor(entity: string, name: string, area: string, device: string, kind: 'temperature' | 'humidity', current: number, extra: Partial<ReadingInfo> = {}): ReadingInfo {
  return { rid: `r-${entity}`, entity_id: `sensor.${entity}`, name, area, device: `${area} sensor`, device_id: device, device_class: kind, battery: null, current, unit: kind === 'temperature' ? '°C' : '%',
    unavailable: false, ...extra }
}
const ref = (one: ContactInfo | ReadingInfo) => ({ rid: one.rid, entity_id: one.entity_id, name: one.name })

const KITCHEN = contact('kitchen_window', 'Kitchen window', 'Kitchen', { open: true, since: NOW - 12 * MIN })
const TERRACE = contact('terrace_door', 'Terrace door', 'Living room', { device_class: 'door', open: true, since: NOW - 4 * MIN })
const FRONT = contact('front_door', 'Front door', 'Hall', { device_class: 'door' })
const CELLAR = contact('cellar_window', 'Cellar window', 'Cellar', { battery: 8 })
const GUEST = contact('guest_window', 'Guest window', '', { open: null, unavailable: true })
const BATH_T = sensor('bath_temperature', 'Bathroom temperature', 'Bathroom', 'd-bath', 'temperature', 23.1, { trend: 0.4 })
const BATH_H = sensor('bath_humidity', 'Bathroom humidity', 'Bathroom', 'd-bath', 'humidity', 71)
const LIVING_T = sensor('living_temperature', 'Living room temperature', 'Living room', 'd-living', 'temperature', 21.3, { trend: -0.05 })
const OUT_H = sensor('outdoor_humidity', 'Outdoor humidity', 'Garden', 'd-weather', 'humidity', 91)
const GONE = { rid: 'r-gone', entity_id: 'binary_sensor.thrown_away', name: 'Old window' }

const STATES: Record<string, SensorState> = Object.fromEntries(
  [KITCHEN, TERRACE, FRONT, CELLAR, GUEST, BATH_T, BATH_H, LIVING_T, OUT_H].map((one) => [one.entity_id, { ...one, missing: false } as SensorState]),
)
STATES[GONE.entity_id] = { missing: true }

const at = (id: string, y: number, rest: Record<string, unknown>) => ({ id, x: 16, y, ...rest }) as HomeElement

function page(elements: HomeElement[], extra: Partial<HomeAnswer> = {}): HomeAnswer {
  return { version: 1, problem: null, layout: { integration_id: 1, elements }, lights: {}, climates: {}, sensors: STATES, ...extra }
}

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

function show(answer: HomeAnswer, { editing = false, canEdit = true } = {}) {
  const sent: Sent[] = []
  let current = answer
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : null
    sent.push({ url, method, body })
    const json = (value: unknown) => new Response(JSON.stringify(value), { status: 200, headers: { 'content-type': 'application/json' } })
    if (method === 'PUT') {
      current = { ...current, layout: { ...current.layout, elements: body.elements }, version: current.version + 1 }
      return json({ layout: current.layout, version: current.version })
    }
    if (url.includes('/home/contacts')) return json({ contacts: [KITCHEN, TERRACE, FRONT, CELLAR, GUEST], problem: null })
    if (url.includes('/home/readings')) return json({ readings: [BATH_T, BATH_H, LIVING_T, OUT_H], problem: null })
    return json(current)
  }))
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <HomePage pageId={9} editing={editing} canEdit={canEdit} canAct onAddPage={() => undefined} onSettings={() => undefined} onDone={() => undefined} />
    </QueryClientProvider>,
  )
  return sent
}

const find = (selector: string) =>
  waitFor(() => {
    const found = document.querySelector(selector) as HTMLElement | null
    if (!found) throw new Error(`${selector} is not drawn yet`)
    return found
  })
const puts = (sent: Sent[]) => sent.filter((one) => one.method === 'PUT')
const lastElements = (sent: Sent[]) => puts(sent).at(-1)!.body!.elements as Record<string, unknown>[]

// ---------------------------------------------------------------------------
// One door or window
// ---------------------------------------------------------------------------

it('says of a door or window that it is open and for how long, closed, offline or gone, and when its battery runs out', async () => {
  show(page([
    at('a', 16, { type: 'contact', ...ref(KITCHEN), style: 'pill' }),
    at('b', 64, { type: 'contact', ...ref(FRONT), style: 'pill' }),
    at('c', 112, { type: 'contact', ...ref(CELLAR), style: 'pill' }),
    at('d', 160, { type: 'contact', ...ref(GUEST), style: 'chip' }),
    at('e', 208, { type: 'contact', ...GONE, style: 'pill' }),
  ]))
  const kitchen = await find('[data-contact="binary_sensor.kitchen_window"]')
  expect(kitchen).toHaveAttribute('data-open', 'true')
  expect(kitchen.querySelector('[data-state]')).toHaveTextContent('open · 12 min')
  expect(document.querySelector('[data-contact="binary_sensor.front_door"] [data-state]')).toHaveTextContent('closed')
  expect(document.querySelector('[data-contact="binary_sensor.front_door"]')).not.toHaveAttribute('data-open')
  expect(document.querySelector('[data-contact="binary_sensor.cellar_window"] [data-battery]')).toHaveTextContent('8 %')
  expect(document.querySelector('[data-contact="binary_sensor.front_door"] [data-battery]')).toBeNull()
  expect(document.querySelector('[data-contact="binary_sensor.guest_window"] [data-state]')).toHaveTextContent('offline')
  expect(document.querySelector('[data-contact="binary_sensor.thrown_away"] [data-state]')).toHaveTextContent('gone')
  expect(document.querySelector('[data-contact="binary_sensor.thrown_away"]')).toHaveTextContent('Old window')
})

it('draws a window tilted and a door ajar while they are open, and a tile says since when', async () => {
  show(page([
    at('w', 16, { type: 'contact', ...ref(KITCHEN), style: 'window' }),
    at('d', 200, { type: 'contact', ...ref(FRONT), style: 'door' }),
    at('t', 400, { type: 'contact', ...ref(TERRACE), style: 'tile' }),
  ]))
  const window_ = await find('[data-contact="binary_sensor.kitchen_window"]')
  expect(window_.querySelector('polygon')).not.toBeNull()
  expect(document.querySelector('[data-contact="binary_sensor.front_door"] polygon')).toBeNull()
  const tile = document.querySelector('[data-contact="binary_sensor.terrace_door"]') as HTMLElement
  expect(tile.querySelector('[data-state]')).toHaveTextContent('Open')
  expect(tile).toHaveTextContent(/since \d/)
})

it('hears from the board stream that a window opened, and keeps its name and battery', () => {
  const before = page([at('c', 16, { type: 'contact', ...ref(CELLAR), style: 'pill' })])
  const after = withNews(before, { page_id: 9, sensors: { [CELLAR.entity_id]: { missing: false, open: true, since: NOW, unavailable: false } } })
  const said = after.sensors![CELLAR.entity_id]
  expect(said).toMatchObject({ open: true, since: NOW, name: 'Cellar window', battery: 8, area: 'Cellar' })
  expect(withNews(before, { page_id: 9, sensors: { [CELLAR.entity_id]: { missing: true } } }).sensors![CELLAR.entity_id]).toEqual({ missing: true })
})

// ---------------------------------------------------------------------------
// Several on one card
// ---------------------------------------------------------------------------

it('lists only what is open, and what cannot be read, with how many of all are open', async () => {
  show(page([at('f', 16, { type: 'contacts', style: 'list', title: '', sensors: [KITCHEN, TERRACE, FRONT, CELLAR, GUEST].map(ref) })]))
  const card = await find('[data-contacts="f"]')
  expect(card.querySelector('[data-count]')).toHaveTextContent('2 of 5 open')
  expect([...card.querySelectorAll('[data-listed]')].map((one) => one.getAttribute('data-listed'))).toEqual([KITCHEN.entity_id, TERRACE.entity_id, GUEST.entity_id])
  expect(card).toHaveTextContent('Windows and doors')
  expect(within(card).getByText('12 min')).toBeInTheDocument()
})

it('says all closed, and calls a card of windows windows', async () => {
  show(page([at('f', 16, { type: 'contacts', style: 'list', title: '', sensors: [FRONT, CELLAR].map(ref).slice(1) })]))
  const card = await find('[data-contacts="f"]')
  expect(card.querySelector('[data-count]')).toHaveTextContent('all closed')
  expect(card).toHaveTextContent('Windows')
  expect(card.querySelectorAll('[data-listed]')).toHaveLength(0)
})

it('draws the house by its rooms, a square per contact, those without a room last', async () => {
  show(page([at('g', 16, { type: 'contacts', style: 'house', title: 'Downstairs', sensors: [GUEST, KITCHEN, FRONT, TERRACE].map(ref) })]))
  const card = await find('[data-contacts="g"]')
  expect([...card.querySelectorAll('[data-room]')].map((one) => one.getAttribute('data-room'))).toEqual(['Kitchen', 'Hall', 'Living room', ''])
  expect([...card.querySelectorAll('[data-square]')].map((one) => one.getAttribute('data-square'))).toEqual(['open', 'closed', 'open', 'quiet'])
  expect(card.querySelector('[data-count]')).toHaveTextContent('2 open')
  expect(card).toHaveTextContent('Downstairs')
})

// ---------------------------------------------------------------------------
// Temperature and humidity
// ---------------------------------------------------------------------------

it('shows a temperature with the humidity of its device, the trend of the hour, and the humidity in its colour', async () => {
  show(page([
    at('h', 16, { type: 'reading', style: 'pill', name: '', temperature: ref(BATH_T), humidity: ref(BATH_H) }),
    at('i', 80, { type: 'reading', style: 'tile', name: 'Bath', temperature: ref(BATH_T), humidity: ref(BATH_H) }),
    at('j', 240, { type: 'reading', style: 'thermometer', name: '', temperature: ref(LIVING_T), humidity: null }),
    at('k', 440, { type: 'reading', style: 'ring', name: '', temperature: null, humidity: ref(BATH_H) }),
  ]))
  const pill = await find('[data-reading="h"]')
  expect(pill).toHaveTextContent('Bathroom')
  expect(pill.querySelector('[data-temperature]')).toHaveTextContent('23.1°')
  expect(pill.querySelector('[data-humidity]')).toHaveTextContent('71 %')
  const tile = document.querySelector('[data-reading="i"]') as HTMLElement
  expect(tile).toHaveTextContent('Bath')
  expect(tile.querySelector('[data-trend]')).toHaveTextContent('↑ 0.4')
  const thermometer = document.querySelector('[data-reading="j"]') as HTMLElement
  expect(thermometer.querySelector('[data-trend]')).toBeNull()
  // 21.3 on a scale of 10 to 30 from 92 to 14: a little more than half way up.
  expect(Number(thermometer.querySelector('[data-level]')!.getAttribute('data-level'))).toBe(48)
  expect(thermometer.querySelector('[data-humidity]')).toBeNull()
  const ring = document.querySelector('[data-reading="k"] [data-ring]') as SVGElement
  expect(ring.getAttribute('stroke')).toBe('rgb(56, 189, 248)')
})

it('lists rooms with their temperature, its trend and their humidity, and says which sensor is gone', async () => {
  show(page([at('l', 16, { type: 'readings', title: '', rows: [
    { name: 'Living room', temperature: ref(LIVING_T), humidity: null },
    { name: 'Bathroom', temperature: ref(BATH_T), humidity: ref(BATH_H) },
    { name: 'Attic', temperature: { rid: 'r-x', entity_id: 'sensor.attic', name: 'Attic' }, humidity: null },
  ] })], { sensors: { ...STATES, 'sensor.attic': { missing: true } } }))
  const card = await find('[data-readings="l"]')
  const rows = [...card.querySelectorAll('[data-row]')] as HTMLElement[]
  expect(rows.map((row) => row.textContent)).toEqual(['Living room21.3°→', 'Bathroom23.1°↑71 %', 'Atticgone'])
  expect(card).toHaveTextContent('Rooms')
})

// ---------------------------------------------------------------------------
// Hints
// ---------------------------------------------------------------------------

it('hints at a window open in a room that heats and a room that wants airing, not at the weather', () => {
  const elements = [
    at('t', 16, { type: 'contact', ...ref(TERRACE), style: 'pill' }),
    at('k', 16, { type: 'contact', ...ref(KITCHEN), style: 'pill' }),
    at('r', 16, { type: 'readings', title: '', rows: [{ name: 'Bath', temperature: null, humidity: ref(BATH_H) }, { name: 'Out', temperature: null, humidity: ref(OUT_H) }] }),
    at('c', 16, { type: 'climate', rid: 'r-heat', entity_id: 'climate.living', name: 'Living room', style: 'pill', sensor: null }),
  ]
  const heating = { area: 'Living room', action: 'heating', target: 21.5, missing: false } as const
  const answer = page(elements, { climates: { c: heating as never } })
  const hints = pageHints(elements, answer, ['heating', 'humid'])
  expect(hints.map((hint) => [hint.kind, hint.name])).toEqual([['heating', 'Terrace door'], ['humid', 'Bathroom']])
  expect(hints[0]).toMatchObject({ since: TERRACE.since, target: 21.5 })
  expect(pageHints(elements, answer, ['humid']).map((hint) => hint.kind)).toEqual(['humid'])
  const idle = page(elements, { climates: { c: { ...heating, action: 'idle' } as never } })
  expect(pageHints(elements, idle, ['heating'])).toEqual([])
  expect(outdoors('Außentemperatur')).toBe(true)
  expect(outdoors('Bathroom humidity', 'Bathroom', 'sensor.bathroom_humidity')).toBe(false)
})

it('says all is quiet when there is nothing to hint at, and looks only for what it was told while arranging', async () => {
  const sent = show(page([at('m', 16, { type: 'hints', title: '', checks: ['heating', 'humid'] })]), { editing: true })
  const card = await find('[data-hints="m"]')
  expect(card.querySelector('[data-quiet]')).toHaveTextContent('All quiet')
  fireEvent.click(within(card).getByRole('button', { name: 'What to look for' }))
  fireEvent.click(within(card).getByRole('menuitemcheckbox', { name: 'Airing from 65 % humidity' }))
  await waitFor(() => expect(puts(sent)).toHaveLength(1))
  expect(lastElements(sent)[0]).toMatchObject({ type: 'hints', checks: ['heating'] })
})

// ---------------------------------------------------------------------------
// Adding and arranging
// ---------------------------------------------------------------------------

it('adds a card of several doors and windows, or one element each', async () => {
  const sent = show(page([]), { editing: true })
  fireEvent.click((await screen.findAllByRole('button', { name: 'Door and window' }))[0])
  let dialog = await screen.findByRole('dialog')
  await within(dialog).findByText('Kitchen window')
  fireEvent.change(within(dialog).getByRole('combobox'), { target: { value: 'house' } })
  fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Kitchen window' }))
  fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Front door' }))
  fireEvent.change(within(dialog).getByPlaceholderText('empty: windows, doors or both'), { target: { value: ' Downstairs ' } })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }))
  await waitFor(() => expect(puts(sent)).toHaveLength(1))
  expect(lastElements(sent)).toEqual([expect.objectContaining({ type: 'contacts', style: 'house', title: 'Downstairs',
    sensors: [expect.objectContaining({ entity_id: KITCHEN.entity_id }), expect.objectContaining({ entity_id: FRONT.entity_id })] })])
  expect(localStorage.getItem('nexdeck.homeContactStyle')).toBe('house')

  fireEvent.click(screen.getByRole('button', { name: 'Sensor' }))
  fireEvent.click(screen.getByRole('menuitem', { name: 'Door and window' }))
  dialog = await screen.findByRole('dialog')
  await within(dialog).findByText('Kitchen window')
  fireEvent.change(within(dialog).getByRole('combobox'), { target: { value: 'window' } })
  fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Kitchen window' }))
  fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Cellar window' }))
  fireEvent.click(within(dialog).getByRole('button', { name: 'Add 2' }))
  await waitFor(() => expect(puts(sent)).toHaveLength(2))
  const added = lastElements(sent).slice(1)
  expect(added.map((one) => [one.type, one.style, one.entity_id])).toEqual([['contact', 'window', KITCHEN.entity_id], ['contact', 'window', CELLAR.entity_id]])
  expect(added[1].x).toBeGreaterThan(added[0].x as number)
})

it('offers a temperature and the humidity of one device as one, and a list of rooms as one card', async () => {
  const sent = show(page([]), { editing: true })
  fireEvent.click((await screen.findAllByRole('button', { name: 'Temperature and humidity' }))[0])
  const dialog = await screen.findByRole('dialog')
  await within(dialog).findByText('Bathroom sensor')
  // Four sensors of three devices: three to choose from.
  expect(within(dialog).getAllByRole('checkbox')).toHaveLength(3)
  fireEvent.change(within(dialog).getByRole('combobox'), { target: { value: 'rooms' } })
  for (const name of ['Bathroom sensor', 'Living room sensor']) fireEvent.click(within(dialog).getByRole('checkbox', { name }))
  fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }))
  await waitFor(() => expect(puts(sent)).toHaveLength(1))
  const [card] = lastElements(sent)
  expect(card).toMatchObject({ type: 'readings' })
  expect((card.rows as Record<string, { entity_id: string } | null | string>[]).map((row) => [row.name, (row.temperature as { entity_id: string } | null)?.entity_id, (row.humidity as { entity_id: string } | null)?.entity_id]))
    .toEqual([['Bathroom', BATH_T.entity_id, BATH_H.entity_id], ['Living room', LIVING_T.entity_id, undefined]])
})

it('changes the sensors of a card and keeps the one that is gone, and changes a style; nothing of that for who only looks', async () => {
  const sent = show(page([at('f', 16, { type: 'contacts', style: 'list', title: 'All', sensors: [ref(KITCHEN), GONE] }),
    at('p', 300, { type: 'contact', ...ref(FRONT), style: 'pill' })]), { editing: true })
  const card = await find('[data-contacts="f"]')
  fireEvent.click(within(card).getByRole('button', { name: 'Choose sensors' }))
  const dialog = await screen.findByRole('dialog')
  await within(dialog).findByText('Front door')
  expect(within(dialog).getByRole('checkbox', { name: 'Kitchen window' })).toBeChecked()
  fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Front door' }))
  fireEvent.click(within(dialog).getByRole('button', { name: 'Apply' }))
  await waitFor(() => expect(puts(sent)).toHaveLength(1))
  const changed = lastElements(sent)[0]
  expect((changed.sensors as { entity_id: string }[]).map((one) => one.entity_id)).toEqual([KITCHEN.entity_id, FRONT.entity_id, GONE.entity_id])
  expect(changed.title).toBe('All')
  const pill = document.querySelector('[data-contact="binary_sensor.front_door"]') as HTMLElement
  expect(pill.querySelector('[data-resize]')).not.toBeNull()
  fireEvent.click(within(pill).getByRole('button', { name: 'Choose a style' }))
  fireEvent.click(within(pill).getByRole('menuitemradio', { name: 'Door drawn' }))
  await waitFor(() => expect(puts(sent)).toHaveLength(2))
  expect(lastElements(sent)[1]).toMatchObject({ style: 'door' })
  cleanup()

  show(page([at('p', 16, { type: 'contact', ...ref(FRONT), style: 'pill' })]), { canEdit: false })
  const looked = await find('[data-contact="binary_sensor.front_door"]')
  expect(within(looked).queryByRole('button')).not.toBeInTheDocument()
  expect(looked.querySelector('[data-resize]')).toBeNull()
})

// ---------------------------------------------------------------------------
// The arithmetic
// ---------------------------------------------------------------------------

it('pairs the readings of one device and counts open for how long', () => {
  const pairs = pairReadings([BATH_H, LIVING_T, BATH_T, { ...BATH_T, entity_id: 'sensor.bath_second', name: 'Second' }])
  expect(pairs.map((pair) => [pair.name, pair.temperature?.entity_id, pair.humidity?.entity_id])).toEqual([
    ['Bathroom sensor', BATH_T.entity_id, BATH_H.entity_id], ['Second', 'sensor.bath_second', undefined], ['Living room sensor', LIVING_T.entity_id, undefined]])
  expect(since(NOW - 30_000, NOW)).toBe('1 min')
  expect(since(NOW - 125 * MIN, NOW)).toBe('2 h 05')
  expect(since(NOW - 3 * 24 * 60 * MIN, NOW)).toBe('3 d')
  expect(since(null, NOW)).toBe('')
})
