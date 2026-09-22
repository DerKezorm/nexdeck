/**
 * The template picker: a slot offers every connection of any service it
 * names, a slot left out takes its cards and the sketch shows it, and what
 * is sent carries the board's words in the language of whoever makes it.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { TemplatePicker, type TemplateSummary } from './TemplatePicker'

const MEDIA: TemplateSummary = {
  id: 'media', name: 'Media', description: 'What is playing.', icon: 'clapperboard', columns: 24, pages: 1, cards: 3,
  slots: [
    { name: 'Media server', kinds: [{ kind: 'jellyfin', label: 'Jellyfin', icon: 'jellyfin' }, { kind: 'plex', label: 'Plex', icon: 'plex' }], cards: 2 },
    { name: 'Downloads', kinds: [{ kind: 'sabnzbd', label: 'SABnzbd', icon: 'sabnzbd' }], cards: 1 },
  ],
  sketch: [
    { slot: 'Media server', at: [0, 0, 12, 3] },
    { slot: 'Downloads', at: [12, 0, 12, 3] },
    { slot: 'Media server', at: [0, 3, 24, 3] },
  ],
  words: ['Media', 'Now playing'],
}

const sent = vi.hoisted(() => ({ body: null as null | Record<string, unknown>, path: '' }))
vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  get: vi.fn(async (path: string) => {
    if (path === '/templates') return [MEDIA]
    return { ...MEDIA, choices: { 'Media server': [{ id: 4, name: 'Plex at home', kind: 'plex', demo: false }, { id: 5, name: 'Jellyfin', kind: 'jellyfin', demo: true }], Downloads: [] } }
  }),
  post: vi.fn(async (path: string, body: Record<string, unknown>) => {
    sent.path = path
    sent.body = body
    return { slug: 'media' }
  }),
}))

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <TemplatePicker />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  sent.body = null
  sent.path = ''
})

describe('the template picker', () => {
  it('offers every connection of any service a slot names, and leaving out when there is none', async () => {
    const view = show()
    await userEvent.click(await screen.findByRole('button', { name: /Media/ }))
    const server = await screen.findByLabelText(/Media server/)
    expect(within(server).getAllByRole('option').map((option) => option.textContent)).toEqual(['Plex at home', 'Jellyfin (demo)', 'Leave out (2 cards)'])
    // The first that fits is taken, so the usual case is one press.
    expect((server as HTMLSelectElement).value).toBe('4')
    const downloads = screen.getByLabelText(/Downloads/) as HTMLSelectElement
    expect(downloads.value).toBe('')
    expect(screen.getByText(/No connection for SABnzbd yet/)).toBeTruthy()
    // Two of three cards come out, and the sketch draws two.
    expect(screen.getByText('2 cards on 24 columns.')).toBeTruthy()
    const sketches = view.container.querySelectorAll('svg')
    expect(sketches[sketches.length - 1].querySelectorAll('rect').length).toBe(2)
  })

  it('makes the board with the slots as chosen and the words of this language', async () => {
    show()
    await userEvent.click(await screen.findByRole('button', { name: /Media/ }))
    await userEvent.selectOptions(await screen.findByLabelText(/Media server/), '5')
    const name = screen.getByLabelText('Name of the new board')
    await userEvent.clear(name)
    await userEvent.type(name, 'Cinema')
    await userEvent.click(screen.getByRole('button', { name: 'Create the board' }))
    await waitFor(() => expect(sent.body).not.toBeNull())
    expect(sent.path).toBe('/templates/media')
    expect(sent.body).toEqual({ name: 'Cinema', slots: { 'Media server': 5, Downloads: null }, texts: { Media: 'Media', 'Now playing': 'Now playing' } })
  })

  it('makes nothing when every card would be left out', async () => {
    show()
    await userEvent.click(await screen.findByRole('button', { name: /Media/ }))
    await userEvent.selectOptions(await screen.findByLabelText(/Media server/), '')
    expect(screen.getByRole('button', { name: 'Create the board' })).toHaveProperty('disabled', true)
  })
})
