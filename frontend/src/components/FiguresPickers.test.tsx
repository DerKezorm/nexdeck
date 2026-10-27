/**
 * The two ways a tile is chosen for key figures: the picker in its settings,
 * and the library opened from its last tile. Both offer cards that show a
 * number and nothing else.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { FieldSpec } from '../api/types'
import { DEMO_VIEWS } from '../demo/board'
import { useEditedPage } from '../lib/groups'
import type { WidgetView } from '../lib/types'
import { FieldInput } from './FieldInput'
import { WidgetLibrary } from './WidgetLibrary'

const PIHOLE = {
  kind: 'pihole', label: 'Pi-hole', category: 'network', description: '', icon: 'pi-hole', beta: false, docs_url: '',
  needs_integration: false, bars_widgets: [], fields: [],
  widgets: [
    { kind: 'pihole.stats', label: 'Statistics', description: '', renderer: 'value', default_size: [2, 2], min_size: [2, 2], options: [], refresh_seconds: 30, metrics: ['blocked'], client_only: false },
    { kind: 'pihole.top', label: 'Top domains', description: '', renderer: 'list', default_size: [3, 3], min_size: [2, 2], options: [], refresh_seconds: 30, metrics: [], client_only: false },
  ],
}

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  get: vi.fn(async (path: string) => (path === '/adapters' ? [PIHOLE] : path === '/apps' ? [{ id: 1, name: 'Jellyfin', icon: 'jellyfin' }] : [])),
  post: vi.fn(async () => ({ widget: { id: 1 } })),
}))

function library(numbersOnly: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <WidgetLibrary open onClose={() => undefined} pageId={1} onCreated={() => undefined} numbersOnly={numbersOnly} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => useEditedPage.setState({ widgets: [] }))

describe('the library opened from key figures', () => {
  it('offers the cards that show a number, and no lists and no apps', async () => {
    library(true)
    await waitFor(() => expect(screen.getByRole('button', { name: /Statistics/ })).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /Top domains/ })).toBeNull()
    expect(screen.queryByText('Jellyfin')).toBeNull()
    expect(screen.getByText('A tile for key figures')).toBeInTheDocument()
  })

  it('offers everything when opened as usual', async () => {
    library(false)
    await waitFor(() => expect(screen.getByRole('button', { name: /Top domains/ })).toBeInTheDocument())
    expect(screen.getByText('Jellyfin')).toBeInTheDocument()
  })
})

describe('the picker in the settings of key figures', () => {
  const view = (id: number, title: string, renderer: string, extra: Partial<WidgetView> = {}) =>
    ({ ...DEMO_VIEWS[0], id, title, renderer, kind: `demo.${renderer}`, options: {}, ...extra }) as WidgetView
  const spec = (helper: string) => ({ name: 'cards', label: 'Tiles', type: 'cards', required: false, secret: false, default: [], help: '', placeholder: '', options: [], helper }) as FieldSpec

  it('lists the number cards of the page only', () => {
    useEditedPage.setState({ widgets: [view(1, 'CPU', 'stats'), view(2, 'Top domains', 'list'), view(3, 'Clock', 'clock', { client_only: true }), view(4, 'Wall', 'figures', { kind: 'core.figures' })] })
    render(<FieldInput spec={spec('numbers')} value={[]} onChange={() => undefined} />)
    expect(screen.getByRole('checkbox', { name: 'CPU' })).toBeInTheDocument()
    expect(screen.getAllByRole('checkbox')).toHaveLength(1)
  })

  it('karten7 ac8 lists a card of blocks that names its main value, and none without one', () => {
    useEditedPage.setState({
      widgets: [view(1, 'With main', 'builder', { number_card: true }), view(2, 'Without main', 'builder', { number_card: false }), view(3, 'Unknown', 'builder'), view(4, 'Offline', 'builder', { number_card: true, client_only: true })],
    })
    render(<FieldInput spec={spec('numbers')} value={[]} onChange={() => undefined} />)
    expect(screen.getByRole('checkbox', { name: 'With main' })).toBeInTheDocument()
    expect(screen.getAllByRole('checkbox')).toHaveLength(1)
  })

  it('lists every card that is no holder for a group', () => {
    useEditedPage.setState({ widgets: [view(1, 'CPU', 'stats'), view(2, 'Top domains', 'list'), view(4, 'Wall', 'figures', { kind: 'core.figures' })] })
    render(<FieldInput spec={spec('')} value={[]} onChange={() => undefined} />)
    expect(screen.getAllByRole('checkbox')).toHaveLength(2)
  })
})
