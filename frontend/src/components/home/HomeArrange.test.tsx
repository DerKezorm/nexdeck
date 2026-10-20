/**
 * Arranging a home page: guides that line things up and can be switched off,
 * widths dragged at the edge, every pill as wide as the next, and a name too
 * long for its pill running as a ticker. jsdom measures nothing, so the
 * boxes are stood in for: each element as wide as ``WIDTHS`` says, 40 high.
 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterAll, beforeAll, beforeEach, vi } from 'vitest'

import { DEFAULT_WIDTH, type HomeAnswer } from '../../lib/home'
import { Marquee } from './Marquee'
import { HomePage } from './HomePage'

type Sent = { url: string; method: string; body: Record<string, unknown> | null }

const lamp = (id: string, x: number, y: number, name: string, extra: Record<string, unknown> = {}) =>
  ({ id, type: 'light' as const, x, y, rid: `r-${id}`, entity_id: `light.${id}`, name, style: 'pill' as const, ...extra })

const ANSWER: HomeAnswer = {
  version: 1,
  problem: null,
  layout: {
    integration_id: 1,
    elements: [
      lamp('a', 100, 40, 'Floor lamp'),
      lamp('b', 400, 200, 'A kitchen counter lamp with a long name'),
      lamp('c', 100, 300, 'Desk', { width: 160 }),
    ],
  },
  lights: {},
}

/** How wide each element is drawn, as the browser would measure it. */
const WIDTHS: Record<string, number> = { a: 224, b: 224, c: 160 }
const measured = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect')

