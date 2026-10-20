/**
 * The topology page in the browser: what the console reports stands on the
 * plan, a new page saves its arrangement once (and only for editors), a
 * device opens its panel, a phone gets the list, and a refusal is said.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, vi } from 'vitest'

import type { TopoAnswer, TopoLink } from '../../lib/topology'
import { TopologyPage } from './TopologyPage'

function link(id: string, a: string, b: string, extra: Partial<TopoLink> = {}): TopoLink {
  return {
    id, a, b, port_a: { index: 12, name: '' }, port_b: { index: 1, name: '' }, kind: 'wire', state: 'up', speed: 1e9,
    down: 1e6, up: 2e5, meter: a, age: 20, every: 70, history: { down: [1e6, 1.2e6], up: [2e5, 3e5] }, ...extra,
  }
}

const ANSWER: TopoAnswer = {
  version: 3,
  problem: null,
  layout: { integration_id: 1, start: 'all', seeded: true, placed: ['internet', 'gw', 'core', 'ap'], clients: [], hidden: [], positions: {} },
  data: {
    nodes: [
      { id: 'internet', name: 'Internet', model: 'Example Fibre', kind: 'internet', status: 'ok', every: null, facts: { isp: 'Example Fibre' } },
      { id: 'gw', name: 'Gateway', model: 'UDM Pro', kind: 'gateway', status: 'ok', every: 10, facts: { ip: '192.168.1.1', uptime: 3600 } },
      { id: 'core', name: 'Core switch', model: 'USW Pro 24', kind: 'switch', status: 'ok', every: 70, facts: { ip: '192.168.1.2' }, wired_clients: 1 },
      { id: 'ap', name: 'Hall AP', model: 'U7 Lite', kind: 'ap', status: 'ok', every: 70, facts: {}, wifi_clients: 6 },
      { id: 'mesh', name: 'Garden AP', model: 'U6 Mesh', kind: 'ap', status: 'offline', every: null, facts: { last_seen_ago: 7200 }, wifi_clients: 0 },
    ],
    links: [
      link('link:internet', 'internet', 'gw', { kind: 'wan', meter: 'gw', down: 120e6, up: 18e6, age: 2 }),
      link('link:core', 'gw', 'core', { meter: 'gw' }),
      link('link:ap', 'core', 'ap'),
      link('link:mesh', 'ap', 'mesh', { kind: 'wifi', state: 'down', down: null, up: null, age: null }),
    ],
    clients: [{ id: 'nas', name: 'nas01', kind: 'nas', ip: '192.168.1.10', at: 'core', port: { index: 26, name: '' }, speed: 1e10 }],
    client_links: [link('client:nas', 'core', 'nas')],
  },
}

type Sent = { url: string; method: string; body: Record<string, unknown> | null }

function serve(answer: TopoAnswer, sent: Sent[]) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    sent.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null })
    const json = (value: unknown) => new Response(JSON.stringify(value), { status: 200, headers: { 'content-type': 'application/json' } })
    if (method === 'PUT') return json({ layout: { ...answer.layout, ...(init?.body ? JSON.parse(String(init.body)) : {}) }, version: answer.version + 1 })
    return json(answer)
  })
}

function show(answer: TopoAnswer, { canEdit = true, editing = false } = {}) {
  const sent: Sent[] = []
  vi.stubGlobal('fetch', serve(answer, sent))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <TopologyPage pageId={7} editing={editing} canEdit={canEdit} onAddPage={() => undefined} onSettings={() => undefined} onDone={() => undefined} />
    </QueryClientProvider>,
  )
  return sent
}

afterEach(() => {
  vi.unstubAllGlobals()
})

/** A card by its name: the name stands in its text and, for the hover, in its title. */
async function card(name: string) {
  const texts = await screen.findAllByText(name, { selector: '[data-node] span' })
  return texts[0].closest('[data-node]')!
}

it('draws the devices on the plan with the traffic on their links and counts what is new', async () => {
  show(ANSWER)
  expect(await card('Core switch')).toBeInTheDocument()
  expect(await card('Hall AP')).toBeInTheDocument()
  // The mesh AP is not placed: it waits under Found, not on the plan.
  expect(screen.queryAllByText('Garden AP')).toEqual([])
  expect(screen.getByRole('button', { name: /Found\s*1/ })).toBeInTheDocument()
  expect(screen.getByText(/▼ 120 Mbit\/s/)).toBeInTheDocument()
  expect(document.querySelectorAll('[data-topology-label]').length).toBeGreaterThan(0)
})

