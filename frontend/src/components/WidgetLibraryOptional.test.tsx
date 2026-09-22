/**
 * A card that can do without a connection, and takes one when there is:
 * GitHub with a token has a hundred times the requests of GitHub without.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { WidgetLibrary } from './WidgetLibrary'

const GITHUB = {
  kind: 'github', label: 'GitHub', category: 'feeds', description: '', icon: 'github', beta: false, docs_url: '',
  needs_integration: false, optional_integration: true, bars_widgets: [], fields: [],
  widgets: [{ kind: 'github.runs', label: 'Workflow runs', description: '', renderer: 'list', default_size: [4, 3], min_size: [3, 2], options: [] }],
}

const state = vi.hoisted(() => ({ integrations: [] as { id: number; kind: string; name: string }[], posted: [] as Record<string, unknown>[] }))
vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  get: vi.fn(async (path: string) => (path === '/adapters' ? [GITHUB] : state.integrations)),
  post: vi.fn(async (_path: string, body: Record<string, unknown>) => {
    state.posted.push(body)
    return { widget: { id: 1 } }
  }),
}))

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <WidgetLibrary open onClose={() => undefined} pageId={1} onCreated={() => undefined} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  state.posted = []
})

describe('a card with an optional connection', () => {
  it('takes the first connection there is', async () => {
    state.integrations = [{ id: 7, kind: 'github', name: 'GitHub with a token' }, { id: 8, kind: 'sonarr', name: 'Sonarr' }]
    show()
    await waitFor(() => expect(screen.getByRole('button', { name: /Workflow runs/ })).toBeTruthy())
    // The connections have to be there before the press for the card to take one.
    await new Promise((resolve) => setTimeout(resolve, 20))
    await userEvent.click(screen.getByRole('button', { name: /Workflow runs/ }))
    await waitFor(() => expect(state.posted).toHaveLength(1))
    expect(state.posted[0].integration_id).toBe(7)
  })

  it('is made without one when there is none, and asks nothing', async () => {
    state.integrations = [{ id: 8, kind: 'sonarr', name: 'Sonarr' }]
    show()
    await userEvent.click(await screen.findByRole('button', { name: /Workflow runs/ }))
    await waitFor(() => expect(state.posted).toHaveLength(1))
    expect(state.posted[0].integration_id).toBeNull()
  })
})
