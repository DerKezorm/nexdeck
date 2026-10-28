/**
 * What the bar says when a shortcut has been typed and nothing else yet.
 *
 * ⚠️ `!y` on its own produced "nothing matches", which reads as "that
 * shortcut does not exist". It exists; it is waiting for a word. A wrong
 * message here makes a working feature look broken.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { WidgetData, WidgetView } from '../lib/types'
import { CommandPalette } from './CommandPalette'

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

function show(widgets: WidgetView[] = [], data: Record<number, WidgetData> = {}) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <CommandPalette open onClose={vi.fn()} boards={[]} widgets={widgets} data={data} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('CommandPalette', () => {
  beforeEach(() => {
    settings.value = TARGETS
    vi.stubGlobal('open', () => null)
  })

  it('opens with the words a search from the address bar brought along', async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <CommandPalette open onClose={vi.fn()} boards={[]} widgets={[]} initial="kitchen clock" />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(screen.getByRole('textbox')).toHaveValue('kitchen clock')
    // The words go to the search targets at once, as if typed.
    expect(await screen.findAllByText('kitchen clock')).not.toHaveLength(0)
  })

  it('says which target it is waiting on, not that nothing matches', async () => {
    show()
    await userEvent.type(screen.getByRole('textbox'), '!y')
    await waitFor(() => expect(screen.getByText(/YouTube/)).toBeTruthy())
    expect(screen.queryByText(/Nothing matches|Nichts passt/i)).toBeNull()
  })

  it('offers the search once a word is typed', async () => {
    show()
    await userEvent.type(screen.getByRole('textbox'), '!y cats')
    await waitFor(() => expect(screen.getByRole('option', { name: /cats/ })).toBeTruthy())
  })

  it('treats a shortcut nobody has as ordinary words', async () => {
    show()
    await userEvent.type(screen.getByRole('textbox'), '!zz')
    // pickTarget leaves an unknown shortcut in the query, so it is searched
    // for rather than swallowed. Nothing is waiting, so no logo row appears.
    await waitFor(() => expect(screen.getAllByRole('option').length).toBeGreaterThan(0))
    expect(screen.queryByText(/type what to search for|Suchbegriff eingeben/i)).toBeNull()
  })

  it('says nothing matches for ordinary text that finds nothing', async () => {
    show()
    await userEvent.type(screen.getByRole('textbox'), 'zzzqqq')
    // Plain words are a search, so the way out is offered rather than nothing.
    await waitFor(() => expect(screen.getAllByRole('option').length).toBeGreaterThan(0))
  })

  it('finds the tile of an own integration by its name and opens its address (KARTEN-4 AC-4)', async () => {
    settings.value = { enabled: false, targets: [] }
    const open = vi.fn(() => null)
    vi.stubGlobal('open', open)
    const tile: WidgetView = {
      id: 7, kind: 'core.app', title: 'Team wiki', icon: 'wikijs', link: 'http://wiki.example.com:3000', renderer: 'app', options: {}, integration_id: 4, refresh_seconds: null,
    }
    show([tile])
    await userEvent.type(screen.getByRole('textbox'), 'Team wiki{Enter}')
    expect(open).toHaveBeenCalledWith('http://wiki.example.com:3000', '_blank', 'noopener,noreferrer')
  })

  describe('app tiles without a link of their own', () => {
    const tile = (id: number, link: string, service_link: string): WidgetView => ({
      id, kind: 'core.app', title: 'Plex', icon: '', link, service_link, renderer: '', options: {}, integration_id: 1, refresh_seconds: null,
    })

    it('offers a tile bound to a connection and opens the address of the connection', async () => {
      const opened: string[] = []
      vi.stubGlobal('open', (url: string) => {
        opened.push(url)
        return null
      })
      show([tile(1, '', 'https://plex.example.com')])
      await userEvent.type(screen.getByRole('textbox'), 'Plex{Enter}')
      expect(opened).toEqual(['https://plex.example.com'])
    })

    it('prefers the link of the tile, and leaves out a tile with no web address at all', async () => {
      const opened: string[] = []
      vi.stubGlobal('open', (url: string) => {
        opened.push(url)
        return null
      })
      show([tile(1, 'https://mine.example.com', 'https://plex.example.com'), { ...tile(2, '', 'javascript:alert(1)'), title: 'Odd' }])
      await userEvent.type(screen.getByRole('textbox'), 'Odd')
      expect(screen.queryAllByRole('option').filter((row) => /^Odd\s*Open/.test(row.textContent ?? ''))).toEqual([])
      await userEvent.clear(screen.getByRole('textbox'))
      await userEvent.type(screen.getByRole('textbox'), 'Plex{Enter}')
      expect(opened).toEqual(['https://mine.example.com'])
    })
  })

  describe('links on the board (issue #46)', () => {
    const card = (id: number, kind: string, title: string): WidgetView => ({
      id, kind, title, icon: '', link: '', renderer: '', options: {}, integration_id: null, refresh_seconds: null,
    })
    const WIDGETS = [
      card(1, 'core.bookmarks', 'Docs'),
      card(2, 'core.button', 'Router'),
      card(3, 'linkding.recent', 'Saved'),
      card(4, 'radarr.queue', 'Downloads'),
      card(5, 'readeck.recent', 'Reading list'),
    ]
    const DATA: Record<number, WidgetData> = {
      1: { status: 'ok', items: [
        { title: 'Backup guide', url: 'https://docs.example.com/backup', icon: '' },
        { title: 'Sneaky', url: 'javascript:alert(1)', icon: '' },
      ] },
      2: { status: 'ok', meta: { kind: 'link', where: 'https://router.example.com', new_tab: true } },
      3: { status: 'ok', items: [{ title: 'DNS cheat sheet', url: 'https://wiki.example.org/dns' }] },
      4: { status: 'ok', items: [{ title: 'Some movie', url: 'https://radarr.example.com/movie/1' }] },
      5: { status: 'ok', items: [
        { title: 'ZFS on a small machine', url: 'https://readeck.example.com/bookmarks/a2' },
        { title: 'Planted', url: 'javascript:alert(2)' },
      ] },
    }
    let opened: string[]

    beforeEach(() => {
      settings.value = { enabled: false, targets: [] }
      opened = []
      vi.stubGlobal('open', (url: string) => {
        opened.push(url)
        return null
      })
    })

    it('finds a bookmark by its exact title and opens it on Enter', async () => {
      show(WIDGETS, DATA)
      await userEvent.type(screen.getByRole('textbox'), 'Backup guide{Enter}')
      expect(opened).toEqual(['https://docs.example.com/backup'])
    })

    it('finds a bookmark by its address, and marks it as a link', async () => {
      show(WIDGETS, DATA)
      await userEvent.type(screen.getByRole('textbox'), 'docs.example.com/backup')
      const row = await screen.findByRole('option', { name: /Backup guide/ })
      expect(row.textContent).toMatch(/Link/)
    })

    it('offers a button that leads to an address', async () => {
      show(WIDGETS, DATA)
      await userEvent.type(screen.getByRole('textbox'), 'Router{Enter}')
      expect(opened).toEqual(['https://router.example.com'])
    })

    it('offers what a bookmark service card has loaded', async () => {
      show(WIDGETS, DATA)
      await userEvent.type(screen.getByRole('textbox'), 'cheat sheet')
      expect(await screen.findByRole('option', { name: /DNS cheat sheet/ })).toBeTruthy()
    })

    it('offers what a Readeck card has loaded, and not an address nexdeck will not open', async () => {
      show(WIDGETS, DATA)
      const box = screen.getByRole('textbox')
      await userEvent.type(box, 'small machine{Enter}')
      expect(opened).toEqual(['https://readeck.example.com/bookmarks/a2'])
      await userEvent.clear(box)
      await userEvent.type(box, 'Planted')
      await waitFor(() => expect(screen.getByText(/Nothing matches|Nichts passt/i)).toBeTruthy())
    })

    it('leaves out rows of other lists and addresses nexdeck will not open', async () => {
      show(WIDGETS, DATA)
      const box = screen.getByRole('textbox')
      await userEvent.type(box, 'Some movie')
      await waitFor(() => expect(screen.getByText(/Nothing matches|Nichts passt/i)).toBeTruthy())
      await userEvent.clear(box)
      await userEvent.type(box, 'Sneaky')
      await waitFor(() => expect(screen.getByText(/Nothing matches|Nichts passt/i)).toBeTruthy())
    })
  })
})
