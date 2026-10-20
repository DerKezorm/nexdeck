/**
 * The menus beside an element open where they can be read: upwards when
 * below would run under the edit bar at the foot of the screen, and over it
 * (seen 20.10.2026: a cover's style menu under the bar). jsdom measures
 * nothing: the bar and the menus are stood in for.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterAll, afterEach, beforeAll, beforeEach, vi } from 'vitest'

import type { HomeAnswer } from '../../lib/home'
import { HomePage } from './HomePage'

/** Where the menu stands before it is placed: low, or high on the screen. */
let menuTop = 410
let menuHeight = 110
const measured = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect')
beforeAll(() => {
  measured.mockImplementation(function (this: HTMLElement) {
    const box = this.hasAttribute('data-edit-bar') ? { top: 440, height: 48 }
      : this.getAttribute('role') === 'menu' && !this.hasAttribute('data-up') ? { top: menuTop, height: menuHeight }
      : { top: 0, height: 0 }
    return { left: 0, top: box.top, width: 200, height: box.height, right: 200, bottom: box.top + box.height, x: 0, y: box.top, toJSON: () => ({}) } as DOMRect
  })
})
afterAll(() => measured.mockRestore())

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

const ANSWER: HomeAnswer = {
  version: 1, problem: null, lights: {}, climates: {}, covers: {},
  layout: { integration_id: 1, elements: [{ id: 'c', type: 'cover', x: 16, y: 16, rid: 'r-c', entity_id: 'cover.kitchen', name: 'Kitchen', style: 'pill' }] },
}

function show() {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(ANSWER), { status: 200, headers: { 'content-type': 'application/json' } })))
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <HomePage pageId={9} editing canEdit canAct onAddPage={() => undefined} onSettings={() => undefined} onDone={() => undefined} />
    </QueryClientProvider>,
  )
}

it('opens a menu upwards and over the bar when below would run under it', async () => {
  menuTop = 410
  show()
  const cover = await waitFor(() => {
    const found = document.querySelector('[data-element="c"]') as HTMLElement | null
    if (!found) throw new Error('not drawn yet')
    return found
  })
  fireEvent.click(within(cover).getByRole('button', { name: 'Choose a style' }))
  const menu = await waitFor(() => {
    const found = within(cover).getByRole('menu')
    if (!found.style.zIndex) throw new Error('not placed yet')
    return found
  })
  expect(menu).toHaveAttribute('data-up')
  expect(menu.style.bottom).toBe('100%')
  expect(menu.style.zIndex).toBe('45')
  expect(screen.getByRole('button', { name: 'Done' })).toBeInTheDocument()
})

async function openMenu(): Promise<HTMLElement> {
  show()
  const cover = await waitFor(() => {
    const found = document.querySelector('[data-element="c"]') as HTMLElement | null
    if (!found) throw new Error('not drawn yet')
    return found
  })
  fireEvent.click(within(cover).getByRole('button', { name: 'Choose a style' }))
  return waitFor(() => {
    const found = within(cover).getByRole('menu')
    if (!found.style.zIndex) throw new Error('not placed yet')
    return found
  })
}

it('leaves a menu below where it fits, and where there is no room above it either', async () => {
  // Fits below, with room above as well: it stays below.
  menuTop = 200
  menuHeight = 110
  expect(await openMenu()).not.toHaveAttribute('data-up')
  cleanup()
  // Runs under the bar, but turned upwards it would leave the window at the top.
  menuTop = 100
  menuHeight = 400
  const tall = await openMenu()
  expect(tall).not.toHaveAttribute('data-up')
  expect(tall.style.bottom).toBe('')
})
