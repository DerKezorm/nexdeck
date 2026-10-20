/**
 * Shutters and blinds on a home page in the browser: what each style says
 * (where, moving, offline, gone), the arrows and the stop, dragging and the
 * arrow keys for a position, the slats of a blind, the details, a group and
 * positions of a card's own, and the picker. jsdom measures nothing: the
 * drawings are stood in for at 300 by 100 pixels.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterAll, afterEach, beforeAll, beforeEach, vi } from 'vitest'

import { positionAt, sceneHolds, withNews, type CoverInfo, type CoverState, type HomeAnswer, type HomeElement } from '../../lib/home'
import { HomePage } from './HomePage'

type Sent = { url: string; method: string; body: Record<string, unknown> | null }

function cover(entity: string, name: string, extra: Partial<CoverInfo> = {}): CoverInfo {
  return { rid: `r-${entity}`, entity_id: `cover.${entity}`, name, area: 'Living room', device: '', device_class: 'shutter', unavailable: false, position: 0, tilt: null,
    moving: null, can_open: true, can_close: true, settable: true, stoppable: true, tiltable: false, ...extra }
}
const ref = (one: CoverInfo) => ({ rid: one.rid, entity_id: one.entity_id, name: one.name })

const TERRACE = cover('terrace', 'Terrace')
const KITCHEN = cover('kitchen', 'Kitchen', { position: 45 })
const BEDROOM = cover('bedroom', 'Bedroom', { position: 70, moving: 'down' })
const OFFICE = cover('office', 'Office blind', { position: 100, tilt: 45, tiltable: true, device_class: 'blind' })
const GARAGE = cover('garage', 'Garage door', { settable: false, stoppable: false })
const GUEST = cover('guest', 'Guest room', { unavailable: true, position: null })
const GONE = { rid: 'r-gone', entity_id: 'cover.thrown_away', name: 'Old shutter' }

const STATES: Record<string, CoverState> = Object.fromEntries([TERRACE, KITCHEN, BEDROOM, OFFICE, GARAGE, GUEST].map((one) => [one.entity_id, { ...one, missing: false } as CoverState]))
STATES[GONE.entity_id] = { missing: true }

const at = (id: string, y: number, rest: Record<string, unknown>) => ({ id, x: 16, y, ...rest }) as HomeElement

function page(elements: HomeElement[]): HomeAnswer {
  return { version: 1, problem: null, layout: { integration_id: 1, elements }, lights: {}, climates: {}, covers: STATES }
}

const measured = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect')
beforeAll(() => {
  measured.mockImplementation(function (this: HTMLElement) {
    const size = this.hasAttribute('data-main') ? { width: 300, height: 100 } : { width: 0, height: 0 }
    return { left: 0, top: 0, ...size, right: size.width, bottom: size.height, x: 0, y: 0, toJSON: () => ({}) } as DOMRect
  })
})
afterAll(() => measured.mockRestore())

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

/** Answers a cover being moved the way the demo house does, unless a test answers itself. */
type Mover = (element: string, body: Record<string, unknown>) => Response
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } })

function show(answer: HomeAnswer, { editing = false, canEdit = true, canAct = true, mover = undefined as Mover | undefined } = {}) {
  const sent: Sent[] = []
  let current = answer
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : null
    sent.push({ url, method, body })
    if (method === 'POST' && url.includes('/home/covers/')) {
      const element = url.split('/home/covers/')[1]
      if (mover) return mover(element, body)
      const placed = current.layout.elements.find((one) => one.id === element)!
      const targets = placed.type === 'cover' ? [placed.entity_id] : body.member ? [body.member as string] : placed.type === 'covers' ? placed.sensors.map((one) => one.entity_id) : []
      const scene = typeof body.scene === 'number' && placed.type === 'covers' ? placed.scenes?.[body.scene]?.position : undefined
      const position = typeof body.position === 'number' ? body.position : body.action === 'open' ? 100 : body.action === 'close' ? 0 : scene
      const covers = Object.fromEntries(targets.map((entity) => [entity, { ...(current.covers?.[entity] as object), ...(position !== undefined ? { position, moving: null } : {}),
        ...(typeof body.tilt === 'number' ? { tilt: body.tilt } : {}), missing: false }]))
      return json({ ok: true, covers, refused: [] })
    }
    if (method === 'PUT') {
      current = { ...current, layout: { ...current.layout, elements: body.elements }, version: current.version + 1 }
      return json({ layout: current.layout, version: current.version })
    }
    if (url.includes('/home/covers')) return json({ covers: [TERRACE, KITCHEN, BEDROOM, OFFICE, GARAGE, GUEST], problem: null })
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
    if (!found || !found.querySelector('[data-state], [data-covers]') && !found.querySelector('[data-scene], [data-member]')) throw new Error(`${id} is not drawn yet`)
    return found
  })
