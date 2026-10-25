/**
 * What runs on what (roadmap M5): the list with its proposals, the map, the
 * field on a connection, and the cause a card names.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import i18n from 'i18next'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { factText } from '../../lib/assistant'
import { layered, tree, type Inventory } from '../../lib/inventory'
import type { WidgetView } from '../../lib/types'
import { InventorySettings } from '../../pages/settings/InventorySettings'
import { WidgetCard } from '../WidgetCard'
import { DependsOn } from './DependsOn'
import { InventoryMap } from './InventoryMap'

const sent: { method: string; path: string; body?: unknown }[] = []

const INVENTORY: Inventory = {
  nodes: [
    { ref: 'integration:1', kind: 'integration', service: 'proxmox', name: 'PVE', detail: '10.0.0.2:8006', host: true, down: false },
    { ref: 'guest:1:201', kind: 'guest', service: '', name: 'docker-live', detail: '10.0.0.65', host: false, down: false, parent: 'integration:1' },
    { ref: 'integration:2', kind: 'integration', service: 'docker', name: 'docker-live', detail: '10.0.0.65:2375', host: true, down: true },
    { ref: 'container:2:plex', kind: 'container', service: '', name: 'plex', detail: 'ports 32400', host: false, down: true, parent: 'integration:2' },
    { ref: 'integration:3', kind: 'integration', service: 'plex', name: 'Plex', detail: '10.0.0.65:32400', host: false, down: true },
    { ref: 'integration:4', kind: 'integration', service: 'radarr', name: 'Radarr', detail: 'radarr.lan:7878', host: false, down: false },
    { ref: 'container:2:radarr', kind: 'container', service: '', name: 'radarr', detail: '', host: false, down: true, parent: 'integration:2' },
    { ref: 'tile:9', kind: 'tile', service: '', name: 'Wiki', detail: '10.0.0.8', host: false, down: false },
  ],
  relations: [
    { id: 1, child: 'integration:2', parent: 'guest:1:201', origin: 'auto', state: 'on' },
    { id: 2, child: 'integration:3', parent: 'container:2:plex', origin: 'auto', state: 'on' },
    { id: 3, child: 'integration:4', parent: 'container:2:radarr', origin: 'suggested', state: 'suggested' },
  ],
}

vi.mock('../../api/client', async (original) => ({
  ...(await original<typeof import('../../api/client')>()),
  get: vi.fn(async (path: string) => {
    sent.push({ method: 'GET', path })
    if (path === '/inventory/layout') return { positions: { 'tile:9': [500, 300] } }
    return INVENTORY
  }),
  post: vi.fn(async (path: string, body?: unknown) => {
    sent.push({ method: 'POST', path, body })
    return path === '/inventory/refresh' ? INVENTORY : {}
  }),
  put: vi.fn(async (path: string, body?: unknown) => {
    sent.push({ method: 'PUT', path, body })
    return body
  }),
  del: vi.fn(async (path: string) => {
    sent.push({ method: 'DELETE', path })
  }),
}))

const wrap = (node: React.ReactNode) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{node}</QueryClientProvider>)

beforeEach(() => {
  sent.length = 0
})

describe('the shape of it', () => {
  it('puts hosts at the top, what runs on them below, and what stands alone apart', () => {
    const { roots, unplaced } = tree(INVENTORY)
    expect(roots.map((branch) => branch.node.name)).toEqual(['PVE'])
    const guest = roots[0].children[0]
    expect(guest.node.ref).toBe('guest:1:201')
    expect(guest.children[0].node.ref).toBe('integration:2')
    expect(guest.children[0].children.map((one) => one.node.name)).toEqual(['plex', 'radarr'])
    expect(guest.children[0].children[0].children[0].node.name).toBe('Plex')
    // A proposal is not a place yet.
    expect(unplaced.map((node) => node.name)).toEqual(['Radarr', 'Wiki'])
  })

  it('lays the map out in rows by depth, and survives a circle', () => {
    const rows = layered(INVENTORY)
    expect(rows['integration:1'][1]).toBeLessThan(rows['guest:1:201'][1])
    expect(rows['guest:1:201'][1]).toBeLessThan(rows['integration:3'][1])
    expect(rows['integration:3'][0]).toBe(rows['container:2:plex'][0])
    const circle: Inventory = { nodes: INVENTORY.nodes, relations: [...INVENTORY.relations, { id: 9, child: 'guest:1:201', parent: 'integration:3', origin: 'manual', state: 'on' }] }
    expect(() => tree(circle)).not.toThrow()
    expect(() => layered(circle)).not.toThrow()
  })

  it('words what a reboot hits', () => {
    const t = i18n.getFixedT('en')
    expect(factText(t, { fact: 'depends', count: 2, names: ['Plex', 'docker-live'], containers: 3 })).toBe('2 run on it: Plex, docker-live · 3 containers stop with it')
    expect(factText(t, { fact: 'depends', count: 1, names: ['Plex'], containers: 0 })).toBe('Runs on it: Plex')
  })
})

describe('the inventory page', () => {
  it('lists the tree, says yes or no to a proposal and places what stands alone', async () => {
    wrap(<InventorySettings />)
    const rows = await screen.findAllByTestId('inventory-row')
    expect(rows.map((row) => row.textContent?.split('Connection')[0].split('VM or LXC')[0].split('Container')[0].trim())).toEqual(['PVE', 'docker-live', 'docker-live', 'plex', 'Plex', 'radarr'])
    expect(rows[1].textContent).toContain('10.0.0.65')
    expect(screen.getByTestId('inventory-proposed').textContent).toContain('Radarr probably runs on radarr')
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Yes' }))
    })
    expect(sent.some((one) => one.method === 'POST' && one.path === '/relations/3/confirm')).toBe(true)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'No' }))
    })
    expect(sent.some((one) => one.method === 'DELETE' && one.path === '/relations/3')).toBe(true)
    await act(async () => {
      fireEvent.change(screen.getByLabelText('Runs on / needs: Wiki'), { target: { value: 'guest:1:201' } })
    })
    expect(sent.find((one) => one.method === 'POST' && one.path === '/relations')?.body).toEqual({ child: 'tile:9', parent: 'guest:1:201' })
  })

  it('takes a found relation away and asks the engines again', async () => {
    wrap(<InventorySettings />)
    await screen.findAllByTestId('inventory-row')
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Remove Plex' }))
    })
    expect(sent.some((one) => one.method === 'DELETE' && one.path === '/relations/2')).toBe(true)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Look now/ }))
    })
    expect(sent.some((one) => one.method === 'POST' && one.path === '/inventory/refresh')).toBe(true)
  })

  it('shows the map with the kept place of a box, and keeps where one is dragged', async () => {
    const { container } = render(<InventoryMap inventory={INVENTORY} />)
    await waitFor(() => expect(screen.getAllByTestId('inventory-node')).toHaveLength(8))
    const map = screen.getByTestId('inventory-map')
    expect(container.querySelectorAll('line[stroke-dasharray]')).toHaveLength(1)
    const wiki = screen.getAllByTestId('inventory-node').find((node) => node.textContent?.startsWith('Wiki')) as Element
    expect(wiki.getAttribute('transform')).toBe('translate(500 300)')
    map.getBoundingClientRect = () => ({ left: 0, top: 0, width: 800, height: 600, right: 800, bottom: 600, x: 0, y: 0, toJSON: () => ({}) })
    fireEvent.pointerDown(wiki, { clientX: 510, clientY: 310 })
    fireEvent.pointerMove(map, { clientX: 610, clientY: 360 })
    fireEvent.pointerUp(map)
    expect(wiki.getAttribute('transform')).toBe('translate(600 350)')
    const kept = sent.filter((one) => one.method === 'PUT').at(-1)?.body as { positions: Record<string, number[]> }
    expect(kept.positions['tile:9']).toEqual([600, 350])
  })
})

describe('the field on a connection', () => {
  it('shows what it runs on, offers no circle and adds by hand', async () => {
    wrap(<DependsOn subject="integration:2" />)
    const field = await screen.findByTestId('depends-on')
    expect(field.textContent).toMatch(/docker-live\s*· found/)
    const options = [...(screen.getByLabelText('Add …') as HTMLSelectElement).options].map((option) => option.value)
    expect(options).not.toContain('integration:2')
    expect(options).not.toContain('container:2:plex')
    expect(options).not.toContain('integration:3')
    expect(options).toContain('integration:1')
    await act(async () => {
      fireEvent.change(screen.getByLabelText('Add …'), { target: { value: 'integration:1' } })
    })
    expect(sent.find((one) => one.method === 'POST')?.body).toEqual({ child: 'integration:2', parent: 'integration:1' })
  })
})

describe('the cause on a card', () => {
  const VIEW: WidgetView = { id: 3, kind: 'plex.nowplaying', title: 'Plex', icon: '', link: '', renderer: 'list', options: {}, integration_id: 3, integration_name: 'Plex', refresh_seconds: 30 }

  it('says why a failed card failed', () => {
    render(<WidgetCard widget={VIEW} data={{ status: 'unknown', error: 'Connection refused', cause: 'docker-live' }} />)
    expect(screen.getByTestId('card-cause').textContent).toBe('because docker-live is down')
  })
})