it('saves where everything stands on a new page once, and only for someone who may edit', async () => {
  const sent = show(ANSWER)
  await waitFor(() => expect(sent.some((one) => one.method === 'PUT')).toBe(true), { timeout: 4000 })
  const saved = sent.find((one) => one.method === 'PUT')!
  expect(saved.url).toContain('/pages/7/topology')
  expect(Object.keys(saved.body!.positions as object).sort()).toEqual(['ap', 'core', 'gw', 'internet'])
  expect(saved.body!.version).toBe(3)
})

it('does not save for someone who may only look', async () => {
  const sent = show(ANSWER, { canEdit: false })
  await card('Core switch')
  await new Promise((resolve) => setTimeout(resolve, 2000))
  expect(sent.filter((one) => one.method === 'PUT')).toEqual([])
})

it('opens a device with its links, its wired clients and its way out', async () => {
  show(ANSWER)
  const core = await card('Core switch')
  fireEvent.pointerDown(core.querySelector('section')!, { pointerId: 1 })
  fireEvent.pointerUp(document.querySelector('[data-topology-canvas]')!, { pointerId: 1 })
  const heading = await screen.findByRole('heading', { name: 'Core switch' })
  const panel = heading.closest('aside')!
  expect(within(panel).getByText('Links (2)')).toBeInTheDocument()
  expect(within(panel).getByText('nas01')).toBeInTheDocument()
  expect(within(panel).getByText('Way to the internet')).toBeInTheDocument()
})

it('shows a phone the network as a list', async () => {
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: query.includes('max-width'), media: query, addEventListener: () => undefined, removeEventListener: () => undefined }))
  show(ANSWER)
  const list = await screen.findByRole('list', { name: 'Network plan' })
  expect(within(list).getByText('Core switch')).toBeInTheDocument()
  expect(document.querySelector('[data-topology-canvas]')).toBeNull()
})

it('says what the console said instead of drawing nothing', async () => {
  show({ ...ANSWER, data: null, problem: { code: 'auth_failed', message: 'The UniFi console rejected the API key.', hint: '' } })
  expect(await screen.findByText('The UniFi console rejected the API key or the password.')).toBeInTheDocument()
})

it('lets the buttons on the plan be pressed instead of starting a pan', async () => {
  // ⚠️ Catching the pointer for a pan swallowed the click of the display menu (19.10.2026).
  const capture = vi.fn()
  Object.defineProperty(HTMLElement.prototype, 'setPointerCapture', { value: capture, configurable: true })
  show(ANSWER)
  await card('Core switch')
  const display = screen.getByRole('button', { name: 'Display' })
  fireEvent.pointerDown(display, { pointerId: 1 })
  expect(capture).not.toHaveBeenCalled()
  fireEvent.click(display)
  expect(screen.getByRole('radiogroup', { name: 'Lines' })).toBeInTheDocument()
  fireEvent.pointerDown(document.querySelector('[data-topology-canvas] svg')!, { pointerId: 2 })
  expect(capture).toHaveBeenCalledTimes(1)
  delete (HTMLElement.prototype as { setPointerCapture?: unknown }).setPointerCapture
})

it('saves a second change after the first, with the version the first got back', async () => {
  // A slow server: the plan saves its first arrangement, and "Arrange as a
  // tree" is pressed while that save is still on its way.
  const sent: Sent[] = []
  let version = ANSWER.version
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : null
    sent.push({ url: String(input), method, body })
    const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } })
    if (method !== 'PUT') return json(ANSWER)
    await new Promise((resolve) => setTimeout(resolve, 700))
    if (body.version !== version) return json({ detail: { code: 'layout_moved_on', message: 'moved on' } }, 409)
    version += 1
    return json({ layout: { ...ANSWER.layout, ...body }, version })
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <TopologyPage pageId={7} editing canEdit onAddPage={() => undefined} onSettings={() => undefined} onDone={() => undefined} />
    </QueryClientProvider>,
  )
  const puts = () => sent.filter((one) => one.method === 'PUT')
  await waitFor(() => expect(puts()).toHaveLength(1), { timeout: 4000 })
  fireEvent.click(screen.getByRole('button', { name: 'Arrange as a tree' }))
  await waitFor(() => expect(puts()).toHaveLength(2), { timeout: 4000 })
  await waitFor(() => expect(version).toBe(ANSWER.version + 2), { timeout: 4000 })
  expect(puts().map((one) => one.body!.version)).toEqual([ANSWER.version, ANSWER.version + 1])
  expect(screen.queryByText(/Somebody else changed this page/)).not.toBeInTheDocument()
}, 15000)

it('keeps the last plan when the console misses a look, and says so', async () => {
  show({ ...ANSWER, data: { ...ANSWER.data!, stale: { code: 'http_error', message: 'The UniFi console answered with HTTP 502.', for_seconds: 30 } } })
  expect(await screen.findByText(/UniFi did not answer, values from 3\d s ago/)).toBeInTheDocument()
  expect(await card('Core switch')).toBeInTheDocument()
})