const posts = (sent: Sent[]) => sent.filter((one) => one.method === 'POST').map((one) => [one.url.split('/home/covers/')[1], one.body])
const puts = (sent: Sent[]) => sent.filter((one) => one.method === 'PUT')
const lastElements = (sent: Sent[]) => puts(sent).at(-1)!.body!.elements as Record<string, unknown>[]
const wait = (ms: number) => act(async () => new Promise((resolve) => window.setTimeout(resolve, ms)))

// ---------------------------------------------------------------------------
// One cover
// ---------------------------------------------------------------------------

it('says where a cover stands, that it moves, that it is offline or gone', async () => {
  show(page([
    at('t', 16, { type: 'cover', ...ref(TERRACE), style: 'pill' }), at('k', 64, { type: 'cover', ...ref(KITCHEN), style: 'pill' }),
    at('b', 112, { type: 'cover', ...ref(BEDROOM), style: 'pill' }), at('o', 160, { type: 'cover', ...ref(OFFICE), style: 'tile' }),
    at('g', 300, { type: 'cover', ...ref(GUEST), style: 'chip' }), at('x', 360, { type: 'cover', ...GONE, style: 'pill' }),
  ]))
  const text = async (id: string) => (await spot(id)).querySelector('[data-state]')!.textContent
  expect(await text('t')).toBe('closed')
  expect(await text('k')).toBe('45 %')
  expect(await text('b')).toBe('closing · 70 %')
  expect(await text('o')).toBe('Open')
  expect(await text('g')).toBe('offline')
  expect(await text('x')).toBe('gone')
  // While it moves the arrows give way to the stop.
  const bedroom = await spot('b')
  expect(within(bedroom).getByRole('button', { name: 'Stop Bedroom' })).toBeInTheDocument()
  expect(within(bedroom).queryByRole('button', { name: 'Open Bedroom' })).not.toBeInTheDocument()
  expect(within(await spot('t')).getByRole('button', { name: 'Close Terrace' })).toBeDisabled()
})

it('opens a cover all the way with its arrow, shows it at once, and stops one on its way', async () => {
  const sent = show(page([at('k', 16, { type: 'cover', ...ref(KITCHEN), style: 'pill' }), at('b', 64, { type: 'cover', ...ref(BEDROOM), style: 'tile' })]))
  const kitchen = await spot('k')
  fireEvent.click(within(kitchen).getByRole('button', { name: 'Open Kitchen' }))
  expect(kitchen.querySelector('[data-state]')).toHaveTextContent('open')
  fireEvent.click(within(await spot('b')).getByRole('button', { name: 'Stop Bedroom' }))
  await waitFor(() => expect(posts(sent)).toEqual([['k', { action: 'open' }], ['b', { action: 'stop' }]]))
})

it('sets a position by dragging across a pill and up a window, and by the arrow keys', async () => {
  const sent = show(page([at('k', 16, { type: 'cover', ...ref(KITCHEN), style: 'pill' }), at('w', 64, { type: 'cover', ...ref(TERRACE), style: 'window' })]))
  const pill = (await spot('k')).querySelector('[data-main]') as HTMLElement
  fireEvent.pointerDown(pill, { pointerId: 1, button: 0, clientX: 30, clientY: 20 })
  fireEvent.pointerMove(pill, { pointerId: 1, clientX: 60, clientY: 20 })
  fireEvent.pointerMove(pill, { pointerId: 1, clientX: 180, clientY: 20 })
  // 180 of 300 is 60 %, shown while the finger moves and sent when it lets go.
  expect((await spot('k')).querySelector('[data-state]')).toHaveTextContent('60 %')
  expect(posts(sent)).toEqual([])
  fireEvent.pointerUp(pill, { pointerId: 1, clientX: 180, clientY: 20 })
  fireEvent.click(pill)
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  const window_ = (await spot('w')).querySelector('[data-main]') as HTMLElement
  fireEvent.pointerDown(window_, { pointerId: 2, button: 0, clientX: 50, clientY: 90 })
  fireEvent.pointerMove(window_, { pointerId: 2, clientX: 50, clientY: 60 })
  fireEvent.pointerUp(window_, { pointerId: 2, clientX: 50, clientY: 26 })
  await waitFor(() => expect(posts(sent)).toEqual([['k', { position: 60 }], ['w', { position: 75 }]]))
  fireEvent.keyDown(pill, { key: 'ArrowUp' })
  fireEvent.keyDown(pill, { key: 'ArrowUp' })
  await waitFor(() => expect(posts(sent)).toHaveLength(3), { timeout: 1500 })
  expect(posts(sent)[2]).toEqual(['k', { position: 80 }])
})

