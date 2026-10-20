/**
 * Thermostats on a home page in the browser: the room read by its sensor or,
 * when that one is gone, by the thermostat with a mark; taps on plus and minus
 * gathered into one call a second after the last; modes and presets in the
 * details; nothing to press for who may only look; the sensor chosen while
 * arranging; thermostats added like lamps.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { vi } from 'vitest'

import { CLIMATE_STYLES, type ClimateOffer, type ClimateView, type HomeAnswer } from '../../lib/home'
import { HomePage } from './HomePage'

type Sent = { url: string; method: string; body: Record<string, unknown> | null }

function thermostat(rid: string, entity_id: string, name: string, extra: Partial<ClimateView> = {}): ClimateView {
  return {
    rid, entity_id, name, area: name, device: '', unavailable: false, on: true, mode: 'heat', modes: ['off', 'heat', 'auto'], action: 'heating',
    current: 20.5, target: 21.5, target_low: null, target_high: null, settable: true, min: 7, max: 30, step: 0.5,
    preset: 'comfort', presets: ['comfort', 'eco', 'away'], unit: '°C', reading: 20.5, sensor: null, ...extra,
  }
}

const LIVING = thermostat('r-heat-living', 'climate.living_room', 'Living room', { reading: 21.3, sensor: { name: 'Living room temperature', state: 'ok' } })
const BED = thermostat('r-heat-bed', 'climate.bedroom', 'Bedroom', { on: false, mode: 'off', modes: ['off', 'heat'], action: 'off', current: 18.2, reading: 18.2, target: 17, presets: [], preset: null,
  sensor: { name: 'Old sensor', state: 'missing' } })

const ANSWER: HomeAnswer = {
  version: 2,
  problem: null,
  layout: {
    integration_id: 1,
    elements: [
      { id: 'living-h', type: 'heading', x: 16, y: 16, text: 'Living room' },
      { id: 'garden-h', type: 'heading', x: 400, y: 16, text: 'Upstairs' },
      { id: 'living', type: 'climate', x: 16, y: 56, rid: 'r-heat-living', entity_id: 'climate.living_room', name: 'Living room', style: 'pill',
        sensor: { rid: 'r-temp-living', entity_id: 'sensor.living_room_temperature', name: 'Living room temperature' } },
      { id: 'bed', type: 'climate', x: 400, y: 56, rid: 'r-heat-bed', entity_id: 'climate.bedroom', name: 'Bedroom', style: 'pill',
        sensor: { rid: 'r-gone', entity_id: 'sensor.thrown_away', name: 'Old sensor' } },
      { id: 'bath', type: 'climate', x: 16, y: 112, rid: 'r-heat-bath', entity_id: 'climate.bathroom', name: 'Bathroom', style: 'pill', sensor: null },
    ],
  },
  lights: {},
  climates: {
    living: { ...LIVING, missing: false },
    bed: { ...BED, missing: false },
    bath: { missing: true },
  },
}

const OFFER: ClimateOffer = {
  problem: null,
  climates: [LIVING, BED, thermostat('r-heat-kids', 'climate.kids_room', 'Kids room'), thermostat('r-heat-hall', 'climate.hall', 'Hall')],
  sensors: [
    { rid: 'r-temp-bed', entity_id: 'sensor.bedroom_temperature', name: 'Bedroom temperature', area: 'Bedroom', device: '', current: 18.9, unit: '°C', unavailable: false },
    { rid: 'r-temp-living', entity_id: 'sensor.living_room_temperature', name: 'Living room temperature', area: 'Living room', device: '', current: 21.3, unit: '°C', unavailable: false },
  ],
}

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } })

/** Answers a thermostat being set the way the server does, unless a test answers itself. */
type Setter = (element: string, body: Record<string, unknown>) => Promise<Response> | Response

function show({ canAct = true, canEdit = true, editing = false, setter = undefined as Setter | undefined, answer = ANSWER } = {}) {
  const sent: Sent[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : null
    sent.push({ url, method, body })
    if (method === 'POST' && url.includes('/home/climates/')) {
      const element = url.split('/home/climates/')[1]
      if (setter) return setter(element, body)
      const before = answer.climates?.[element]
      const view = { ...(before && !before.missing ? before : {}) } as ClimateView
      if (typeof body.target === 'number') view.target = body.target
      if (typeof body.mode === 'string') Object.assign(view, { mode: body.mode, on: body.mode !== 'off' })
      if (typeof body.preset === 'string') view.preset = body.preset
      return json({ ok: true, confirmed: true, climate: { ...view, missing: false } })
    }
    if (method === 'PUT') return json({ layout: { ...answer.layout, elements: body.elements }, version: answer.version + 1 })
    if (url.includes('/home/climates')) return json(OFFER)
    if (url.includes('/home/lights')) return json({ lights: [], problem: null })
    return json(answer)
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <HomePage pageId={9} editing={editing} canEdit={canEdit} canAct={canAct} onAddPage={() => undefined} onSettings={() => undefined} onDone={() => undefined} />
    </QueryClientProvider>,
  )
  return sent
}

