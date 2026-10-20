/**
 * The home page in the browser: headings stand where they were put, an
 * editor adds, renames, moves and removes them, each change is saved with
 * the version it started from, someone who may only look changes nothing,
 * a connection that went is said, and a lamp switches at a tap, dims when
 * dragged and opens its details when held.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterAll, afterEach, beforeAll, vi } from 'vitest'

import { LAMP_STYLES, SETTLE_MS, type HomeAnswer, type LampInfo, type LightOffer } from '../../lib/home'
import { HomePage } from './HomePage'

const ANSWER: HomeAnswer = {
  version: 4,
  problem: null,
  layout: {
    integration_id: 1,
    elements: [
      { id: 'living', type: 'heading', x: 16, y: 16, text: 'Living room' },
      { id: 'garden', type: 'heading', x: 320, y: 16, text: 'Garden' },
    ],
  },
}

type Sent = { url: string; method: string; body: Record<string, unknown> | null }

function lamp(rid: string, entity_id: string, name: string, extra: Partial<LampInfo> = {}): LampInfo {
  return {
    rid, entity_id, name, area: 'Living room', device: name, group: false, on: false, unavailable: false, pct: null, rgb: null, kelvin: null,
    dims: true, temperature: true, colour: false, ...extra,
  }
}

const OFFER: LightOffer = {
  problem: null,
  lights: [
    lamp('r-ceiling', 'light.ceiling', 'Ceiling light', { on: true, pct: 80, kelvin: 3000 }),
    lamp('r-floor', 'light.floor_lamp', 'Floor lamp', { on: true, pct: 62, rgb: [255, 167, 87] }),
    lamp('r-path', 'light.garden_path', 'Garden path', { area: 'Garden', dims: false, temperature: false }),
    lamp('r-counter', 'light.kitchen_counter', 'Kitchen counter', { area: 'Kitchen' }),
  ],
}

/** What a switch is answered with; by default the lamp as asked, confirmed. */
type Switcher = (element: string, body: { on: boolean }) => Promise<Response> | Response

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } })

function serve(answer: HomeAnswer, sent: Sent[], offer: LightOffer = OFFER, switcher?: Switcher) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : null
    sent.push({ url, method, body })
    if (method === 'POST' && url.includes('/home/lights/')) {
      const element = url.split('/home/lights/')[1]
      if (switcher) return switcher(element, body)
      // As the server answers: the lamp as it stands after the wish.
      const before = answer.lights?.[element]
      const on = body.on ?? true
      const pct = on ? body.brightness_pct ?? (before && !before.missing ? before.pct : null) : null
      return json({ ok: true, confirmed: true, light: { ...(before && !before.missing ? before : {}), on, pct, missing: false } })
    }
    if (method === 'PUT') return json({ layout: { ...answer.layout, elements: body.elements }, version: answer.version + 1 })
    if (url.includes('/home/lights')) return json(offer)
    return json(answer)
  })
}

function show(answer: HomeAnswer, { canEdit = true, canAct = false, editing = false, offer = OFFER, switcher = undefined as Switcher | undefined } = {}) {
  const sent: Sent[] = []
  vi.stubGlobal('fetch', serve(answer, sent, offer, switcher))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <HomePage pageId={9} editing={editing} canEdit={canEdit} canAct={canAct} onAddPage={() => undefined} onSettings={() => undefined} onDone={() => undefined} />
    </QueryClientProvider>,
  )
  return sent
}

const puts = (sent: Sent[]) => sent.filter((one) => one.method === 'PUT')

// jsdom has no PointerEvent, and without one a pointer event loses its coordinates.
const hadPointerEvent = 'PointerEvent' in window
beforeAll(() => {
  if (!hadPointerEvent) {
    class PointerEventLike extends MouseEvent {
      pointerId: number
      constructor(type: string, init: PointerEventInit = {}) {
        super(type, init)
        this.pointerId = init.pointerId ?? 0
      }
    }
    vi.stubGlobal('PointerEvent', PointerEventLike)
  }
})
afterAll(() => {
  if (!hadPointerEvent) delete (window as { PointerEvent?: unknown }).PointerEvent
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  if (!hadPointerEvent) beforeAllAgain()
})
function beforeAllAgain() {
  class PointerEventLike extends MouseEvent {
    pointerId: number
    constructor(type: string, init: PointerEventInit = {}) {
      super(type, init)
      this.pointerId = init.pointerId ?? 0
    }
  }
  vi.stubGlobal('PointerEvent', PointerEventLike)
}

