/**
 * The home page in the browser: headings stand where they were put, an
 * editor adds, renames, moves and removes them, each change is saved with
 * the version it started from, someone who may only look changes nothing,
 * and a connection that went is said.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterAll, afterEach, beforeAll, vi } from 'vitest'

import type { HomeAnswer } from '../../lib/home'
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

function serve(answer: HomeAnswer, sent: Sent[]) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : null
    sent.push({ url, method, body })
    const json = (value: unknown) => new Response(JSON.stringify(value), { status: 200, headers: { 'content-type': 'application/json' } })
    if (method === 'PUT') return json({ layout: { ...answer.layout, elements: body.elements }, version: answer.version + 1 })
    return json(answer)
  })
}

function show(answer: HomeAnswer, { canEdit = true, editing = false } = {}) {
  const sent: Sent[] = []
  vi.stubGlobal('fetch', serve(answer, sent))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <HomePage pageId={9} editing={editing} canEdit={canEdit} onAddPage={() => undefined} onSettings={() => undefined} onDone={() => undefined} />
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
  expect(added).toMatchObject({ x: 16, y: 72 })
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
      <HomePage pageId={9} editing canEdit onAddPage={() => undefined} onSettings={() => undefined} onDone={() => undefined} />
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
})
