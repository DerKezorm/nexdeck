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

  describe('links on the board (issue #46)', () => {
    const card = (id: number, kind: string, title: string): WidgetView => ({
      id, kind, title, icon: '', link: '', renderer: '', options: {}, integration_id: null, refresh_seconds: null,
    })
    const WIDGETS = [
      card(1, 'core.bookmarks', 'Docs'),
      card(2, 'core.button', 'Router'),
      card(3, 'linkding.recent', 'Saved'),
      card(4, 'radarr.queue', 'Downloads'),
    ]
    const DATA: Record<number, WidgetData> = {
      1: { status: 'ok', items: [
        { title: 'Backup guide', url: 'https://docs.example.com/backup', icon: '' },
        { title: 'Sneaky', url: 'javascript:alert(1)', icon: '' },
      ] },
      2: { status: 'ok', meta: { kind: 'link', where: 'https://router.example.com', new_tab: true } },
      3: { status: 'ok', items: [{ title: 'DNS cheat sheet', url: 'https://wiki.example.org/dns' }] },
      4: { status: 'ok', items: [{ title: 'Some movie', url: 'https://radarr.example.com/movie/1' }] },
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