it('puts each heading where it was placed', async () => {
  show(ANSWER)
  const garden = await screen.findByText('Garden')
  const spot = garden.closest('[data-element]') as HTMLElement
  expect(spot.style.left).toBe('320px')
  expect(spot.style.top).toBe('16px')
  expect(screen.getByText('Living room')).toBeInTheDocument()
})

it('lets an editor add a heading, name it, and saves it with the version it started from', async () => {
  const sent = show(ANSWER, { editing: true })
  await screen.findByText('Garden')
  fireEvent.click(screen.getAllByRole('button', { name: 'Heading' })[0])
  const field = await screen.findByRole('textbox', { name: 'Name of the heading' })
  fireEvent.change(field, { target: { value: 'Upstairs' } })
  fireEvent.keyDown(field, { key: 'Enter' })
  expect(await screen.findByText('Upstairs')).toBeInTheDocument()
  await waitFor(() => expect(puts(sent).length).toBeGreaterThan(0))
  await waitFor(() => {
    const last = puts(sent).at(-1)!
    const texts = (last.body!.elements as { text: string }[]).map((element) => element.text)
    expect(texts).toContain('Upstairs')
  })
  const first = puts(sent)[0]
  expect(first.url).toContain('/pages/9/home')
  expect(first.body!.version).toBe(4)
  const added = (puts(sent).at(-1)!.body!.elements as { id: string; x: number; y: number }[]).at(-1)!
  expect(added).toMatchObject({ x: 16, y: 56 })
  expect(added.id).toMatch(/^[A-Za-z0-9_-]{1,32}$/)
})

it('moves a heading by the pointer and saves where it landed, on the step of the surface', async () => {
  const sent = show(ANSWER, { editing: true })
  const spot = (await screen.findByText('Living room')).closest('[data-element]') as HTMLElement
  fireEvent.pointerDown(spot, { pointerId: 1, button: 0, clientX: 100, clientY: 100 })
  fireEvent.pointerMove(spot, { pointerId: 1, clientX: 143, clientY: 162 })
  fireEvent.pointerUp(spot, { pointerId: 1, clientX: 143, clientY: 162 })
  await waitFor(() => expect(puts(sent).length).toBe(1))
  const moved = (puts(sent)[0].body!.elements as { id: string; x: number; y: number }[]).find((element) => element.id === 'living')!
  // 16 + 43 = 59 snaps to 56, 16 + 62 = 78 snaps to 80.
  expect(moved).toMatchObject({ x: 56, y: 80 })
})

it('removes a heading at once', async () => {
  const sent = show(ANSWER, { editing: true })
  await screen.findByText('Garden')
  fireEvent.click(screen.getAllByRole('button', { name: 'Remove' })[1])
  await waitFor(() => expect(puts(sent).length).toBe(1))
  expect((puts(sent)[0].body!.elements as { id: string }[]).map((element) => element.id)).toEqual(['living'])
  expect(screen.queryByText('Garden')).not.toBeInTheDocument()
})

it('saves one change after the other, each with the version the one before it got back', async () => {
  // A slow server and two changes a moment apart: the second has to wait for
  // the first, or both carry version 4 and the second is refused as stale.
  const sent: Sent[] = []
  let version = ANSWER.version
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : null
    sent.push({ url: String(input), method, body })
    const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } })
    if (method !== 'PUT') return json(ANSWER)
    await new Promise((resolve) => setTimeout(resolve, 80))
    if (body.version !== version) return json({ detail: { code: 'layout_moved_on', message: 'moved on' } }, 409)
    version += 1
    return json({ layout: { ...ANSWER.layout, elements: body.elements }, version })
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <HomePage pageId={9} editing canEdit canAct={false} onAddPage={() => undefined} onSettings={() => undefined} onDone={() => undefined} />
    </QueryClientProvider>,
  )
  await screen.findByText('Garden')
  fireEvent.click(screen.getAllByRole('button', { name: 'Remove' })[1])
  // The second change comes while the first save is still on its way.
  await waitFor(() => expect(puts(sent)).toHaveLength(1))
  fireEvent.click(screen.getAllByRole('button', { name: 'Remove' })[0])
  await waitFor(() => expect(puts(sent)).toHaveLength(2))
  await waitFor(() => expect(version).toBe(6))
  expect(puts(sent).map((one) => one.body!.version)).toEqual([4, 5])
  expect(puts(sent)[1].body!.elements).toEqual([])
  expect(screen.queryByText(/changed this page meanwhile/)).not.toBeInTheDocument()
})

