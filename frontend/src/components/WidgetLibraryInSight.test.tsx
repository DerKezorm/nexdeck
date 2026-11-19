/**
 * Issue #76: with two TrueNAS connections a click asks which one, and the
 * question stands above the list. Somebody who scrolled down to TrueNAS saw
 * nothing happen. The question, and any refusal, are brought into sight.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { WidgetLibrary } from './WidgetLibrary'

const TRUENAS = {
  kind: 'truenas', label: 'TrueNAS', category: 'storage', description: '', icon: 'truenas', beta: false, docs_url: '',
  needs_integration: true, optional_integration: false, bars_widgets: false, fields: [],
  widgets: [{ kind: 'truenas.smb_sessions', label: 'SMB sessions', description: '', renderer: 'list', default_size: [3, 2], min_size: [2, 2], options: [] }],
}

const state = vi.hoisted(() => ({ integrations: [] as { id: number; kind: string; name: string }[], refuse: false }))
vi.mock('../api/client', () => {
  class ApiError extends Error {}
  return {
    ApiError,
    get: vi.fn(async (path: string) => (path === '/adapters' ? [TRUENAS] : path === '/integrations' ? state.integrations : [])),
    post: vi.fn(async () => {
      if (state.refuse) throw new ApiError('That card cannot be added here.')
      return { widget: { id: 1 } }
    }),
  }
})

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

/** The elements that were scrolled into sight, in order. */
let scrolled: Element[] = []

beforeEach(() => {
  scrolled = []
  state.refuse = false
  Element.prototype.scrollIntoView = function (this: Element) {
    scrolled.push(this)
  }
})

afterEach(() => {
  delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView
})

async function clickTheCard() {
  await screen.findByRole('button', { name: /SMB sessions/ })
  // The connections have to be there before the press.
  await new Promise((resolve) => setTimeout(resolve, 20))
  await userEvent.click(screen.getByRole('button', { name: /SMB sessions/ }))
}

describe('what the library asks after a click', () => {
  it('brings the choice of connection into sight', async () => {
    state.integrations = [{ id: 1, kind: 'truenas', name: 'NAS one' }, { id: 2, kind: 'truenas', name: 'NAS two' }]
    show()
    expect(scrolled).toEqual([])
    await clickTheCard()
    const question = await screen.findByText('Which TrueNAS should this widget use?')
    await waitFor(() => expect(scrolled.some((element) => element.contains(question))).toBe(true))
  })

  it('brings a refusal into sight', async () => {
    state.integrations = [{ id: 1, kind: 'truenas', name: 'NAS one' }]
    state.refuse = true
    show()
    await clickTheCard()
    const refusal = await screen.findByRole('alert')
    expect(refusal.textContent).toBe('That card cannot be added here.')
    await waitFor(() => expect(scrolled.some((element) => element.contains(refusal))).toBe(true))
  })
})