const posts = (sent: Sent[]) => sent.filter((one) => one.method === 'POST')
const puts = (sent: Sent[]) => sent.filter((one) => one.method === 'PUT')
const pill = (entity: string) => document.querySelector(`[data-climate="${entity}"]`) as HTMLElement
/** Waits until the page has drawn the thermostat, then hands it over. */
const findPill = (entity: string) =>
  waitFor(() => {
    const found = pill(entity)
    if (!found) throw new Error(`${entity} is not drawn yet`)
    return found
  })
const wait = (ms: number) => act(async () => new Promise((resolve) => window.setTimeout(resolve, ms)))

it('reads each room by its sensor, and marks the one read by its thermostat because the sensor went', async () => {
  show()
  await screen.findByText('Living room', { selector: '[data-climate] *' })
  const living = pill('climate.living_room')
  expect(within(living).getByText('21.3°', { exact: false })).toHaveAttribute('data-reading')
  expect(living.querySelector('[data-target]')).toHaveTextContent('21.5°')
  const bed = pill('climate.bedroom')
  expect(bed.querySelector('[data-reading]')).toHaveTextContent('18.2° *')
  expect(bed.title).toContain('Old sensor is not answering')
  expect(bed.querySelector('[data-target]')).toHaveTextContent('off')
  expect(within(bed).queryByRole('button', { name: /Warmer/ })).not.toBeInTheDocument()
  expect(pill('climate.bathroom')).toHaveTextContent('gone')
})

it('gathers taps on plus and minus into one call a second after the last, saying it is setting', async () => {
  const sent = show()
  const living = await findPill('climate.living_room')
  const warmer = within(living).getByRole('button', { name: 'Warmer: Living room' })
  fireEvent.click(warmer)
  fireEvent.click(warmer)
  fireEvent.click(warmer)
  fireEvent.click(within(living).getByRole('button', { name: 'Colder: Living room' }))
  const target = living.querySelector('[data-target]') as HTMLElement
  expect(target).toHaveTextContent('22.5°')
  expect(target).toHaveAttribute('title', 'setting…')
  await wait(500)
  expect(posts(sent)).toEqual([])
  await waitFor(() => expect(posts(sent)).toHaveLength(1), { timeout: 2000 })
  expect(posts(sent)[0]).toMatchObject({ url: '/api/v1/pages/9/home/climates/living', body: { target: 22.5 } })
  await waitFor(() => expect(target).not.toHaveAttribute('title'))
  expect(target).toHaveTextContent('22.5°')
})

it('stops at the thermostat\'s bounds', async () => {
  show({ answer: { ...ANSWER, climates: { ...ANSWER.climates, living: { ...LIVING, target: 29.5, missing: false } } } })
  const living = await findPill('climate.living_room')
  const warmer = within(living).getByRole('button', { name: 'Warmer: Living room' })
  fireEvent.click(warmer)
  fireEvent.click(warmer)
  expect(living.querySelector('[data-target]')).toHaveTextContent('30°')
  expect(warmer).toBeDisabled()
})

it('opens the details at a tap, and sets the mode and the preset from there', async () => {
  const sent = show()
  const bed = await findPill('climate.bedroom')
  fireEvent.click(within(bed).getByRole('button', { name: /^Bedroom/ }))
  const panel = await screen.findByRole('dialog')
  expect(panel).toHaveTextContent('Old sensor is not answering')
  expect(within(panel).queryByRole('radio', { name: 'Comfort' })).not.toBeInTheDocument()
  // No presets, and no heading for them either.
  expect(panel).not.toHaveTextContent('Preset')
  fireEvent.click(within(panel).getByRole('radio', { name: 'Heat' }))
  await waitFor(() => expect(posts(sent).map((one) => one.body)).toEqual([{ mode: 'heat' }]))
  fireEvent.keyDown(window, { key: 'Escape' })
  fireEvent.click(within(pill('climate.living_room')).getByRole('button', { name: /^Living room/ }))
  const living = await screen.findByRole('dialog')
  expect(within(living).getByText('Heating')).toHaveAttribute('data-action')
  expect(within(living).getByRole('radio', { name: 'Comfort' })).toHaveAttribute('aria-checked', 'true')
  fireEvent.click(within(living).getByRole('radio', { name: 'Eco' }))
  await waitFor(() => expect(posts(sent).map((one) => one.body)).toEqual([{ mode: 'heat' }, { preset: 'eco' }]))
  await waitFor(() => expect(within(living).getByRole('radio', { name: 'Eco' })).toHaveAttribute('aria-checked', 'true'))
})