it('changes nothing for someone who may only look', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  const sent = show(ANSWER, { editing: true, canEdit: false })
  await screen.findByText('Garden')
  expect(screen.queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Heading' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByText('Garden'))
  // Neither a press nor a drag does anything for them.
  const spot = screen.getByText('Garden').closest('[data-element]') as HTMLElement
  fireEvent.pointerDown(spot, { pointerId: 1, button: 0, clientX: 100, clientY: 100 })
  fireEvent.pointerUp(spot, { pointerId: 1, clientX: 100, clientY: 100 })
  fireEvent.pointerDown(spot, { pointerId: 2, button: 0, clientX: 100, clientY: 100 })
  fireEvent.pointerMove(spot, { pointerId: 2, clientX: 180, clientY: 160 })
  fireEvent.pointerUp(spot, { pointerId: 2, clientX: 180, clientY: 160 })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2000)
  })
  expect(puts(sent)).toHaveLength(0)
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  expect(spot.style.left).toBe('320px')
})

it('says so when the connection of the page is gone, and still shows what stands on it', async () => {
  show({ ...ANSWER, problem: { code: 'no_integration', message: 'The Home Assistant connection of this page is gone.', hint: 'Delete the page and add it again with another connection.' } })
  expect(await screen.findByText('The Home Assistant connection of this page is gone.')).toBeInTheDocument()
  expect(screen.getByText('Garden')).toBeInTheDocument()
})

it('invites an empty page to be filled, and only an editor to fill it', async () => {
  show({ ...ANSWER, layout: { integration_id: 1, elements: [] } }, { editing: true })
  expect(await screen.findByText('Nothing on this page yet')).toBeInTheDocument()
  expect(screen.getAllByRole('button', { name: 'Heading' }).length).toBeGreaterThan(0)
  expect(screen.getAllByRole('button', { name: 'Light' }).length).toBeGreaterThan(0)
})

// -- lamps --------------------------------------------------------------------

const WITH_LAMPS: HomeAnswer = {
  ...ANSWER,
  layout: {
    integration_id: 1,
    elements: [
      ...ANSWER.layout.elements,
      { id: 'floor', type: 'light', x: 16, y: 56, rid: 'r-floor', entity_id: 'light.floor_lamp', name: 'Floor lamp', style: 'pill' },
      { id: 'path', type: 'light', x: 216, y: 56, rid: 'r-path', entity_id: 'light.garden_path', name: 'Garden path', style: 'pill' },
      { id: 'gone', type: 'light', x: 416, y: 56, rid: 'r-gone', entity_id: 'light.old_desk', name: 'Old desk', style: 'pill' },
    ],
  },
  lights: {
    floor: { ...OFFER.lights[1], missing: false },
    path: { ...OFFER.lights[2], missing: false },
    gone: { missing: true },
  },
}

it('shows each lamp as Home Assistant reports it, and one that went by the name it had', async () => {
  show(WITH_LAMPS)
  const floor = (await screen.findByText('Floor lamp')).closest('[data-lamp]') as HTMLElement
  expect(floor).toHaveTextContent('62 %')
  expect(floor.getAttribute('style') ?? '').toContain('rgb(255, 167, 87)')
  expect((screen.getByText('Garden path').closest('[data-lamp]') as HTMLElement)).toHaveTextContent('off')
  const gone = screen.getByText('Old desk').closest('[data-lamp]') as HTMLElement
  expect(gone).toHaveTextContent('gone')
  expect(gone.title).toContain('no longer in Home Assistant')
})

