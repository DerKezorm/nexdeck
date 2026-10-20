/**
 * Names of the page's own: the pencil beside a lamp, a thermostat, a door or
 * a reading while arranging, the name shown instead of Home Assistant's in
 * the drawing and the details, empty for Home Assistant's again, and a long
 * name running as a ticker in the drawings.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, vi } from 'vitest'

import { pageHints, type ClimateView, type HomeAnswer, type HomeElement, type LampInfo, type SensorState } from '../../lib/home'
import { HomePage } from './HomePage'

type Sent = { url: string; method: string; body: Record<string, unknown> | null }

const LAMP: LampInfo = { rid: 'r-floor', entity_id: 'light.floor_lamp', name: 'Floor lamp', area: 'Living room', device: '', group: false, on: true, unavailable: false,
  pct: 60, rgb: null, kelvin: null, dims: true, temperature: false, colour: false }
const HEAT = { rid: 'r-heat', entity_id: 'climate.living', name: 'Living room', area: 'Living room', device: '', unavailable: false, on: true, mode: 'heat',
  modes: ['off', 'heat'], action: 'heating', current: 20.5, target: 21.5, target_low: null, target_high: null, settable: true, min: 7, max: 30, step: 0.5,
  preset: null, presets: [], unit: '°C', reading: 20.5, sensor: null } satisfies ClimateView
const DOOR = { rid: 'r-door', entity_id: 'binary_sensor.stairs_door', name: 'Treppenhaus Eingangstür Erdgeschoss' }
const BATH = { rid: 'r-hum', entity_id: 'sensor.bath_humidity', name: 'Bathroom humidity' }
const SENSORS: Record<string, SensorState> = {
  [DOOR.entity_id]: { ...DOOR, missing: false, area: 'Living room', device: '', device_id: 'd', device_class: 'door', battery: null, open: true, since: Date.now() - 60_000, unavailable: false },
  [BATH.entity_id]: { ...BATH, missing: false, area: 'Bathroom', device: '', device_id: 'b', device_class: 'humidity', battery: null, current: 55, unit: '%', unavailable: false },
}

const ELEMENTS: HomeElement[] = [
  { id: 'lamp', type: 'light', x: 16, y: 16, rid: LAMP.rid, entity_id: LAMP.entity_id, name: LAMP.name, style: 'pill', label: 'Reading corner' },
  { id: 'heat', type: 'climate', x: 16, y: 80, rid: HEAT.rid, entity_id: HEAT.entity_id, name: HEAT.name, style: 'pill', sensor: null },
  { id: 'door', type: 'contact', x: 16, y: 160, ...DOOR, style: 'door' },
  { id: 'bath', type: 'reading', x: 200, y: 160, style: 'pill', name: '', temperature: null, humidity: BATH },
  { id: 'rows', type: 'readings', x: 16, y: 360, title: '', rows: [{ name: '', temperature: null, humidity: BATH }] },
]

function page(elements: HomeElement[] = ELEMENTS): HomeAnswer {
  return { version: 1, problem: null, layout: { integration_id: 1, elements }, lights: { lamp: { ...LAMP, missing: false } }, climates: { heat: { ...HEAT, missing: false } }, sensors: SENSORS }
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
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : null
    sent.push({ url: String(input), method, body })
    const json = (value: unknown) => new Response(JSON.stringify(value), { status: 200, headers: { 'content-type': 'application/json' } })
    if (method === 'PUT') {
      current = { ...current, layout: { ...current.layout, elements: body.elements }, version: current.version + 1 }
      return json({ layout: current.layout, version: current.version })
    }
    if (String(input).includes('/home/stats/')) return json({ period: '24h', start: 0, end: 1, now: 1, zone: 'UTC', series: [{ missing: true }], problem: null })
    return json(current)
  }))
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <HomePage pageId={9} editing={editing} canEdit={canEdit} canAct onAddPage={() => undefined} onSettings={() => undefined} onDone={() => undefined} />
    </QueryClientProvider>,
  )
  return sent
}

const spot = (id: string) =>
  waitFor(() => {
    const found = document.querySelector(`[data-element="${id}"]`) as HTMLElement | null
    if (!found) throw new Error(`${id} is not drawn yet`)
    return found
  })
const puts = (sent: Sent[]) => sent.filter((one) => one.method === 'PUT')
const saved = (sent: Sent[], id: string) => (puts(sent).at(-1)!.body!.elements as Record<string, unknown>[]).find((one) => one.id === id)!

/** Opens an element's pencil, types a name and saves it with Enter. */
function rename(element: HTMLElement, name: string) {
  fireEvent.click(within(element).getByRole('button', { name: 'A name of its own' }))
  const field = within(element).getByRole('textbox', { name: 'A name of its own' })
  fireEvent.change(field, { target: { value: name } })
  fireEvent.submit(field.closest('form')!)
}

it('shows the name of the page instead of Home Assistant\'s, in the drawing and in the details', async () => {
  show(page())
  const lamp = await spot('lamp')
  expect(lamp).toHaveTextContent('Reading corner')
  expect(lamp).not.toHaveTextContent('Floor lamp')
  fireEvent.contextMenu(lamp.querySelector('[data-lamp]')!)
  expect(await screen.findByRole('dialog')).toHaveTextContent('Reading corner')
})

