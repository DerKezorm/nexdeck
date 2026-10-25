/**
 * What runs on what (roadmap M5): the list with its proposals, the map, the
 * field on a connection, and the cause a card names.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react'
import i18n from 'i18next'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { factText } from '../../lib/assistant'
import { columns, tree, type Inventory } from '../../lib/inventory'
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
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  )

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

  it('puts each machine in a column with what runs in its containers, and folds a tile into its connection', () => {
    const { columns: machines, loose } = columns(INVENTORY)
    expect(machines.map((one) => one.host.name)).toEqual(['docker-live', 'PVE'])
    const engine = machines[0]
    expect(engine.slots.map((slot) => [slot.node.name, slot.services.map((one) => [one.node.name, one.proposed])])).toEqual([
      ['plex', [['Plex', false]]],
      ['radarr', [['Radarr', true]]],
    ])
    expect(machines[1].slots[0].services.map((one) => one.node.ref)).toEqual(['integration:2'])
    expect(loose.map((one) => one.node.name)).toEqual(['Wiki'])
    const folded = columns({ ...INVENTORY, relations: [...INVENTORY.relations, { id: 8, child: 'tile:9', parent: 'integration:3', origin: 'auto', state: 'on' }] })
    expect(folded.loose).toEqual([])
    expect(folded.columns.map((one) => one.host.name)).toEqual(['docker-live', 'PVE'])
    expect(folded.columns[0].slots[0].services[0]).toMatchObject({ node: { name: 'Plex' }, tiles: 1 })
    const circle: Inventory = { nodes: INVENTORY.nodes, relations: [...INVENTORY.relations, { id: 9, child: 'guest:1:201', parent: 'integration:3', origin: 'manual', state: 'on' }] }
    expect(() => tree(circle)).not.toThrow()
    expect(() => columns(circle)).not.toThrow()
  })

  it('keeps a container nothing runs in out of its column until asked', () => {
    const empty: Inventory = { ...INVENTORY, nodes: [...INVENTORY.nodes, { ref: 'container:2:redis', kind: 'container', service: '', name: 'redis', detail: '', host: false, down: false, parent: 'integration:2' }] }
    const engine = columns(empty).columns[0]
    expect(engine.slots.map((slot) => slot.node.name)).toEqual(['plex', 'radarr'])
    expect(engine.empty.map((slot) => slot.node.name)).toEqual(['redis'])
  })

  it('words what a reboot hits', () => {
    const t = i18n.getFixedT('en')
    expect(factText(t, { fact: 'depends', count: 2, names: ['Plex', 'docker-live'], containers: 3 })).toBe('2 run on it: Plex, docker-live · 3 containers stop with it')
    expect(factText(t, { fact: 'depends', count: 1, names: ['Plex'], containers: 0 })).toBe('Runs on it: Plex')
  })
})

describe('the inventory page', () => {
  it('says which proposal is an app tile, and keeps the proposals for one service together', async () => {
    // ⚠️ Seen on 25.10.2026: "Jellyfin probably runs on jellyfin" twice, once for the connection and once for its tile.
    INVENTORY.relations.push({ id: 4, child: 'tile:9', parent: 'integration:1', origin: 'suggested', state: 'suggested' })
    try {
      wrap(<InventorySettings />)
      const proposed = await screen.findByTestId('inventory-proposed')
      expect(proposed.textContent).toMatch(/radarr on docker-live.*Wiki \(app tile\) probably runs on PVE/)
    } finally {
      INVENTORY.relations.pop()
    }
  })

  it('lists the tree, says yes or no to a proposal and places what stands alone', async () => {
    wrap(<InventorySettings />)
    const rows = await screen.findAllByTestId('inventory-row')
    expect(rows.map((row) => row.textContent?.split('Connection')[0].split('VM or LXC')[0].split('Container')[0].trim())).toEqual(['PVE', 'docker-live', 'docker-live', 'plex', 'Plex', 'radarr'])
    expect(rows[1].textContent).toContain('10.0.0.65')
    expect(screen.getByTestId('inventory-proposed').textContent).toContain('Radarr probably runs in the container radarr on docker-live')
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

  it('draws the map as columns, names leading to their diagnosis', () => {
    render(<MemoryRouter><InventoryMap inventory={INVENTORY} /></MemoryRouter>)
    const machines = screen.getAllByTestId('inventory-column')
    expect(machines.map((one) => one.querySelector('h3')?.textContent)).toEqual(['docker-live', 'PVE'])
    const proposed = screen.getAllByTestId('inventory-service').filter((one) => one.dataset.proposed)
    expect(proposed.map((one) => one.textContent)).toEqual([expect.stringContaining('Radarr')])
    expect(screen.getByRole('link', { name: 'Plex' }).getAttribute('href')).toBe('/diagnosis?ref=integration%3A3')
    expect(screen.getByTestId('inventory-loose').textContent).toContain('Wiki')
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