it('lets an editor pick lamps, offers none twice, and places the new ones side by side below the rest', async () => {
  const sent = show(WITH_LAMPS, { editing: true })
  await screen.findByText('Floor lamp')
  fireEvent.click(screen.getAllByRole('button', { name: 'Light' })[0])
  expect(await screen.findByRole('checkbox', { name: 'Kitchen counter' })).toBeInTheDocument()
  expect(screen.getByRole('checkbox', { name: 'Floor lamp' })).toBeDisabled()
  const search = screen.getByRole('textbox', { name: 'Search by name, room or entity id' })
  fireEvent.change(search, { target: { value: 'kitchen' } })
  expect(screen.queryByRole('checkbox', { name: 'Ceiling light' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('checkbox', { name: 'Kitchen counter' }))
  fireEvent.change(search, { target: { value: '' } })
  fireEvent.click(screen.getByRole('checkbox', { name: 'Ceiling light' }))
  fireEvent.click(screen.getByRole('button', { name: 'Add (2)' }))
  await waitFor(() => expect(puts(sent)).toHaveLength(1))
  const added = (puts(sent)[0].body!.elements as Record<string, unknown>[]).filter((element) => !['living', 'garden', 'floor', 'path', 'gone'].includes(String(element.id)))
  expect(added).toEqual([
    expect.objectContaining({ type: 'light', rid: 'r-ceiling', entity_id: 'light.ceiling', name: 'Ceiling light', style: 'pill', x: 16, y: 112 }),
    expect.objectContaining({ type: 'light', rid: 'r-counter', entity_id: 'light.kitchen_counter', name: 'Kitchen counter', style: 'pill', x: 288, y: 112 }),
  ])
  // The page is asked again, so the new lamps show how they stand.
  await waitFor(() => expect(sent.filter((one) => one.method === 'GET' && one.url.endsWith('/pages/9/home')).length).toBeGreaterThan(1))
  expect(screen.getByText('Ceiling light').closest('[data-lamp]')).toHaveTextContent('80 %')
})

it('says why no lamps can be offered', async () => {
  show(WITH_LAMPS, {
    editing: true,
    offer: { lights: [], problem: { code: 'not_admin', message: 'Home Assistant lets only an administrator read which lamps there are.', hint: 'Use a long-lived token of an administrator for this connection.' } },
  })
  await screen.findByText('Floor lamp')
  fireEvent.click(screen.getAllByRole('button', { name: 'Light' })[0])
  expect(await screen.findByText('Only an administrator of Home Assistant may read which lights there are.')).toBeInTheDocument()
  expect(screen.getByText('Use a long-lived token of an administrator for this connection.')).toBeInTheDocument()
})

it('moves a lamp but does not try to rename it', async () => {
  const sent = show(WITH_LAMPS, { editing: true })
  const spot = (await screen.findByText('Floor lamp')).closest('[data-element]') as HTMLElement
  fireEvent.pointerDown(spot, { pointerId: 1, button: 0, clientX: 50, clientY: 50 })
  fireEvent.pointerUp(spot, { pointerId: 1, clientX: 50, clientY: 50 })
  expect(screen.queryByRole('textbox', { name: 'Name of the heading' })).not.toBeInTheDocument()
  fireEvent.pointerDown(spot, { pointerId: 2, button: 0, clientX: 50, clientY: 50 })
  fireEvent.pointerMove(spot, { pointerId: 2, clientX: 90, clientY: 50 })
  fireEvent.pointerUp(spot, { pointerId: 2, clientX: 90, clientY: 50 })
  await waitFor(() => expect(puts(sent)).toHaveLength(1))
  const floor = (puts(sent)[0].body!.elements as Record<string, unknown>[]).find((element) => element.id === 'floor')
  expect(floor).toMatchObject({ x: 56, y: 56, rid: 'r-floor', entity_id: 'light.floor_lamp', type: 'light' })
  expect(floor).not.toHaveProperty('text')
})

// -- switching ---------------------------------------------------------------

const posts = (sent: Sent[]) => sent.filter((one) => one.method === 'POST')
// The pill, not the title of its details, which says the same name.
const pill = (name: string) => [...document.querySelectorAll<HTMLElement>('[data-lamp]')].find((element) => element.textContent?.includes(name)) as HTMLElement

/** A promise to answer a switch with, later. */
function later() {
  let answer: (response: Response) => void = () => undefined
  const promise = new Promise<Response>((resolve) => { answer = resolve })
  return { promise, answer }
}

it('switches a lamp at a tap, shows it at once, then as the server says', async () => {
  const reply = later()
  const sent = show(WITH_LAMPS, { canAct: true, switcher: () => reply.promise })
  fireEvent.click(await screen.findByRole('button', { name: /Floor lamp/ }))
  expect(pill('Floor lamp')).toHaveTextContent('off')
  expect(pill('Floor lamp')).toHaveAttribute('aria-pressed', 'false')
  await waitFor(() => expect(posts(sent)).toHaveLength(1))
  expect(posts(sent)[0]).toMatchObject({ url: '/api/v1/pages/9/home/lights/floor', body: { on: false } })
  await act(async () => reply.answer(json({ ok: true, confirmed: true, light: { ...OFFER.lights[1], on: false, pct: null, rgb: null, missing: false } })))
  expect(pill('Floor lamp')).toHaveTextContent('off')
})

it('keeps a lamp as asked when Home Assistant names nothing that changed', async () => {
  // A lamp already on is not in Home Assistant's list of what changed; the server says so with ``confirmed``.
  const sent = show(WITH_LAMPS, { canAct: true, switcher: () => json({ ok: true, confirmed: false, light: { ...OFFER.lights[2], on: false, missing: false } }) })
  fireEvent.click(await screen.findByRole('button', { name: /Garden path/ }))
  await waitFor(() => expect(posts(sent)).toHaveLength(1))
  expect(posts(sent)[0].body).toEqual({ on: true })
  await waitFor(() => expect(pill('Garden path')).toHaveTextContent('on'))
  await act(async () => new Promise((resolve) => window.setTimeout(resolve, 20)))
  expect(pill('Garden path')).toHaveAttribute('aria-pressed', 'true')
})

it('takes a refused switch back and says why', async () => {
  show(WITH_LAMPS, { canAct: true, switcher: () => json({ detail: { code: 'lamp_unavailable', message: 'Home Assistant cannot reach Floor lamp right now.' } }, 409) })
  fireEvent.click(await screen.findByRole('button', { name: /Floor lamp/ }))
  expect(await screen.findByText('Home Assistant cannot reach Floor lamp right now.')).toBeInTheDocument()
  expect(pill('Floor lamp')).toHaveTextContent('62 %')
  expect(pill('Floor lamp')).toHaveAttribute('aria-pressed', 'true')
})

it('sends two quick taps one after the other, and the lamp ends as the last one asked', async () => {
  const replies = [later(), later()]
  let asked = 0
  const sent = show(WITH_LAMPS, { canAct: true, switcher: () => replies[asked++].promise })
  const floor = await screen.findByRole('button', { name: /Floor lamp/ })
  fireEvent.click(floor)
  fireEvent.click(floor)
  expect(pill('Floor lamp')).toHaveTextContent('62 %')
  await waitFor(() => expect(posts(sent)).toHaveLength(1))
  await act(async () => replies[0].answer(json({ ok: true, confirmed: true, light: { ...OFFER.lights[1], on: false, pct: null, missing: false } })))
  await waitFor(() => expect(posts(sent)).toHaveLength(2))
  expect(posts(sent).map((one) => one.body)).toEqual([{ on: false }, { on: true }])
  expect(pill('Floor lamp')).toHaveAttribute('aria-pressed', 'true')
  await act(async () => replies[1].answer(json({ ok: true, confirmed: true, light: { ...OFFER.lights[1], missing: false } })))
  expect(pill('Floor lamp')).toHaveTextContent('62 %')
})

it('offers no switch to who may not act, while arranging, or on a lamp that went', async () => {
  show(WITH_LAMPS, { canAct: false })
  await screen.findByText('Floor lamp')
  expect(screen.queryByRole('button', { name: /Floor lamp/ })).not.toBeInTheDocument()
  cleanup()
  show(WITH_LAMPS, { canAct: true, editing: true })
  await screen.findByText('Floor lamp')
  // No lamp is a switch while the page is arranged (the guides' toggle in the bar is pressed, and no lamp).
  expect(document.querySelectorAll('button[data-lamp]')).toHaveLength(0)
  cleanup()
  show({ ...WITH_LAMPS, lights: { ...WITH_LAMPS.lights, path: { ...OFFER.lights[2], unavailable: true, missing: false } } }, { canAct: true })
  await screen.findByRole('button', { name: /Floor lamp/ })
  expect(screen.queryByRole('button', { name: /Old desk/ })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Garden path/ })).not.toBeInTheDocument()
  expect(pill('Garden path')).toHaveTextContent('offline')
})

