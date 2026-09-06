/**
 * The search card, held against the ways it could quietly do the wrong thing.
 *
 * It shares its targets and its `!shortcut` with the command palette, so the
 * tests here are about the card's own decisions: which target Enter takes,
 * that a word is encoded before it goes into an address, and that an
 * unconfigured card says so instead of looking broken.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { SearchCard } from './SearchCard'
import type { WidgetData, WidgetView } from '../lib/types'

const settings = vi.hoisted(() => ({ value: {} as unknown }))
vi.mock('../api/client', () => ({
  get: vi.fn(async () => settings.value),
  mediaUrl: () => '',
}))

const TARGETS = {
  enabled: true,
  targets: [
    { name: 'DuckDuckGo', url: 'https://duckduckgo.com/?q={query}', prefix: 'd', icon: '' },
    { name: 'YouTube', url: 'https://www.youtube.com/results?search_query={query}', prefix: 'y', icon: '' },
  ],
}

const widget = { id: 1, kind: 'core.search', title: 'Search', renderer: 'search' } as unknown as WidgetView

function show(meta: Record<string, unknown> = {}) {
  const data = { meta } as unknown as WidgetData
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <SearchCard widget={widget} data={data} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SearchCard', () => {
  let opened: string[] = []

  beforeEach(() => {
    opened = []
    settings.value = TARGETS
    vi.stubGlobal('open', (url: string) => {
      opened.push(url)
      return null
    })
  })

  it('sends the words to the first target when nothing else is named', async () => {
    show()
    const field = await screen.findByRole('searchbox')
    await userEvent.type(field, 'reverse proxy{Enter}')
    expect(opened).toEqual(['https://duckduckgo.com/?q=reverse%20proxy'])
  })

  it('takes the target named in the settings', async () => {
    show({ target: 'y' })
    const field = await screen.findByRole('searchbox')
    await userEvent.type(field, 'homelab{Enter}')
    expect(opened).toEqual(['https://www.youtube.com/results?search_query=homelab'])
  })

  it('lets a shortcut in the field win over the setting', async () => {
    show({ target: 'd' })
    const field = await screen.findByRole('searchbox')
    await userEvent.type(field, '!y cats{Enter}')
    expect(opened).toEqual(['https://www.youtube.com/results?search_query=cats'])
  })

  it('encodes the words, so an ampersand cannot add a parameter', async () => {
    show()
    const field = await screen.findByRole('searchbox')
    await userEvent.type(field, 'a&b=c{Enter}')
    expect(opened).toEqual(['https://duckduckgo.com/?q=a%26b%3Dc'])
  })

  it('does nothing on an empty field', async () => {
    show()
    const field = await screen.findByRole('searchbox')
    await userEvent.type(field, '   {Enter}')
    expect(opened).toEqual([])
  })

  it('opens in a new tab without an opener', async () => {
    show()
    const seen: unknown[][] = []
    vi.stubGlobal('open', (...args: unknown[]) => {
      seen.push(args)
      return null
    })
    await userEvent.type(await screen.findByRole('searchbox'), 'x{Enter}')
    expect(seen[0][1]).toBe('_blank')
    expect(seen[0][2]).toBe('noopener,noreferrer')
  })

  it('stays in the tab when the card says so', async () => {
    const assign = vi.fn()
    vi.stubGlobal('location', { assign })
    show({ new_tab: false })
    await userEvent.type(await screen.findByRole('searchbox'), 'x{Enter}')
    expect(assign).toHaveBeenCalledWith('https://duckduckgo.com/?q=x')
    expect(opened).toEqual([])
  })

  it('offers a button per target and searches with the one that is pressed', async () => {
    show()
    const field = await screen.findByRole('searchbox')
    await userEvent.type(field, 'nas')
    await userEvent.click(screen.getByRole('button', { name: /YouTube/ }))
    expect(opened).toEqual(['https://www.youtube.com/results?search_query=nas'])
  })

  it('can leave the shortcuts off, for somebody with a dozen targets', async () => {
    show({ show_shortcuts: false })
    const button = await screen.findByRole('button', { name: /YouTube/ })
    expect(button.textContent).not.toContain('!y')
    expect(button.textContent).toContain('YouTube')
  })

  it('can leave the whole row off', async () => {
    show({ show_targets: false })
    await screen.findByRole('searchbox')
    expect(screen.queryByRole('button', { name: /YouTube/ })).toBeNull()
  })

  it('writes the shortcut on the button, where somebody would look for it', async () => {
    // A shortcut nobody can see is a shortcut nobody uses: the card is the
    // only place that knows which letter belongs to which target.
    show()
    expect((await screen.findByRole('button', { name: /YouTube/ })).textContent).toContain('!y')
    expect(screen.getByRole('button', { name: /DuckDuckGo/ }).textContent).toContain('!d')
  })

  it('says it is not set up instead of showing an empty field', async () => {
    settings.value = { enabled: false, targets: [] }
    show()
    // A field that goes nowhere reads as broken; this says what is missing.
    await waitFor(() => expect(screen.getByText(/No search target|kein Suchziel/i)).toBeTruthy())
    expect(screen.queryByRole('searchbox')).toBeNull()
  })

  it('says the same when the search is on but nothing is configured', async () => {
    settings.value = { enabled: true, targets: [] }
    show()
    await waitFor(() => expect(screen.getByText(/No search target|kein Suchziel/i)).toBeTruthy())
  })

  it('cannot be typed in while the board is being edited', async () => {
    const data = { meta: {} } as unknown as WidgetData
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <SearchCard widget={widget} data={data} editing />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const field = (await screen.findByRole('searchbox')) as HTMLInputElement
    expect(field.disabled).toBe(true)
  })
})