it('opens the details at a tap, with only what the cover can do', async () => {
  const sent = show(page([at('g', 16, { type: 'cover', ...ref(GARAGE), style: 'chip' }), at('o', 64, { type: 'cover', ...ref(OFFICE), style: 'pill' })]))
  fireEvent.click((await spot('g')).querySelector('[data-main]')!)
  let details = await screen.findByRole('dialog')
  expect(within(details).queryByRole('slider')).not.toBeInTheDocument()
  expect(within(details).queryByRole('button', { name: /Stop/ })).not.toBeInTheDocument()
  fireEvent.click(within(details).getByRole('button', { name: /Open/ }))
  await waitFor(() => expect(posts(sent)).toEqual([['g', { action: 'open' }]]))
  fireEvent.keyDown(details, { key: 'Escape' })
  fireEvent.contextMenu((await spot('o')).querySelector('[data-main]')!)
  details = await screen.findByRole('dialog')
  expect(details).toHaveTextContent('Office blind')
  fireEvent.change(within(details).getByRole('slider', { name: 'Slats' }), { target: { value: '20' } })
  fireEvent.change(within(details).getByRole('slider', { name: 'Position' }), { target: { value: '35' } })
  await waitFor(() => expect(posts(sent).slice(1)).toEqual([['o', { position: 35 }]]), { timeout: 1500 })
})

it('turns the slats of a blind under its pill, and says a shutter has none', async () => {
  const sent = show(page([at('o', 16, { type: 'cover', ...ref(OFFICE), style: 'tilt' }), at('t', 120, { type: 'cover', ...ref(TERRACE), style: 'tilt' })]))
  const office = await spot('o')
  const slats = within(office).getByRole('slider', { name: 'Slats of Office blind' })
  expect(slats).toHaveValue('45')
  fireEvent.change(slats, { target: { value: '80' } })
  await waitFor(() => expect(posts(sent)).toEqual([['o', { tilt: 80 }]]), { timeout: 1500 })
  expect((await spot('t')).querySelector('[data-no-slats]')).toHaveTextContent('No slats')
})

it('gives who may only look nothing to move, and the details to read', async () => {
  const sent = show(page([at('k', 16, { type: 'cover', ...ref(KITCHEN), style: 'pill' })]), { canAct: false, canEdit: false })
  const kitchen = await spot('k')
  expect(within(kitchen).queryByRole('button', { name: /Open|Close/ })).not.toBeInTheDocument()
  const pill = kitchen.querySelector('[data-main]') as HTMLElement
  fireEvent.pointerDown(pill, { pointerId: 1, button: 0, clientX: 30, clientY: 20 })
  fireEvent.pointerMove(pill, { pointerId: 1, clientX: 200, clientY: 20 })
  fireEvent.pointerUp(pill, { pointerId: 1, clientX: 200, clientY: 20 })
  expect(kitchen.querySelector('[data-state]')).toHaveTextContent('45 %')
  fireEvent.click(pill)
  const details = await screen.findByRole('dialog')
  expect(within(details).queryByRole('slider')).not.toBeInTheDocument()
  expect(within(details).queryByRole('button', { name: /Open/ })).not.toBeInTheDocument()
  expect(posts(sent)).toEqual([])
})