it('says why a thermostat was not set and leaves it as it was', async () => {
  show({ setter: () => json({ detail: { code: 'climate_unavailable', message: 'Home Assistant cannot reach Living room right now.' } }, 409) })
  const living = await findPill('climate.living_room')
  fireEvent.click(within(living).getByRole('button', { name: 'Warmer: Living room' }))
  expect(await screen.findByText('Home Assistant cannot reach Living room right now.', {}, { timeout: 2500 })).toBeInTheDocument()
  expect(living.querySelector('[data-target]')).toHaveTextContent('21.5°')
})

it('gives who may only look no plus, no minus and no mode to press', async () => {
  const sent = show({ canAct: false, canEdit: false })
  const living = await findPill('climate.living_room')
  expect(within(living).queryByRole('button', { name: /Warmer|Colder/ })).not.toBeInTheDocument()
  fireEvent.click(within(living).getByRole('button', { name: /^Living room/ }))
  const panel = await screen.findByRole('dialog')
  expect(within(panel).queryByRole('button', { name: /Warmer/ })).not.toBeInTheDocument()
  for (const mode of within(panel).getAllByRole('radio')) expect(mode).toBeDisabled()
  expect(posts(sent)).toEqual([])
})

it('reads a room by the sensor chosen while arranging, or by the thermostat again', async () => {
  const sent = show({ editing: true })
  const bed = await findPill('climate.bedroom')
  // The tools stand beside the pill, which clips what reaches past its edge.
  const tools = bed.parentElement as HTMLElement
  fireEvent.click(within(tools).getByRole('button', { name: 'Read the room by' }))
  fireEvent.click(await within(tools).findByRole('menuitemradio', { name: /Bedroom temperature/ }))
  await waitFor(() => expect(puts(sent)).toHaveLength(1))
  const chosen = (puts(sent)[0].body!.elements as Record<string, unknown>[]).find((element) => element.id === 'bed')
  expect(chosen).toMatchObject({ type: 'climate', sensor: { rid: 'r-temp-bed', entity_id: 'sensor.bedroom_temperature', name: 'Bedroom temperature' } })
  // The reading comes from the server, so the page is asked again.
  await waitFor(() => expect(sent.filter((one) => one.method === 'GET' && one.url.endsWith('/pages/9/home')).length).toBeGreaterThan(1))
  fireEvent.click(within(pill('climate.living_room').parentElement as HTMLElement).getByRole('button', { name: 'Read the room by' }))
  fireEvent.click(await within(pill('climate.living_room').parentElement as HTMLElement).findByRole('menuitemradio', { name: 'The thermostat itself' }))
  expect(within(pill('climate.living_room')).queryByRole('menu')).not.toBeInTheDocument()
  await waitFor(() => expect(puts(sent)).toHaveLength(2))
  expect((puts(sent)[1].body!.elements as Record<string, unknown>[]).find((element) => element.id === 'living')).toMatchObject({ sensor: null })
})

it('adds thermostats as lamps are added, below what stands, read by themselves', async () => {
  const sent = show({ editing: true })
  await findPill('climate.living_room')
  fireEvent.click(screen.getByRole('button', { name: 'Heating' }))
  expect(await screen.findByRole('checkbox', { name: 'Living room' })).toBeDisabled()
  fireEvent.click(screen.getByRole('checkbox', { name: 'Kids room' }))
  fireEvent.click(screen.getByRole('checkbox', { name: 'Hall' }))
  fireEvent.click(screen.getByRole('button', { name: 'Add (2)' }))
  await waitFor(() => expect(puts(sent)).toHaveLength(1))
  const added = (puts(sent)[0].body!.elements as Record<string, unknown>[]).filter((element) => !['living-h', 'garden-h', 'living', 'bed', 'bath'].includes(String(element.id)))
  // Side by side as far apart as a thermostat's pill is wide (320 and a gap), not a lamp's.
  expect(added).toEqual([
    expect.objectContaining({ type: 'climate', rid: 'r-heat-kids', entity_id: 'climate.kids_room', name: 'Kids room', style: 'pill', sensor: null, x: 16, y: 168 }),
    expect.objectContaining({ type: 'climate', rid: 'r-heat-hall', entity_id: 'climate.hall', name: 'Hall', sensor: null, x: 352, y: 168 }),
  ])
})