// -- dimming and the details ---------------------------------------------------

/** A floor lamp that has whites and colours, and a garden path that only switches. */
const RICH: HomeAnswer = {
  ...WITH_LAMPS,
  lights: {
    ...WITH_LAMPS.lights,
    floor: { ...OFFER.lights[1], colour: true, kelvin_min: 2202, kelvin_max: 6535, missing: false },
  },
}

it('dims a lamp dragged sideways, sending the newest brightness and switching nothing', async () => {
  const replies = [later(), later()]
  let asked = 0
  const sent = show(RICH, { canAct: true, switcher: () => replies[asked++].promise })
  const floor = await screen.findByRole('button', { name: /Floor lamp/ })
  fireEvent.pointerDown(floor, { pointerId: 1, button: 0, clientX: 100, clientY: 20 })
  fireEvent.pointerMove(floor, { pointerId: 1, clientX: 110, clientY: 21 })
  fireEvent.pointerMove(floor, { pointerId: 1, clientX: 140, clientY: 22 })
  fireEvent.pointerMove(floor, { pointerId: 1, clientX: 140.4, clientY: 23 })
  // jsdom measures nothing, so the drag runs over the least travel there is, 160 px: 40 px are 25 points.
  expect(pill('Floor lamp')).toHaveTextContent('87 %')
  fireEvent.pointerUp(floor, { pointerId: 1, clientX: 140, clientY: 22 })
  fireEvent.click(floor)
  await waitFor(() => expect(posts(sent)).toHaveLength(1))
  await act(async () => replies[0].answer(json({ ok: true, confirmed: true, light: { ...RICH.lights!.floor, pct: 68 } })))
  await waitFor(() => expect(posts(sent)).toHaveLength(2), { timeout: 1000 })
  expect(posts(sent).map((one) => one.body)).toEqual([{ brightness_pct: 68 }, { brightness_pct: 87 }])
  await act(async () => replies[1].answer(json({ ok: true, confirmed: true, light: { ...RICH.lights!.floor, pct: 87 } })))
  expect(pill('Floor lamp')).toHaveTextContent('87 %')
})