it('gives a lamp, a thermostat, a door and a reading a name of their own with the pencil', async () => {
  const sent = show(page(), { editing: true })
  const heat = await spot('heat')
  rename(heat, '  Lounge  ')
  await waitFor(() => expect(puts(sent)).toHaveLength(1))
  expect(saved(sent, 'heat')).toMatchObject({ label: 'Lounge', name: 'Living room' })
  rename(await spot('door'), 'Stairs')
  await waitFor(() => expect(puts(sent)).toHaveLength(2))
  expect(saved(sent, 'door')).toMatchObject({ label: 'Stairs', name: DOOR.name })
  rename(await spot('bath'), 'Bath')
  await waitFor(() => expect(puts(sent)).toHaveLength(3))
  expect(saved(sent, 'bath')).toMatchObject({ name: 'Bath' })
  expect(await spot('door')).toHaveTextContent('Stairs')
})

it('offers Home Assistant\'s name in the field and takes it back with the button', async () => {
  const sent = show(page(), { editing: true })
  const lamp = await spot('lamp')
  fireEvent.click(within(lamp).getByRole('button', { name: 'A name of its own' }))
  expect(within(lamp).getByRole('textbox', { name: 'A name of its own' })).toHaveAttribute('placeholder', 'Floor lamp')
  expect(within(lamp).getByRole('textbox', { name: 'A name of its own' })).toHaveValue('Reading corner')
  fireEvent.click(within(lamp).getByRole('button', { name: "Home Assistant's name" }))
  await waitFor(() => expect(puts(sent)).toHaveLength(1))
  expect(saved(sent, 'lamp')).toMatchObject({ label: '' })
  expect(await spot('lamp')).toHaveTextContent('Floor lamp')
  // Saving the same name asks nothing, not even after the page's wait before it saves.
  rename(await spot('heat'), '')
  await new Promise((resolve) => window.setTimeout(resolve, 1500))
  expect(puts(sent)).toHaveLength(1)
})

it('names a row of the list of rooms while arranging, its room until then', async () => {
  const sent = show(page(), { editing: true })
  const rows = await spot('rows')
  const field = within(rows).getByRole('textbox', { name: 'Name of the row' })
  expect(field).toHaveAttribute('placeholder', 'Bathroom')
  fireEvent.change(field, { target: { value: 'Upstairs bath ' } })
  fireEvent.blur(field)
  await waitFor(() => expect(puts(sent)).toHaveLength(1))
  expect((saved(sent, 'rows').rows as { name: string }[])[0].name).toBe('Upstairs bath')
})

it('gives who only looks no pencil, and runs a long name in a drawing as a ticker', async () => {
  show(page(), { canEdit: false })
  const door = await spot('door')
  expect(within(door).queryByRole('button', { name: 'A name of its own' })).not.toBeInTheDocument()
  expect(door.querySelector('.lamp-marquee')).toHaveTextContent(DOOR.name)
  expect(door.querySelector('.truncate')).toBeNull()
})

it('names a window in a hint by the name the page gave it', () => {
  const elements: HomeElement[] = [{ id: 'door', type: 'contact', x: 0, y: 0, ...DOOR, style: 'pill', label: 'Stairs' }, ELEMENTS[1]]
  const hints = pageHints(elements, page(elements), ['heating'])
  expect(hints.map((hint) => hint.name)).toEqual(['Stairs'])
})

it('names a thermostat Home Assistant no longer has by the name the page gave it', async () => {
  const gone: HomeElement = { id: 'old', type: 'climate', x: 16, y: 16, rid: 'r-old', entity_id: 'climate.old', name: 'Old valve', style: 'pill', sensor: null, label: 'Attic' }
  show({ ...page([gone]), climates: { old: { missing: true } } })
  expect(await spot('old')).toHaveTextContent('Attic')
})

it('names every card with the pencil, the statistics card too, and falls back to its own name when emptied', async () => {
  const cover = { rid: 'r-c', entity_id: 'cover.kitchen', name: 'Kitchen' }
  const cards: HomeElement[] = [
    { id: 'stat', type: 'stat', x: 16, y: 16, style: 'line', sensors: [BATH], title: '' },
    { id: 'contacts', type: 'contacts', x: 400, y: 16, style: 'list', sensors: [DOOR], title: '' },
    { id: 'rooms', type: 'readings', x: 16, y: 300, title: '', rows: [{ name: '', temperature: null, humidity: BATH }] },
    { id: 'hints', type: 'hints', x: 400, y: 300, title: '', checks: ['humid'] },
    { id: 'covers', type: 'covers', x: 16, y: 600, style: 'group', sensors: [cover], title: 'Downstairs' },
    { id: 'scenes', type: 'scenes', x: 400, y: 600, style: 'grid', sensors: [{ rid: 'r-s', entity_id: 'scene.cozy', name: 'Cozy' }], title: '' },
    { id: 'switches', type: 'switches', x: 16, y: 900, sensors: [{ rid: 'r-w', entity_id: 'switch.tv', name: 'TV' }], title: '' },
  ]
  const sent = show(page(cards), { editing: true })
  let count = 0
  for (const card of cards) {
    rename(await spot(card.id), `Card ${card.id}`)
    count += 1
    await waitFor(() => expect(puts(sent)).toHaveLength(count))
    expect(saved(sent, card.id)).toMatchObject({ title: `Card ${card.id}` })
  }
  const covers = await spot('covers')
  fireEvent.click(within(covers).getByRole('button', { name: 'A name of its own' }))
  expect(within(covers).getByRole('textbox', { name: 'A name of its own' })).toHaveAttribute('placeholder', 'Covers')
  fireEvent.click(within(covers).getByRole('button', { name: "Home Assistant's name" }))
  await waitFor(() => expect(puts(sent)).toHaveLength(count + 1))
  expect(saved(sent, 'covers')).toMatchObject({ title: '' })
}, 20_000)