it('shows a phone each thermostat under its heading, the width of the screen', async () => {
  const wide = window.matchMedia
  window.matchMedia = ((query: string) => ({ matches: true, media: query, addEventListener: () => undefined, removeEventListener: () => undefined })) as unknown as typeof window.matchMedia
  try {
    show()
    await findPill('climate.bedroom')
    expect(within(document.querySelector('[data-phone-group="garden-h"]') as HTMLElement).getByText('Bedroom')).toBeInTheDocument()
    expect(pill('climate.bedroom').parentElement).toHaveClass('w-full')
    expect(pill('climate.bedroom')).toHaveClass('w-full')
  } finally {
    window.matchMedia = wide
  }
})

// -- swiping, turning and the ten styles -------------------------------------------

const main = (entity: string) => (pill(entity).matches('button') ? pill(entity) : (pill(entity).querySelector('[data-main]') as HTMLElement))

it('sets the target by a swipe sideways, shown as the finger moves and sent once it lets go', async () => {
  const sent = show()
  await findPill('climate.living_room')
  const surface = main('climate.living_room')
  fireEvent.pointerDown(surface, { pointerId: 1, button: 0, clientX: 100, clientY: 20 })
  fireEvent.pointerMove(surface, { pointerId: 1, clientX: 118, clientY: 21 })
  fireEvent.pointerMove(surface, { pointerId: 1, clientX: 137, clientY: 22 })
  // 37 px are three steps of 12: 21.5 and one and a half.
  expect(pill('climate.living_room').querySelector('[data-target]')).toHaveTextContent('23°')
  await wait(50)
  expect(posts(sent)).toEqual([])
  fireEvent.pointerUp(surface, { pointerId: 1, clientX: 137, clientY: 22 })
  fireEvent.click(surface)
  await waitFor(() => expect(posts(sent).map((one) => one.body)).toEqual([{ target: 23 }]))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

it('lets a swipe up and down scroll the page rather than set anything', async () => {
  const sent = show()
  await findPill('climate.living_room')
  const surface = main('climate.living_room')
  fireEvent.pointerDown(surface, { pointerId: 1, button: 0, clientX: 100, clientY: 20 })
  fireEvent.pointerMove(surface, { pointerId: 1, clientX: 104, clientY: 80 })
  fireEvent.pointerUp(surface, { pointerId: 1, clientX: 104, clientY: 80 })
  await wait(1200)
  expect(posts(sent)).toEqual([])
  expect(pill('climate.living_room').querySelector('[data-target]')).toHaveTextContent('21.5°')
})

const STYLED = (style: string): HomeAnswer => ({
  ...ANSWER,
  layout: { ...ANSWER.layout, elements: ANSWER.layout.elements.map((element) => (element.id === 'living' ? { ...element, style } : element)) as HomeAnswer['layout']['elements'] },
})

it('turns a dial, the place of the finger on the circle being the target', async () => {
  const measured = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 100, height: 124, right: 100, bottom: 124, x: 0, y: 0, toJSON: () => ({}) } as DOMRect)
  try {
    const sent = show({ answer: STYLED('dial') })
    await findPill('climate.living_room')
    const dial = main('climate.living_room')
    expect(dial).toHaveAttribute('data-style', 'dial')
    fireEvent.pointerDown(dial, { pointerId: 1, button: 0, clientX: 50, clientY: 10 })
    // Straight right of the middle is five sixths of the way round: 7 + 23 * 5/6 is 26.2, on the half degree 26.
    fireEvent.pointerMove(dial, { pointerId: 1, clientX: 100, clientY: 50 })
    expect(dial.querySelector('[data-target]')).toHaveTextContent('26°')
    // Past the end at the bottom right stays at the end.
    fireEvent.pointerMove(dial, { pointerId: 1, clientX: 80, clientY: 95 })
    expect(dial.querySelector('[data-target]')).toHaveTextContent('30°')
    fireEvent.pointerUp(dial, { pointerId: 1, clientX: 80, clientY: 95 })
    await waitFor(() => expect(posts(sent).map((one) => one.body)).toEqual([{ target: 30 }]))
  } finally {
    measured.mockRestore()
  }
})