it('dims a lamp by the arrow keys', async () => {
  const sent = show(RICH, { canAct: true })
  const floor = await screen.findByRole('button', { name: /Floor lamp/ })
  fireEvent.keyDown(floor, { key: 'ArrowRight' })
  await waitFor(() => expect(posts(sent)).toHaveLength(1))
  expect(posts(sent)[0].body).toEqual({ brightness_pct: 72 })
})

it('opens the details when a lamp is held, and the press that opened them switches nothing', async () => {
  const sent = show(RICH, { canAct: true })
  const floor = await screen.findByRole('button', { name: /Floor lamp/ })
  fireEvent.pointerDown(floor, { pointerId: 1, button: 0, clientX: 100, clientY: 20 })
  const panel = await screen.findByRole('dialog', {}, { timeout: 1500 })
  fireEvent.pointerUp(floor, { pointerId: 1, clientX: 100, clientY: 20 })
  fireEvent.click(floor)
  expect(panel).toHaveTextContent('Floor lamp')
  expect(posts(sent)).toHaveLength(0)

  fireEvent.change(screen.getByRole('slider', { name: /Brightness/ }), { target: { value: '40' } })
  await waitFor(() => expect(posts(sent)).toHaveLength(1))
  expect(posts(sent)[0].body).toEqual({ brightness_pct: 40 })
  expect(pill('Floor lamp')).toHaveTextContent('40 %')

  // Lit in a colour, so the details open on the colours.
  expect(screen.getByRole('radio', { name: 'Colour' })).toHaveAttribute('aria-checked', 'true')
  fireEvent.click(screen.getByRole('radio', { name: 'White' }))
  expect(screen.queryByRole('slider', { name: /Hue/ })).not.toBeInTheDocument()
  const white = screen.getByRole('slider', { name: /White/ })
  // The lamp's own whites, on whole fifties.
  expect(white).toHaveAttribute('min', '2250')
  expect(white).toHaveAttribute('max', '6500')
  fireEvent.click(screen.getByRole('radio', { name: 'Colour' }))
  expect(screen.queryByRole('slider', { name: /White/ })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Colour at 235°' }))
  await waitFor(() => expect(posts(sent).map((one) => one.body)).toContainEqual({ hs: [235, 85] }), { timeout: 1500 })
  fireEvent.click(screen.getByRole('button', { name: 'Turn off' }))
  await waitFor(() => expect(posts(sent).at(-1)?.body).toEqual({ on: false }), { timeout: 1500 })
})

it('opens the details by a right click, showing only what the lamp can do', async () => {
  show(RICH, { canAct: true })
  fireEvent.contextMenu(await screen.findByRole('button', { name: /Garden path/ }))
  const panel = await screen.findByRole('dialog')
  expect(panel).toHaveTextContent('Garden path')
  expect(screen.queryByRole('slider')).not.toBeInTheDocument()
  expect(screen.queryByRole('radio')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Turn on' })).toBeInTheDocument()
})

it('does not dim a lamp that only switches', async () => {
  const sent = show(RICH, { canAct: true })
  const path = await screen.findByRole('button', { name: /Garden path/ })
  fireEvent.pointerDown(path, { pointerId: 1, button: 0, clientX: 100, clientY: 20 })
  fireEvent.pointerMove(path, { pointerId: 1, clientX: 160, clientY: 20 })
  fireEvent.pointerUp(path, { pointerId: 1, clientX: 160, clientY: 20 })
  fireEvent.keyDown(path, { key: 'ArrowRight' })
  await act(async () => new Promise((resolve) => window.setTimeout(resolve, 50)))
  expect(posts(sent).filter((one) => 'brightness_pct' in (one.body ?? {}))).toEqual([])
})

it('takes back what Home Assistant never confirmed, a moment later', async () => {
  // Asked on, but Home Assistant names nothing that changed and the server still knows it off.
  show(WITH_LAMPS, { canAct: true, switcher: () => json({ ok: true, confirmed: false, light: { ...OFFER.lights[2], on: false, missing: false } }) })
  fireEvent.click(await screen.findByRole('button', { name: /Garden path/ }))
  await waitFor(() => expect(pill('Garden path')).toHaveTextContent('on'))
  await waitFor(() => expect(pill('Garden path')).toHaveTextContent('off'), { timeout: SETTLE_MS + 1500 })
}, SETTLE_MS + 5000)

it('tells the lamp each brightness of a drag once, however long the finger rests', async () => {
  const sent = show(RICH, { canAct: true })
  const floor = await screen.findByRole('button', { name: /Floor lamp/ })
  fireEvent.pointerDown(floor, { pointerId: 1, button: 0, clientX: 100, clientY: 20 })
  fireEvent.pointerMove(floor, { pointerId: 1, clientX: 140, clientY: 20 })
  await waitFor(() => expect(posts(sent)).toHaveLength(1))
  await act(async () => new Promise((resolve) => window.setTimeout(resolve, 400)))
  fireEvent.pointerMove(floor, { pointerId: 1, clientX: 140.4, clientY: 21 })
  await act(async () => new Promise((resolve) => window.setTimeout(resolve, 400)))
  fireEvent.pointerUp(floor, { pointerId: 1, clientX: 140.4, clientY: 21 })
  expect(posts(sent).map((one) => one.body)).toEqual([{ brightness_pct: 87 }])
})

it('sets the colour sliders from the colour a lamp names only in rgb', async () => {
  show(RICH, { canAct: true })
  fireEvent.contextMenu(await screen.findByRole('button', { name: /Floor lamp/ }))
  await screen.findByRole('dialog')
  // rgb(255, 167, 87) is a hue of 28.6° at 65.9 %, not the sliders' starting point.
  expect(screen.getByRole('slider', { name: /Hue/ })).toHaveValue('29')
  expect(screen.getByRole('slider', { name: /Saturation/ })).toHaveValue('66')
})

// -- styles and the phone ------------------------------------------------------

const EVERY_STYLE: HomeAnswer = {
  ...WITH_LAMPS,
  layout: {
    integration_id: 1,
    elements: LAMP_STYLES.map((style, index) => ({ id: `l${index}`, type: 'light' as const, x: 16 + index * 100, y: 16, rid: 'r-floor', entity_id: 'light.floor_lamp', name: 'Floor lamp', style })),
  },
  lights: Object.fromEntries(LAMP_STYLES.map((_, index) => [`l${index}`, { ...OFFER.lights[1], missing: false as const }])),
}

it('draws a lamp in each of the ten styles, each one a switch with its name', async () => {
  show(EVERY_STYLE, { canAct: true })
  await screen.findAllByRole('button', { name: /Floor lamp/ })
  const drawn = screen.getAllByRole('button', { name: /Floor lamp/ })
  expect(drawn.map((one) => one.getAttribute('data-style'))).toEqual([...LAMP_STYLES])
  for (const one of drawn) expect(one).toHaveAttribute('aria-pressed', 'true')
})

it('changes the style of a lamp while the page is arranged, and saves it', async () => {
  const sent = show(WITH_LAMPS, { editing: true })
  await screen.findByText('Floor lamp')
  const tools = (document.querySelector('[data-element="floor"]') as HTMLElement)
  const choose = within(tools).getByRole('button', { name: 'Choose a style' })
  // Beside the drawing, not in it: a pill clips what reaches past its edge.
  expect(tools.querySelector('[data-lamp]')?.contains(choose)).toBe(false)
  fireEvent.click(choose)
  fireEvent.keyDown(window, { key: 'Escape' })
  expect(within(tools).queryByRole('menu')).not.toBeInTheDocument()
  fireEvent.click(choose)
  fireEvent.pointerDown(document.body)
  expect(within(tools).queryByRole('menu')).not.toBeInTheDocument()
  fireEvent.click(choose)
  fireEvent.click(within(tools).getByRole('menuitemradio', { name: 'Knob' }))
  await waitFor(() => expect(puts(sent)).toHaveLength(1))
  const floor = (puts(sent)[0].body!.elements as Record<string, unknown>[]).find((element) => element.id === 'floor')
  expect(floor).toMatchObject({ style: 'knob', x: 16, y: 56, rid: 'r-floor' })
  expect(document.querySelector('[data-element="floor"] [data-style]')).toHaveAttribute('data-style', 'knob')
})

it('adds lamps in the style picked for them, spaced for that style', async () => {
  const sent = show(ANSWER, { editing: true })
  await screen.findByText('Living room')
  fireEvent.click(screen.getAllByRole('button', { name: 'Light' })[0])
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Kitchen counter' }))
  fireEvent.click(screen.getByRole('checkbox', { name: 'Ceiling light' }))
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'tile' } })
  fireEvent.click(screen.getByRole('button', { name: 'Add (2)' }))
  await waitFor(() => expect(puts(sent)).toHaveLength(1))
  const added = (puts(sent)[0].body!.elements as Record<string, unknown>[]).filter((element) => element.type === 'light')
  expect(added.map((element) => [element.name, element.style, element.x, element.y])).toEqual([['Ceiling light', 'tile', 16, 56], ['Kitchen counter', 'tile', 120, 56]])
})