beforeAll(() => {
  measured.mockImplementation(function (this: HTMLElement) {
    const id = this.dataset.element
    if (id) {
      const left = parseFloat(this.style.left) || 0
      const top = parseFloat(this.style.top) || 0
      return { left, top, width: WIDTHS[id] ?? 100, height: 40, right: left + (WIDTHS[id] ?? 100), bottom: top + 40, x: left, y: top, toJSON: () => ({}) } as DOMRect
    }
    return { left: 0, top: 0, width: 0, height: 0, right: 0, bottom: 0, x: 0, y: 0, toJSON: () => ({}) } as DOMRect
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

function show(answer: HomeAnswer = ANSWER) {
  const sent: Sent[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : null
    sent.push({ url, method, body })
    const json = (value: unknown) => new Response(JSON.stringify(value), { status: 200, headers: { 'content-type': 'application/json' } })
    if (method === 'PUT') return json({ layout: { ...answer.layout, elements: body.elements }, version: answer.version + 1 })
    return json(answer)
  }))
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <HomePage pageId={9} editing canEdit canAct onAddPage={() => undefined} onSettings={() => undefined} onDone={() => undefined} />
    </QueryClientProvider>,
  )
  return sent
}

const puts = (sent: Sent[]) => sent.filter((one) => one.method === 'PUT')
const saved = (sent: Sent[], id: string) => (puts(sent).at(-1)!.body!.elements as Record<string, unknown>[]).find((element) => element.id === id)
const spot = (id: string) => document.querySelector(`[data-element="${id}"]`) as HTMLElement

/** Drags an element, or the grip at its edge, by so much, in three moves as a hand would. */
function drag(from: HTMLElement, dx: number, dy: number) {
  const target = spot(from.closest('[data-element]')!.getAttribute('data-element')!)
  fireEvent.pointerDown(from, { pointerId: 1, button: 0, clientX: 500, clientY: 500 })
  fireEvent.pointerMove(target, { pointerId: 1, clientX: 500 + dx / 2, clientY: 500 + dy / 2 })
  fireEvent.pointerMove(target, { pointerId: 1, clientX: 500 + dx, clientY: 500 + dy })
}

it('lines a dragged lamp up with another and draws the guide, and only on the step without guides', async () => {
  const sent = show()
  await screen.findByText('Floor lamp')
  // c starts at 100, 300; moved 3 px right of a's left edge (100) it snaps back onto it.
  drag(spot('c'), 3, -40)
  expect(document.querySelector('[data-guide="x"]')).not.toBeNull()
  fireEvent.pointerUp(spot('c'), { pointerId: 1, clientX: 503, clientY: 460 })
  await waitFor(() => expect(puts(sent)).toHaveLength(1))
  expect(saved(sent, 'c')).toMatchObject({ x: 100, y: 264 })
  expect(document.querySelector('[data-guide]')).toBeNull()

  fireEvent.click(screen.getByRole('button', { name: 'Guides' }))
  expect(screen.getByRole('button', { name: 'Guides' })).toHaveAttribute('aria-pressed', 'false')
  expect(localStorage.getItem('nexdeck.homeGuides')).toBe('off')
  expect(document.querySelector('[data-home-surface]')).not.toHaveAttribute('data-guides')
  // From 100, 5 px is 105: on the step that is 104, though a's edge at 100 is near.
  drag(spot('c'), 5, 0)
  expect(document.querySelector('[data-guide]')).toBeNull()
  fireEvent.pointerUp(spot('c'), { pointerId: 1, clientX: 505, clientY: 500 })
  await waitFor(() => expect(puts(sent)).toHaveLength(2))
  expect(saved(sent, 'c')).toMatchObject({ x: 104, y: 264 })
})

it('remembers in the browser that the guides are off', async () => {
  localStorage.setItem('nexdeck.homeGuides', 'off')
  show()
  await screen.findByText('Floor lamp')
  expect(screen.getByRole('button', { name: 'Guides' })).toHaveAttribute('aria-pressed', 'false')
  expect((document.querySelector('[data-home-surface]') as HTMLElement).style.backgroundImage).toBe('')
})

it('changes a width at the grip, to the step or as wide as another', async () => {
  const sent = show()
  await screen.findByText('Floor lamp')
  const grip = spot('c').querySelector('[data-resize]') as HTMLElement
  expect(grip).not.toBeNull()
  // From 160: 61 px wider is 221, near enough to a's 224 to become as wide as it.
  drag(grip, 61, 0)
  expect(document.querySelectorAll('[data-guide="y"]')).toHaveLength(2)
  fireEvent.pointerUp(spot('c'), { pointerId: 1, clientX: 561, clientY: 500 })
  await waitFor(() => expect(puts(sent)).toHaveLength(1))
  expect(saved(sent, 'c')).toMatchObject({ width: 224, x: 100, y: 300 })
  drag(spot('a').querySelector('[data-resize]') as HTMLElement, 37, 0)
  fireEvent.pointerUp(spot('a'), { pointerId: 1, clientX: 537, clientY: 500 })
  await waitFor(() => expect(puts(sent)).toHaveLength(2))
  // No other near: on the step.
  expect(saved(sent, 'a')).toMatchObject({ width: 264, x: 100, y: 40 })
})

it('draws every pill as wide as the next, whatever its name, unless it was given a width', async () => {
  show()
  await screen.findByText('Floor lamp')
  const width = (id: string) => (spot(id).querySelector('[data-lamp]') as HTMLElement).style.width
  expect(width('a')).toBe(`${DEFAULT_WIDTH.pill}px`)
  expect(width('b')).toBe(`${DEFAULT_WIDTH.pill}px`)
  expect(width('c')).toBe('160px')
})

it('runs a name that does not fit as a ticker, and leaves one that fits alone', async () => {
  const sizes = vi.spyOn(Element.prototype, 'scrollWidth', 'get').mockImplementation(function (this: Element) {
    return (this.textContent ?? '').length * 7
  })
  const room = vi.spyOn(Element.prototype, 'clientWidth', 'get').mockReturnValue(120)
  try {
    render(
      <div>
        <Marquee text="A kitchen counter lamp with a long name" />
        <Marquee text="Desk" />
      </div>,
    )
    await act(async () => undefined)
    const [long, short] = Array.from(document.querySelectorAll<HTMLElement>('.lamp-marquee'))
    expect(long).toHaveAttribute('data-marquee')
    expect(long.style.getPropertyValue('--shift')).toBe(`-${39 * 7 - 120}px`)
    expect(long).toHaveAttribute('title', 'A kitchen counter lamp with a long name')
    expect(short).not.toHaveAttribute('data-marquee')
    expect(within(short).getByText('Desk')).toBeInTheDocument()
  } finally {
    sizes.mockRestore()
    room.mockRestore()
  }
})
