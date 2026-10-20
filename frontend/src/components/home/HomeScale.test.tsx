/**
 * A size of its own for every drawn style: dragged at the corner while
 * arranging, as a whole, never smaller than can be read or pressed; the
 * styles with a width of their own and the cards keep their grips. jsdom
 * measures nothing: each element is stood in for at 100 by 130 pixels.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterAll, afterEach, beforeAll, beforeEach, vi } from 'vitest'

import { heightOf, isScalable, scaleOf, scaleTo, SCALES, widthOf, type HomeAnswer, type HomeElement } from '../../lib/home'
import { HomePage } from './HomePage'

type Sent = { url: string; method: string; body: Record<string, unknown> | null }

const DOOR = { rid: 'r-door', entity_id: 'binary_sensor.front_door', name: 'Front door' }
const ELEMENTS: HomeElement[] = [
  { id: 'door', type: 'contact', x: 16, y: 16, ...DOOR, style: 'door' },
  { id: 'big', type: 'contact', x: 300, y: 16, ...DOOR, style: 'door', scale: 2 },
  { id: 'pill', type: 'contact', x: 16, y: 300, ...DOOR, style: 'pill' },
  { id: 'lamp', type: 'light', x: 600, y: 16, rid: 'r-l', entity_id: 'light.bulb', name: 'Bulb', style: 'bulb' },
]

const measured = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect')
beforeAll(() => {
  measured.mockImplementation(function (this: HTMLElement) {
    const size = this.dataset.element ? { width: 100, height: 130 } : { width: 0, height: 0 }
    const left = parseFloat(this.style.left) || 0
    const top = parseFloat(this.style.top) || 0
    return { left, top, ...size, right: left + size.width, bottom: top + size.height, x: left, y: top, toJSON: () => ({}) } as DOMRect
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

function show({ editing = true, canEdit = true } = {}) {
  const sent: Sent[] = []
  let current: HomeAnswer = { version: 1, problem: null, layout: { integration_id: 1, elements: ELEMENTS }, lights: {}, climates: {}, sensors: {} }
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : null
    sent.push({ url: String(input), method, body })
    const json = (value: unknown) => new Response(JSON.stringify(value), { status: 200, headers: { 'content-type': 'application/json' } })
    if (method === 'PUT') {
      current = { ...current, layout: { ...current.layout, elements: body.elements }, version: current.version + 1 }
      return json({ layout: current.layout, version: current.version })
    }
    return json(current)
  }))
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <HomePage pageId={9} editing={editing} canEdit={canEdit} canAct onAddPage={() => undefined} onSettings={() => undefined} onDone={() => undefined} />
    </QueryClientProvider>,
  )
  return sent
}

const spot = (id: string) => document.querySelector(`[data-element="${id}"]`) as HTMLElement
const puts = (sent: Sent[]) => sent.filter((one) => one.method === 'PUT')
const saved = (sent: Sent[], id: string) => (puts(sent).at(-1)!.body!.elements as Record<string, unknown>[]).find((one) => one.id === id)!

function drag(id: string, dx: number, dy: number) {
  const grip = spot(id).querySelector('[data-resize="scale"]') as HTMLElement
  fireEvent.pointerDown(grip, { pointerId: 1, button: 0, clientX: 500, clientY: 500 })
  fireEvent.pointerMove(spot(id), { pointerId: 1, clientX: 500 + dx / 2, clientY: 500 + dy / 2 })
  fireEvent.pointerMove(spot(id), { pointerId: 1, clientX: 500 + dx, clientY: 500 + dy })
  fireEvent.pointerUp(spot(id), { pointerId: 1, clientX: 500 + dx, clientY: 500 + dy })
}

it('draws an element at its own size as a whole, and the others as they are', async () => {
  show({ editing: false })
  await screen.findAllByText('Front door')
  expect(spot('big').querySelector('[data-scaled]')).toHaveStyle({ zoom: '2' })
  expect(spot('door').querySelector('[data-scaled]')).toBeNull()
})

it('grows a drawing at its corner and never shrinks it below what can be read', async () => {
  const sent = show()
  await screen.findAllByText('Front door')
  // From 1 at 100 wide, 50 to the right is half as big again.
  drag('door', 50, 10)
  await waitFor(() => expect(puts(sent)).toHaveLength(1))
  expect(saved(sent, 'door')).toMatchObject({ scale: 1.5, x: 16, y: 16 })
  drag('big', -900, -900)
  await waitFor(() => expect(puts(sent)).toHaveLength(2))
  // Three quarters at the least, as on the server.
  expect(saved(sent, 'big')).toMatchObject({ scale: 0.75 })
  drag('lamp', 0, 65)
  await waitFor(() => expect(puts(sent)).toHaveLength(3))
  // Down by half its height is half as big again too.
  expect(saved(sent, 'lamp')).toMatchObject({ scale: 1.5 })
})

it('gives the corner only to drawings, while arranging, to who arranges', async () => {
  show()
  await screen.findAllByText('Front door')
  expect(spot('door').querySelector('[data-resize="scale"]')).not.toBeNull()
  expect(spot('pill').querySelector('[data-resize="scale"]')).toBeNull()
  cleanup()
  show({ editing: false })
  await screen.findAllByText('Front door')
  expect(document.querySelector('[data-resize="scale"]')).toBeNull()
})

it('reckons with the size when placing and keeps the tools at theirs', () => {
  const door = ELEMENTS[0]
  const big = ELEMENTS[1]
  expect(isScalable(door)).toBe(true)
  expect(isScalable(ELEMENTS[2])).toBe(false)
  expect(scaleOf(big)).toBe(2)
  expect(scaleOf({ ...door, scale: 9 } as HomeElement)).toBe(SCALES[1])
  expect(heightOf(big)).toBe(heightOf(door) * 2)
  expect(widthOf(big)).toBe(widthOf(door) * 2)
  expect(scaleTo(1, 100, 33)).toBe(1.35)
  expect(scaleTo(2, 200, -1000)).toBe(SCALES[0])
  const css = readFileSync(join(process.cwd(), 'src/styles/app.css'), 'utf8')
  // Only the outermost tool: the name button sits in the tools and shrank twice (seen 20.10.2026).
  expect(css).toMatch(/\[data-scaled\] \[data-element-tool\]:not\(\[data-element-tool\] \*\), \[data-scaled\] \.home-grip \{\s*zoom: calc\(1 \/ var\(--home-scale, 1\)\);/)
})