it('takes a press that hardly moved for a tap, and keeps the arrow keys inside the bounds', async () => {
  const sent = show(page([at('k', 16, { type: 'cover', ...ref(KITCHEN), style: 'pill' }), at('t', 64, { type: 'cover', ...ref(TERRACE), style: 'pill' })]))
  const pill = (await spot('k')).querySelector('[data-main]') as HTMLElement
  fireEvent.pointerDown(pill, { pointerId: 1, button: 0, clientX: 30, clientY: 20 })
  fireEvent.pointerMove(pill, { pointerId: 1, clientX: 33, clientY: 21 })
  fireEvent.pointerUp(pill, { pointerId: 1, clientX: 33, clientY: 21 })
  fireEvent.click(pill)
  expect(await screen.findByRole('dialog')).toHaveTextContent('Kitchen')
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
  const terrace = (await spot('t')).querySelector('[data-main]') as HTMLElement
  fireEvent.keyDown(terrace, { key: 'ArrowDown' })
  await waitFor(() => expect(posts(sent)).toEqual([['t', { position: 0 }]]), { timeout: 1500 })
})

// ---------------------------------------------------------------------------
// Several
// ---------------------------------------------------------------------------

it('moves a group together, and one of it from its details', async () => {
  const sent = show(page([at('f', 16, { type: 'covers', style: 'group', title: 'Downstairs', sensors: [ref(TERRACE), ref(KITCHEN), ref(GUEST), GONE] })]))
  const card = await spot('f')
  expect(card).toHaveTextContent('Downstairs')
  expect(card.querySelector('[data-member="cover.thrown_away"]')).toHaveTextContent('gone')
  expect(card.querySelector('[data-member="cover.guest"]')).toHaveTextContent('offline')
  fireEvent.click(within(card).getByRole('button', { name: 'Close all' }))
  await waitFor(() => expect(posts(sent)).toEqual([['f', { action: 'close' }]]))
  fireEvent.click(card.querySelector('[data-member="cover.kitchen"]')!)
  const details = await screen.findByRole('dialog')
  expect(details).toHaveTextContent('Kitchen')
  fireEvent.click(within(details).getByRole('button', { name: /Open/ }))
  await waitFor(() => expect(posts(sent)[1]).toEqual(['f', { action: 'open', member: 'cover.kitchen' }]))
})

it('sends every cover of a card to a position of its own, and lights the one they stand at', async () => {
  const sent = show(page([at('g', 16, { type: 'covers', style: 'scenes', title: '', sensors: [ref(TERRACE), ref(GARAGE)],
    scenes: [{ name: 'Morning', position: 100 }, { name: 'Night', position: 0 }] })]))
  const card = await spot('g')
  expect(card).toHaveTextContent('All covers')
  expect(card.querySelector('[data-scene="1"]')).toHaveAttribute('aria-pressed', 'true')
  expect(card.querySelector('[data-scene="0"]')).toHaveAttribute('aria-pressed', 'false')
  fireEvent.click(card.querySelector('[data-scene="0"]')!)
  await waitFor(() => expect(card.querySelector('[data-scene="0"]')).toHaveAttribute('aria-pressed', 'true'))
  expect(posts(sent)).toEqual([['g', { scene: 0 }]])
})

it('says which cover of a card could not go, and what kept the house from it', async () => {
  show(page([at('f', 16, { type: 'covers', style: 'group', title: '', sensors: [ref(TERRACE), ref(GUEST)] })]), {
    mover: () => json({ ok: true, covers: { [TERRACE.entity_id]: { ...TERRACE, position: 100, missing: false } },
      refused: [{ entity_id: GUEST.entity_id, code: 'cover_unavailable', message: 'Home Assistant cannot reach Guest room right now.' }] }),
  })
  fireEvent.click(within(await spot('f')).getByRole('button', { name: 'Open all' }))
  expect(await screen.findByText('Home Assistant cannot reach this cover right now.')).toBeInTheDocument()
})

// ---------------------------------------------------------------------------
// Picking and arranging
// ---------------------------------------------------------------------------