it('shows a phone each heading with the lamps that stand under it', async () => {
  const wide = window.matchMedia
  window.matchMedia = ((query: string) => ({ matches: true, media: query, addEventListener: () => undefined, removeEventListener: () => undefined })) as unknown as typeof window.matchMedia
  try {
    show({
      ...WITH_LAMPS,
      layout: {
        integration_id: 1,
        elements: [
          ...ANSWER.layout.elements,
          { id: 'floor', type: 'light', x: 16, y: 56, rid: 'r-floor', entity_id: 'light.floor_lamp', name: 'Floor lamp', style: 'round' },
          { id: 'path', type: 'light', x: 330, y: 56, rid: 'r-path', entity_id: 'light.garden_path', name: 'Garden path', style: 'chip' },
        ],
      },
    })
    await screen.findByText('Floor lamp')
    const garden = document.querySelector('[data-phone-group="garden"]') as HTMLElement
    const living = document.querySelector('[data-phone-group="living"]') as HTMLElement
    expect(within(garden).getByText('Garden path')).toBeInTheDocument()
    expect(within(living).getByText('Floor lamp')).toBeInTheDocument()
    expect(within(living).queryByText('Garden path')).not.toBeInTheDocument()
    expect(pill('Garden path').parentElement).toHaveClass('w-full')
    expect(pill('Floor lamp').parentElement).not.toHaveClass('w-full')
    // A chip runs the width of the screen too, its own limit of 200 px lifted.
    expect(pill('Garden path')).toHaveClass('w-full', 'max-w-none')
  } finally {
    window.matchMedia = wide
  }
})

