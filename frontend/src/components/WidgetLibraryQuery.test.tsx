/**
 * "Build a card" on a connection without one opens the library already
 * searching for its service, so the cards it can carry are what is shown.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { WidgetLibrary } from './WidgetLibrary'

function adapter(kind: string, label: string, widget: string) {
  return {
    kind, label, category: 'downloads', description: '', icon: kind, beta: false, docs_url: '', needs_integration: true, fields: [],
    widgets: [{ kind: `${kind}.one`, label: widget, description: '', renderer: 'list', default_size: [4, 3], min_size: [3, 2], options: [] }],
  }
}

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  get: vi.fn(async (path: string) => (path === '/adapters' ? [adapter('sonarr', 'Sonarr', 'Calendar'), adapter('radarr', 'Radarr', 'Queue')] : [])),
  post: vi.fn(async () => ({ widget: { id: 1 } })),
}))

function show(initialQuery?: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <WidgetLibrary open onClose={() => undefined} pageId={1} onCreated={() => undefined} initialQuery={initialQuery} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('the library opened for one service', () => {
  it('starts with its name in the search and shows only its cards', async () => {
    show('Sonarr')
    expect(await screen.findByRole('button', { name: /Calendar/ })).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Search widgets…' })).toHaveValue('Sonarr')
    expect(screen.queryByRole('button', { name: /Queue/ })).toBeNull()
  })

  it('starts empty without one, as it always did', async () => {
    show()
    expect(await screen.findByRole('button', { name: /Queue/ })).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Search widgets…' })).toHaveValue('')
  })
})