it('moves the target by the arrow keys, gathered as taps are', async () => {
  const sent = show({ answer: STYLED('round') })
  await findPill('climate.living_room')
  const round = main('climate.living_room')
  fireEvent.keyDown(round, { key: 'ArrowUp' })
  fireEvent.keyDown(round, { key: 'ArrowRight' })
  fireEvent.keyDown(round, { key: 'ArrowDown' })
  await waitFor(() => expect(posts(sent).map((one) => one.body)).toEqual([{ target: 22 }]), { timeout: 2500 })
})

it('sets the target by the slider in the details, gathered as taps are', async () => {
  const sent = show()
  await findPill('climate.living_room')
  fireEvent.click(main('climate.living_room'))
  const panel = await screen.findByRole('dialog')
  const slider = within(panel).getByRole('slider', { name: 'Target' })
  expect(slider).toHaveAttribute('min', '7')
  expect(slider).toHaveAttribute('max', '30')
  expect(slider).toHaveAttribute('step', '0.5')
  fireEvent.change(slider, { target: { value: '19' } })
  fireEvent.change(slider, { target: { value: '19.5' } })
  expect(panel.querySelector('[data-target]')).toHaveTextContent('19.5°')
  await waitFor(() => expect(posts(sent).map((one) => one.body)).toEqual([{ target: 19.5 }]), { timeout: 2500 })
})

it('draws a thermostat in each of the ten styles, each with its room and its target', async () => {
  for (const style of CLIMATE_STYLES) {
    cleanup()
    show({ answer: STYLED(style) })
    const living = await findPill('climate.living_room')
    expect(living, style).toHaveAttribute('data-style', style)
    expect(living.querySelector('[data-reading]'), style).toHaveTextContent('21.3°')
    // The valve head says the mark of its scale: 21.5 degrees are about a 3.
    expect(living.querySelector('[data-target]'), style).toHaveTextContent(style === 'valve' ? '3' : '21.5°')
    expect(main('climate.living_room').getAttribute('aria-label'), style).toContain('21.5°')
    // Who may act can swipe every style; the tile and the pill have plus and minus besides.
    const steps = within(living.parentElement as HTMLElement).queryAllByRole('button', { name: /Warmer|Colder/ })
    expect(steps.length, style).toBe(style === 'pill' || style === 'tile' ? 2 : 0)
    for (const step of steps) expect(main('climate.living_room').contains(step), `${style}: a button in a button`).toBe(false)
  }
})

it('changes the style of a thermostat while arranging, and adds new ones in the style picked', async () => {
  const sent = show({ editing: true })
  await findPill('climate.bedroom')
  const tools = pill('climate.bedroom').parentElement as HTMLElement
  fireEvent.click(within(tools).getByRole('button', { name: 'Choose a style' }))
  fireEvent.click(within(tools).getByRole('menuitemradio', { name: 'Dial' }))
  await waitFor(() => expect(puts(sent)).toHaveLength(1))
  expect((puts(sent)[0].body!.elements as Record<string, unknown>[]).find((element) => element.id === 'bed')).toMatchObject({ style: 'dial' })

  fireEvent.click(screen.getByRole('button', { name: 'Heating' }))
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Kids room' }))
  fireEvent.click(screen.getByRole('checkbox', { name: 'Hall' }))
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'digits' } })
  fireEvent.click(screen.getByRole('button', { name: 'Add (2)' }))
  await waitFor(() => expect(puts(sent)).toHaveLength(2))
  const added = (puts(sent)[1].body!.elements as Record<string, unknown>[]).filter((element) => ['r-heat-kids', 'r-heat-hall'].includes(String(element.rid)))
  // Spaced for big digits (150 and a gap).
  expect(added.map((element) => [element.style, element.x])).toEqual([['digits', 16], ['digits', 184]])
})

it('says the degrees on a valve head while it is turned, and its mark otherwise', async () => {
  show({ answer: STYLED('valve') })
  const valve = main(await findPill('climate.living_room').then(() => 'climate.living_room'))
  expect(valve.querySelector('[data-target]')).toHaveTextContent('3')
  fireEvent.keyDown(valve, { key: 'ArrowUp' })
  fireEvent.keyDown(valve, { key: 'ArrowUp' })
  fireEvent.keyDown(valve, { key: 'ArrowUp' })
  expect(valve.querySelector('[data-target]')).toHaveTextContent('23°')
  await waitFor(() => expect(valve.querySelector('[data-target]')).toHaveTextContent(/^4$/), { timeout: 2500 })
})