/** The part of each drawing that makes it that drawing (``lampFace`` and the ``lamp-*`` classes). */
const DRAWING: Record<string, string> = {
  pill: '.lamp-pill', round: '.lamp-round', chip: '.lamp-chip', tile: '.lamp-tile', slider: '.lamp-slide',
  ring: '.lamp-ring', rocker: '.lamp-plate', dots: '.lamp-dots', bulb: '.lamp-bulb', knob: '.lamp-knob',
}

it('gives each style its own drawing, and shows in it how bright the lamp is', async () => {
  show({
    ...EVERY_STYLE,
    layout: { ...EVERY_STYLE.layout, elements: [...EVERY_STYLE.layout.elements, { id: 'dark', type: 'light', x: 16, y: 200, rid: 'r-path', entity_id: 'light.garden_path', name: 'Garden path', style: 'slider' }] },
    lights: { ...EVERY_STYLE.lights, dark: { ...OFFER.lights[2], missing: false } },
  }, { canAct: true })
  await screen.findAllByRole('button', { name: /Floor lamp/ })
  for (const one of screen.getAllByRole('button', { name: /Floor lamp/ })) {
    const style = one.getAttribute('data-style') ?? ''
    const drawing = DRAWING[style]
    expect(one.matches(drawing) || one.querySelector(drawing) !== null, style).toBe(true)
    for (const [other, selector] of Object.entries(DRAWING)) {
      if (other !== style) expect(one.matches(selector) || one.querySelector(selector) !== null, `${style} drawn as ${other}`).toBe(false)
    }
  }
  const byStyle = (style: string) => document.querySelector(`[data-element] [data-style="${style}"][aria-label^="Floor lamp"]`) as HTMLElement
  expect((byStyle('slider').querySelector('.lamp-fill') as HTMLElement).style.width).toBe('62%')
  expect(byStyle('ring').querySelector('.lamp-arc-lit')).not.toBeNull()
  expect(byStyle('knob').querySelectorAll('.lamp-led.is-on')).toHaveLength(9)
  expect(byStyle('rocker').querySelector('.lamp-plate.is-on')).not.toBeNull()
  const off = document.querySelector('[data-style="slider"][aria-label^="Garden path"]') as HTMLElement
  expect(off.querySelector('.lamp-fill')).toBeNull()
  expect(off).toHaveTextContent('off')
})
