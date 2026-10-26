/**
 * KARTEN-4 AC-4: a connection of an own kind is offered as an app tile with its logo and its address, and the tile
 * gets the dot that asks the check path of the description.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { WidgetLibrary } from './WidgetLibrary'

const CORE = {
  kind: 'core', label: 'Basics', category: 'basics', description: '', icon: 'lucide:layout-dashboard', beta: false, docs_url: '',
  needs_integration: false, optional_integration: false, bars_widgets: [], fields: [],
  widgets: [{ kind: 'core.app', label: 'App tile', description: '', renderer: 'app', default_size: [2, 1], min_size: [1, 1], options: [{ name: 'check', label: 'Check reachability', type: 'bool', default: true }] }],
}

const CONNECTIONS = [
  { id: 4, kind: 'custom:wiki-x', label: 'Wiki.js', icon: 'wikijs', name: 'Team wiki', enabled: true, missing: false, config: { url: 'https://wiki.example.com', insecure: true } },
  { id: 5, kind: 'custom:gone', label: 'gone', icon: '', name: 'Lost', enabled: true, missing: true, config: {} },
  { id: 6, kind: 'sonarr', label: 'Sonarr', icon: 'sonarr', name: 'Series', enabled: true, config: {} },
]

const world = vi.hoisted(() => ({ posted: [] as { path: string; body: Record<string, unknown> }[], put: [] as { path: string; body: Record<string, unknown> }[] }))
vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  get: vi.fn(async (path: string) => (path === '/adapters' ? [CORE] : path === '/integrations' ? CONNECTIONS : path === '/apps' ? [] : { cards: [] })),
  post: vi.fn(async (path: string, body: Record<string, unknown>) => {
    world.posted.push({ path, body })
    return { widget: { id: 31 } }
  }),
  put: vi.fn(async (path: string, body: Record<string, unknown>) => {
    world.put.push({ path, body })
    return {}
  }),
}))

function show(onCreated = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <WidgetLibrary open onClose={() => undefined} pageId={1} onCreated={onCreated} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return onCreated
}

beforeEach(() => {
  world.posted = []
  world.put = []
})

describe('connections of an own kind in the library', () => {
  it('karten4 ac4: only the ones whose description is there are offered, under their own name', async () => {
    show()
    const section = await screen.findByTestId('library-own-connections')
    expect(section.textContent).toContain('Team wiki')
    expect(section.textContent).not.toContain('Lost')
    expect(section.textContent).not.toContain('Series')
  })

  it('karten4 ac4: a press places an app tile that follows the connection, with its name and logo, and asks it for the dot', async () => {
    const created = show()
    await userEvent.click(await screen.findByRole('button', { name: /Team wiki/ }))
    await waitFor(() => expect(created).toHaveBeenCalledWith(31))
    expect(world.posted[0].path).toBe('/pages/1/widgets')
    expect(world.posted[0].body).toMatchObject({ kind: 'core.app', title: 'Team wiki', icon: 'wikijs', integration_id: 4, options: { check: true } })
    expect(world.put[0].path).toBe('/widgets/31/health')
    expect(world.put[0].body).toMatchObject({ kind: 'http', target: '', enabled: true, insecure: true })
  })

  it('karten4 ac4: the search narrows them like the rest of the library', async () => {
    show()
    await screen.findByTestId('library-own-connections')
    await userEvent.type(screen.getByRole('textbox'), 'zzz')
    await waitFor(() => expect(screen.queryByTestId('library-own-connections')).toBeNull())
  })
})
