/**
 * Scenes, scripts and switches on a home page in the browser: a tap sets a
 * scene off and says so, a script says while it runs and stops; a bar of a
 * room lights the scene set off last; a switch flips with what it draws,
 * asks first where it should, says "switching" meanwhile; a card of
 * switches adds up their power; the details, the picker with a bar for each
 * room, and the tools while arranging.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, vi } from 'vitest'

import { heightOf, latestScene, sceneSign, totalPower, widthOf, withNews, type ActionInfo, type ActionState, type HomeAnswer, type HomeElement } from '../../lib/home'
import { HomePage } from './HomePage'
import { watts } from './SwitchControl'

type Sent = { url: string; method: string; body: Record<string, unknown> | null }

const NOW = Date.now()
const MIN = 60_000

function scene(entity: string, name: string, area: string, last: number | null): ActionInfo {
  return { rid: `r-${entity}`, entity_id: `scene.${entity}`, name, area, device: '', kind: 'scene', unavailable: false, last }
}
function plug(entity: string, name: string, extra: Partial<ActionInfo> = {}): ActionInfo {
  return { rid: `r-${entity}`, entity_id: `switch.${entity}`, name, area: '', device: '', kind: 'switch', unavailable: false, on: true, since: NOW - 30 * MIN, power: null,
    power_entity: null, energy_entity: null, device_class: 'outlet', ...extra }
}
const ref = (one: ActionInfo) => ({ rid: one.rid, entity_id: one.entity_id, name: one.name })

const COZY = scene('cozy', 'Cozy', 'Living room', NOW - 10 * MIN)
const BRIGHT = scene('bright', 'Bright', 'Living room', NOW - 600 * MIN)
const CINEMA = scene('cinema', 'Cinema', 'Living room', null)
const COOKING = scene('cooking', 'Cooking', 'Kitchen', NOW - 90 * MIN)
const ROUTINE: ActionInfo = { rid: 'r-routine', entity_id: 'script.routine', name: 'Good night routine', area: '', device: '', kind: 'script', unavailable: false, running: true }
const COFFEE = plug('coffee', 'Coffee machine', { power: 1240, power_entity: 'sensor.coffee_power', energy_entity: 'sensor.coffee_energy' })
const TV = plug('tv', 'TV', { on: false, power: 0, power_entity: 'sensor.tv_power' })
const ROUTER = plug('router', 'Router', { power: 9, power_entity: 'sensor.router_power' })
const GUESTS: ActionInfo = { ...plug('guests', 'Guests here', { device_class: '' }), entity_id: 'input_boolean.guests', rid: 'r-guests' }
const DARK = plug('dark', 'Garden light', { unavailable: true, on: null })
const GONE = { rid: 'r-gone', entity_id: 'switch.thrown_away', name: 'Old plug' }

const STATES: Record<string, ActionState> = Object.fromEntries([COZY, BRIGHT, CINEMA, COOKING, ROUTINE, COFFEE, TV, ROUTER, GUESTS, DARK].map((one) => [one.entity_id, { ...one, missing: false } as ActionState]))
STATES[GONE.entity_id] = { missing: true }

const at = (id: string, y: number, rest: Record<string, unknown>) => ({ id, x: 16, y, ...rest }) as HomeElement

function page(elements: HomeElement[]): HomeAnswer {
  return { version: 1, problem: null, layout: { integration_id: 1, elements }, lights: {}, climates: {}, actions: STATES }
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

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } })

function show(answer: HomeAnswer, { editing = false, canEdit = true, canAct = true, hold = undefined as Promise<void> | undefined } = {}) {
  const sent: Sent[] = []
  let current = answer
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : null
    sent.push({ url, method, body })
    if (method === 'POST' && /\/home\/(scenes|switches)\//.test(url)) {
      if (hold) await hold
      const element = url.split('/').at(-1)!
      const placed = current.layout.elements.find((one) => one.id === element)!
      const targets = placed.type === 'scene' || placed.type === 'switch' ? [placed.entity_id] : body.member ? [body.member as string]
        : placed.type === 'switches' ? placed.sensors.map((one) => one.entity_id) : []
      const actions = Object.fromEntries(targets.map((entity) => {
        const before = current.actions?.[entity] as ActionInfo
        const now = entity.startsWith('scene.') ? { last: Date.now() } : entity.startsWith('script.') ? { running: !body.stop }
          : { on: body.on, power: body.on ? before.power : before.power_entity ? 0 : null }
        return [entity, { ...before, ...now, missing: false }]
      }))
      return json({ ok: true, actions, refused: [] })
    }
    if (method === 'PUT') {
      current = { ...current, layout: { ...current.layout, elements: body.elements }, version: current.version + 1 }
      return json({ layout: current.layout, version: current.version })
    }
    if (url.includes('/energy')) return json({ today: 1.234, problem: null })
    if (url.includes('/home/scenes')) return json({ scenes: [BRIGHT, COZY, CINEMA, COOKING, ROUTINE], problem: null })
    if (url.includes('/home/switches')) return json({ switches: [COFFEE, TV, ROUTER, GUESTS, DARK], problem: null })
    return json(current)
  }))
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <HomePage pageId={9} editing={editing} canEdit={canEdit} canAct={canAct} onAddPage={() => undefined} onSettings={() => undefined} onDone={() => undefined} />
    </QueryClientProvider>,
  )
  return sent
}

const spot = (id: string) =>
  waitFor(() => {
    const found = document.querySelector(`[data-element="${id}"]`) as HTMLElement | null
    if (!found || !found.querySelector('[data-main], [data-member], [role=switch]')) throw new Error(`${id} is not drawn yet`)
    return found
  })
const posts = (sent: Sent[]) => sent.filter((one) => one.method === 'POST').map((one) => [one.url.replace(/^.*\/home\//, ''), one.body])
const puts = (sent: Sent[]) => sent.filter((one) => one.method === 'PUT')
const lastElements = (sent: Sent[]) => puts(sent).at(-1)!.body!.elements as Record<string, unknown>[]

// ---------------------------------------------------------------------------
// Scenes and scripts
// ---------------------------------------------------------------------------

it('sets a scene off at a tap and says so a moment, and stops a script that runs', async () => {
  const sent = show(page([at('a', 16, { type: 'scene', ...ref(COZY), style: 'pill' }), at('e', 64, { type: 'scene', ...ref(ROUTINE), style: 'pill' })]))
  const cozy = await spot('a')
  expect(cozy.querySelector('[data-state]')).toHaveTextContent('Living room')
  fireEvent.click(cozy.querySelector('[data-main]')!)
  expect(cozy.querySelector('[data-state]')).toHaveTextContent('set off')
  const routine = await spot('e')
  expect(routine.querySelector('[data-state]')).toHaveTextContent('running')
  fireEvent.click(routine.querySelector('[data-main]')!)
  fireEvent.click(within(routine).getByRole('button', { name: 'Stop Good night routine' }))
  await waitFor(() => expect(posts(sent)).toEqual([['scenes/a', {}], ['scenes/e', { stop: true }]]), { timeout: 1500 })
  await waitFor(() => expect(routine.querySelector('[data-state]')).not.toHaveTextContent('running'))
})

it('tells in the details when a scene was set off last', async () => {
  show(page([at('a', 16, { type: 'scene', ...ref(CINEMA), style: 'tile', colour: 'ocean' })]))
  const tile = await spot('a')
  expect((tile.querySelector('[data-main]') as HTMLElement).style.background).toContain('linear-gradient')
  fireEvent.contextMenu(tile.querySelector('[data-main]')!)
  expect(await screen.findByRole('dialog')).toHaveTextContent('Not set off yet')
})

it('lights the scene of a room set off last, and sets off the one tapped', async () => {
  const sent = show(page([at('c', 16, { type: 'scenes', style: 'bar', title: '', sensors: [ref(BRIGHT), ref(COZY), ref(CINEMA)] }),
    at('d', 120, { type: 'scenes', style: 'grid', title: 'Evening', sensors: [ref(COOKING), ref(CINEMA)] })]))
  const bar = await spot('c')
  expect(bar).toHaveTextContent('Living room')
  expect(bar.querySelector('[data-member="scene.cozy"]')).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(bar.querySelector('[data-member="scene.cinema"]')!)
  await waitFor(() => expect(bar.querySelector('[data-member="scene.cinema"]')).toHaveAttribute('aria-pressed', 'true'))
  expect(bar.querySelector('[data-member="scene.cozy"]')).toHaveAttribute('aria-pressed', 'false')
  expect(posts(sent)).toEqual([['scenes/c', { member: 'scene.cinema' }]])
  expect(await spot('d')).toHaveTextContent('Evening')
})

// ---------------------------------------------------------------------------
// Switches
// ---------------------------------------------------------------------------

it('says whether a switch is on and what it draws, offline or gone, and flips it at a tap', async () => {
  const sent = show(page([at('f', 16, { type: 'switch', ...ref(COFFEE), style: 'pill' }), at('t', 64, { type: 'switch', ...ref(TV), style: 'outlet' }),
    at('d', 240, { type: 'switch', ...ref(DARK), style: 'chip' }), at('x', 290, { type: 'switch', ...GONE, style: 'pill' })]))
  const coffee = await spot('f')
  expect(coffee.querySelector('[data-state]')).toHaveTextContent('on · 1.2 kW')
  expect((await spot('t')).querySelector('[data-state]')).toHaveTextContent('off')
  expect((await spot('d')).querySelector('[data-state]')).toHaveTextContent('offline')
  expect((await spot('x')).querySelector('[data-state]')).toHaveTextContent('gone')
  fireEvent.click((await spot('t')).querySelector('[data-main]')!)
  await waitFor(() => expect((document.querySelector('[data-element="t"] [data-state]') as HTMLElement).textContent).toMatch(/^on/))
  expect(document.querySelector('[data-element="t"] [data-lit]')).not.toBeNull()
  fireEvent.click(coffee.querySelector('[data-main]')!)
  await waitFor(() => expect(posts(sent)).toEqual([['switches/t', { on: true }], ['switches/f', { on: false }]]))
  fireEvent.click((await spot('d')).querySelector('[data-main]')!)
  expect(posts(sent)).toHaveLength(2)
})

it('says "switching" until the house answers', async () => {
  let release = () => undefined as void
  const hold = new Promise<void>((resolve) => { release = resolve })
  show(page([at('f', 16, { type: 'switch', ...ref(TV), style: 'pill' })]), { hold })
  const tv = await spot('f')
  fireEvent.click(tv.querySelector('[data-main]')!)
  expect(tv.querySelector('[data-state]')).toHaveTextContent('switching …')
  await act(async () => release())
  await waitFor(() => expect(tv.querySelector('[data-state]')).toHaveTextContent('on'))
})

it('asks before a switch goes off where the element says so, and not before it goes on', async () => {
  const sent = show(page([at('r', 16, { type: 'switch', ...ref(ROUTER), style: 'toggle', confirm: true })]))
  const router = await spot('r')
  fireEvent.click(within(router).getByRole('switch', { name: 'Router' }))
  const asking = await screen.findByRole('dialog')
  expect(asking).toHaveTextContent('Switch off Router?')
  fireEvent.click(within(asking).getByRole('button', { name: 'Cancel' }))
  expect(posts(sent)).toEqual([])
  fireEvent.click(within(router).getByRole('switch', { name: 'Router' }))
  fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Switch off' }))
  await waitFor(() => expect(posts(sent)).toEqual([['switches/r', { on: false }]]))
  await waitFor(() => expect(within(router).getByRole('switch', { name: 'Router' })).toHaveAttribute('aria-checked', 'false'))
  fireEvent.click(within(router).getByRole('switch', { name: 'Router' }))
  await waitFor(() => expect(posts(sent)).toEqual([['switches/r', { on: false }], ['switches/r', { on: true }]]))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

it('shows in the details what a switch draws, used today and since when it is on', async () => {
  const sent = show(page([at('f', 16, { type: 'switch', ...ref(COFFEE), style: 'tile' }), at('r', 200, { type: 'switch', ...ref(ROUTER), style: 'pill' })]))
  const coffee = await spot('f')
  expect(coffee).toHaveTextContent('1.2 kW')
  fireEvent.contextMenu(coffee.querySelector('[data-main]')!)
  const details = await screen.findByRole('dialog')
  await waitFor(() => expect(details.querySelector('[data-energy]')).toHaveTextContent('1.23 kWh'))
  expect(details.querySelector('[data-power]')).toHaveTextContent('1.2 kW')
  expect(details).toHaveTextContent('on since')
  fireEvent.keyDown(details, { key: 'Escape' })
  fireEvent.contextMenu((await spot('r')).querySelector('[data-main]')!)
  const router = await screen.findByRole('dialog')
  expect(router.querySelector('[data-energy]')).toBeNull()
  expect(sent.filter((one) => one.url.includes('/energy'))).toHaveLength(1)
})

it('switches a card together, adds up what it draws, and one of it on its own', async () => {
  const sent = show(page([at('k', 16, { type: 'switches', title: 'Office', sensors: [ref(COFFEE), ref(TV), ref(ROUTER), ref(DARK), GONE] })]))
  const card = await spot('k')
  expect(card.querySelector('[data-total]')).toHaveTextContent('together 1.2 kW')
  expect(card.querySelector('[data-member="switch.thrown_away"]')).toHaveTextContent('gone')
  fireEvent.click(within(card).getByRole('button', { name: 'All off' }))
  await waitFor(() => expect(posts(sent)).toEqual([['switches/k', { on: false }]]))
  await waitFor(() => expect(card.querySelector('[data-total]')).toHaveTextContent('together 0 W'))
  fireEvent.click(within(card).getByRole('switch', { name: 'TV' }))
  await waitFor(() => expect(posts(sent)[1]).toEqual(['switches/k', { on: true, member: 'switch.tv' }]))
})

it('gives who may only look nothing to switch or set off', async () => {
  const sent = show(page([at('f', 16, { type: 'switch', ...ref(COFFEE), style: 'pill' }), at('a', 64, { type: 'scene', ...ref(COZY), style: 'pill' }),
    at('k', 120, { type: 'switches', title: '', sensors: [ref(TV)] }), at('i', 300, { type: 'switch', ...ref(GUESTS), style: 'toggle' })]), { canAct: false, canEdit: false })
  expect(within(await spot('i')).getByRole('switch', { name: 'Guests here' })).toBeDisabled()
  fireEvent.click((await spot('f')).querySelector('[data-main]')!)
  fireEvent.click((await spot('a')).querySelector('[data-main]')!)
  const card = await spot('k')
  expect(within(card).queryByRole('button', { name: 'All on' })).not.toBeInTheDocument()
  expect(within(card).getByRole('switch', { name: 'TV' })).toBeDisabled()
  expect(posts(sent)).toEqual([])
})

// ---------------------------------------------------------------------------
// Picking and arranging
// ---------------------------------------------------------------------------

it('adds a bar for each room the chosen scenes are in', async () => {
  const sent = show(page([]), { editing: true })
  fireEvent.click((await screen.findAllByRole('button', { name: 'Scene' }))[0])
  const dialog = await screen.findByRole('dialog')
  await within(dialog).findByText('Cooking')
  fireEvent.change(within(dialog).getByRole('combobox'), { target: { value: 'bar' } })
  for (const name of ['Bright', 'Cooking', 'Cinema']) fireEvent.click(within(dialog).getByRole('checkbox', { name }))
  fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }))
  await waitFor(() => expect(puts(sent)).toHaveLength(1))
  expect(lastElements(sent).map((one) => [one.type, one.style, (one.sensors as { entity_id: string }[]).map((sensor) => sensor.entity_id)])).toEqual([
    ['scenes', 'bar', ['scene.bright', 'scene.cinema']], ['scenes', 'bar', ['scene.cooking']]])
})

it('adds switches that ask first, and turns asking on and off while arranging', async () => {
  const sent = show(page([]), { editing: true })
  fireEvent.click((await screen.findAllByRole('button', { name: 'Switch' }))[0])
  const dialog = await screen.findByRole('dialog')
  await within(dialog).findByText('Router')
  fireEvent.change(within(dialog).getByRole('combobox'), { target: { value: 'toggle' } })
  fireEvent.click(within(dialog).getByRole('checkbox', { name: /Ask before switching off/ }))
  fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Router' }))
  fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }))
  await waitFor(() => expect(puts(sent)).toHaveLength(1))
  expect(lastElements(sent)[0]).toMatchObject({ type: 'switch', style: 'toggle', entity_id: 'switch.router', confirm: true })
  const router = await spot(lastElements(sent)[0].id as string)
  const shield = within(router).getByRole('button', { name: 'Ask before switching off' })
  expect(shield).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(shield)
  await waitFor(() => expect(puts(sent)).toHaveLength(2))
  expect(lastElements(sent)[0]).toMatchObject({ confirm: false })
})

it('gives a scene tile another colour while arranging', async () => {
  const sent = show(page([at('b', 16, { type: 'scene', ...ref(COZY), style: 'tile' })]), { editing: true })
  const tile = await spot('b')
  fireEvent.click(within(tile).getByRole('button', { name: 'Colour of the tile' }))
  fireEvent.click(within(tile).getByRole('menuitemradio', { name: 'Forest' }))
  await waitFor(() => expect(puts(sent)).toHaveLength(1))
  expect(lastElements(sent)[0]).toMatchObject({ colour: 'forest' })
})

// ---------------------------------------------------------------------------
// The arithmetic
// ---------------------------------------------------------------------------

it('finds the scene set off last, adds up the power, writes watts and finds a sign by the name', () => {
  expect(latestScene([ref(BRIGHT), ref(COZY), ref(CINEMA)], STATES)).toBe('scene.cozy')
  expect(latestScene([ref(CINEMA)], STATES)).toBeNull()
  expect(latestScene([ref(COZY), ref(BRIGHT)], STATES)).toBe('scene.cozy')
  const tile = { id: 't', type: 'switch', x: 0, y: 0, ...ref(COFFEE), style: 'tile' } as HomeElement
  expect([widthOf(tile), heightOf(tile)]).toEqual([150, 118])
  const sceneTile = { id: 's', type: 'scene', x: 0, y: 0, ...ref(COZY), style: 'tile' } as HomeElement
  expect([widthOf(sceneTile), heightOf(sceneTile)]).toEqual([150, 118])
  expect(totalPower([ref(COFFEE), ref(TV), ref(ROUTER), ref(GUESTS)], STATES)).toBe(1249)
  expect(totalPower([ref(GUESTS)], STATES)).toBeNull()
  expect([watts(9), watts(1240), watts(12_500), watts(null)]).toEqual(['9 W', '1.2 kW', '13 kW', ''])
  expect([sceneSign('Kino'), sceneSign('Gute Nacht'), sceneSign('Cozy'), sceneSign('Whatever')]).toEqual(['film', 'moon', 'sofa', 'spark'])
  const after = withNews(page([]), { page_id: 9, actions: { [COFFEE.entity_id]: { missing: false, power: 17 } } })
  expect(after.actions![COFFEE.entity_id]).toMatchObject({ power: 17, on: true, name: 'Coffee machine' })
})