it('adds a card of positions with its own names, or one cover each', async () => {
  const sent = show(page([]), { editing: true })
  fireEvent.click((await screen.findAllByRole('button', { name: 'Cover' }))[0])
  let dialog = await screen.findByRole('dialog')
  await within(dialog).findByText('Kitchen')
  fireEvent.change(within(dialog).getByRole('combobox'), { target: { value: 'scenes' } })
  const names = within(dialog).getAllByRole('textbox', { name: 'Name of the position' })
  expect(names.map((one) => (one as HTMLInputElement).value)).toEqual(['Morning', 'Shade', 'Night'])
  fireEvent.change(names[1], { target: { value: 'Sun' } })
  fireEvent.change(within(dialog).getAllByRole('spinbutton', { name: 'Position in percent' })[1], { target: { value: '20' } })
  fireEvent.click(within(dialog).getAllByRole('button', { name: 'Remove position' })[2])
  fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Terrace' }))
  fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Kitchen' }))
  fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }))
  await waitFor(() => expect(puts(sent)).toHaveLength(1))
  expect(lastElements(sent)[0]).toMatchObject({ type: 'covers', style: 'scenes', scenes: [{ name: 'Morning', position: 100 }, { name: 'Sun', position: 20 }],
    sensors: [expect.objectContaining({ entity_id: TERRACE.entity_id }), expect.objectContaining({ entity_id: KITCHEN.entity_id })] })

  fireEvent.click(screen.getByRole('button', { name: 'Cover' }))
  dialog = await screen.findByRole('dialog')
  await within(dialog).findByText('Kitchen')
  fireEvent.change(within(dialog).getByRole('combobox'), { target: { value: 'window' } })
  expect(within(dialog).queryByRole('textbox', { name: 'Name of the position' })).not.toBeInTheDocument()
  fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Kitchen' }))
  fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Bedroom' }))
  fireEvent.click(within(dialog).getByRole('button', { name: 'Add 2' }))
  await waitFor(() => expect(puts(sent)).toHaveLength(2))
  expect(lastElements(sent).slice(1).map((one) => [one.type, one.style, one.entity_id])).toEqual([['cover', 'window', KITCHEN.entity_id], ['cover', 'window', BEDROOM.entity_id]])
})

it('turns a group into positions with the defaults of the page\'s language, and keeps a cover that is gone', async () => {
  const sent = show(page([at('f', 16, { type: 'covers', style: 'group', title: '', sensors: [ref(TERRACE), GONE] })]), { editing: true })
  const card = await spot('f')
  fireEvent.click(within(card).getByRole('button', { name: 'Choose a style' }))
  fireEvent.click(within(card).getByRole('menuitemradio', { name: 'Positions' }))
  await waitFor(() => expect(puts(sent)).toHaveLength(1))
  expect(lastElements(sent)[0]).toMatchObject({ style: 'scenes', scenes: [{ name: 'Morning', position: 100 }, { name: 'Shade', position: 30 }, { name: 'Night', position: 0 }] })
  fireEvent.click(within(await spot('f')).getByRole('button', { name: 'Choose sensors' }))
  const dialog = await screen.findByRole('dialog')
  await within(dialog).findByText('Kitchen')
  fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Kitchen' }))
  fireEvent.click(within(dialog).getByRole('button', { name: 'Apply' }))
  await waitFor(() => expect(puts(sent)).toHaveLength(2))
  expect((lastElements(sent)[0].sensors as { entity_id: string }[]).map((one) => one.entity_id)).toEqual([TERRACE.entity_id, KITCHEN.entity_id, GONE.entity_id])
  await wait(0)
})

// ---------------------------------------------------------------------------
// The arithmetic
// ---------------------------------------------------------------------------

it('steps a dragged position by five, keeps the name of a cover when the stream tells it moved, and lights a position all stand at', () => {
  expect([positionAt(-0.2), positionAt(0.43), positionAt(0.6), positionAt(1.4)]).toEqual([0, 45, 60, 100])
  const before = page([at('k', 16, { type: 'cover', ...ref(KITCHEN), style: 'pill' })])
  const after = withNews(before, { page_id: 9, covers: { [KITCHEN.entity_id]: { missing: false, position: 52, moving: 'up' } } })
  expect(after.covers![KITCHEN.entity_id]).toMatchObject({ position: 52, moving: 'up', name: 'Kitchen', settable: true })
  const night = { name: 'Night', position: 0 }
  expect(sceneHolds(night, [STATES[TERRACE.entity_id], STATES[GARAGE.entity_id], STATES[GUEST.entity_id]])).toBe(true)
  expect(sceneHolds(night, [STATES[TERRACE.entity_id], STATES[KITCHEN.entity_id]])).toBe(false)
  expect(sceneHolds(night, [STATES[GUEST.entity_id]])).toBe(false)
})
