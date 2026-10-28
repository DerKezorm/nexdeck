/**
 * The overview of the Card shop: tiles, search, filters, sorting, "No cards match", a thousand entries, the phone
 * (KARTEN-14 AC-3, AC-4, EC-7 to EC-10).
 */
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { entry, githubWasAsked, renderWith, reset, STATE_ON, stub } from '../../../test/shopWorld'
import { ShopTab } from './ShopTab'

const QBIT = { kind: 'qbittorrent', label: 'qBittorrent', icon: 'qbittorrent' }

const speed = entry({
  id: '7/speed',
  author_id: '7',
  slug: 'speed',
  name: 'Download speed',
  description: 'The current download speed.',
  author: { id: '7', login: 'otheruser' },
  category: 'downloads',
  requires: [QBIT],
  class: 'buttons',
  thumbs: 40,
  updated_at: '2026-10-25T10:00:00Z',
  fits: false,
  connections: [],
  images: { light: '/api/v1/workshop/entries/7/speed/image/light', dark: '/api/v1/workshop/entries/7/speed/image/dark' },
})
const queue = entry()
const lamp = entry({
  id: '9/lamp',
  author_id: '9',
  slug: 'lamp',
  name: 'Lamp',
  type: 'integration',
  description: 'Switches a lamp.',
  category: 'smart_home',
  requires: [],
  thumbs: 3,
  updated_at: '2026-10-27T10:00:00Z',
  fits: true,
})

/** The names on the tiles, top to bottom. */
const names = () => within(screen.getByRole('list', { name: 'Entries of the Card shop' })).getAllByRole('listitem').map((one) => one.querySelector('.font-medium')?.textContent)

beforeEach(() => {
  localStorage.clear()
  reset([queue, speed, lamp], STATE_ON)
  stub()
})
afterEach(async () => {
  vi.unstubAllGlobals()
  await i18next.changeLanguage('en')
})

describe('the tiles', () => {
  it('karten14 ac3: a tile has the picture over the server, name, author, thumbs, class and what it needs', async () => {
    localStorage.setItem('nexdeck.shop.fits', '0')
    renderWith(<ShopTab />)
    const tile = await screen.findByTestId('shop-tile-7/speed')
    expect(tile.querySelector('img')).toHaveAttribute('src', '/api/v1/workshop/entries/7/speed/image/dark')
    expect(within(tile).getByText('Download speed')).toBeInTheDocument()
    expect(within(tile).getByText('by otheruser')).toBeInTheDocument()
    expect(within(tile).getByRole('img', { name: '40 thumbs up' })).toBeInTheDocument()
    expect(within(tile).getByText('Has buttons')).toBeInTheDocument()
    expect(within(tile).getByText('qBittorrent')).toBeInTheDocument()
    expect(within(tile).getByText('no connection yet')).toBeInTheDocument()
  })

  it('karten14 ac3: the picture is never asked of GitHub: its address is the server\'s', async () => {
    renderWith(<ShopTab />)
    const tile = await screen.findByTestId('shop-tile-123/queue-size')
    const source = tile.querySelector('img')!.getAttribute('src')!
    expect(source.startsWith('/api/v1/workshop/entries/')).toBe(true)
    expect(source).not.toMatch(/github/i)
  })

  it('karten14 ac3: the name is shown in the language of the viewer', async () => {
    await i18next.changeLanguage('de')
    renderWith(<ShopTab />)
    expect(await screen.findByText('Warteschlange')).toBeInTheDocument()
  })

  it('karten14 ac3: a name or a description with markup is text, not markup', async () => {
    reset([entry({ name: '<b>Bold</b><img src=x onerror=alert(1)>', description: '<script>alert(1)</script>' })], STATE_ON)
    renderWith(<ShopTab />)
    expect(await screen.findByText('<b>Bold</b><img src=x onerror=alert(1)>')).toBeInTheDocument()
    expect(document.querySelector('script, b')).toBeNull()
  })
})

describe('search, filters and sorting', () => {
  it('karten14 ec9: "Fits my connections" is on at first, remembered per browser, and filters the list', async () => {
    const first = renderWith(<ShopTab />)
    const box = await screen.findByRole('checkbox', { name: 'Fits my connections' })
    expect(box).toBeChecked()
    expect(names()).toEqual(['Queue size', 'Lamp'])
    await userEvent.click(box)
    expect(names()).toEqual(['Download speed', 'Queue size', 'Lamp'])
    first.unmount()
    renderWith(<ShopTab />)
    expect(await screen.findByRole('checkbox', { name: 'Fits my connections' })).not.toBeChecked()
  })

  it('karten14 ac4: the search narrows the list at once by name, author, description and service', async () => {
    localStorage.setItem('nexdeck.shop.fits', '0')
    renderWith(<ShopTab />)
    const search = await screen.findByRole('textbox', { name: 'Search by name, author or service' })
    await userEvent.type(search, 'otheruser')
    expect(names()).toEqual(['Download speed'])
    await userEvent.clear(search)
    await userEvent.type(search, 'sonarr')
    expect(names()).toEqual(['Queue size'])
    await userEvent.clear(search)
    await userEvent.type(search, 'episodes')
    expect(names()).toEqual(['Queue size'])
  })

  it('karten14 ac4: the filters for category and for cards or integrations narrow the list', async () => {
    localStorage.setItem('nexdeck.shop.fits', '0')
    renderWith(<ShopTab />)
    await screen.findByTestId('shop-list')
    await userEvent.selectOptions(screen.getByDisplayValue('All categories'), 'downloads')
    expect(names()).toEqual(['Download speed'])
    await userEvent.selectOptions(screen.getByDisplayValue('Downloads'), 'all')
    await userEvent.selectOptions(screen.getByDisplayValue('Cards and integrations'), 'integration')
    expect(names()).toEqual(['Lamp'])
  })

  it('karten14 ac4: the list is sorted by thumbs, by newest or by name', async () => {
    localStorage.setItem('nexdeck.shop.fits', '0')
    renderWith(<ShopTab />)
    await screen.findByTestId('shop-list')
    expect(names()).toEqual(['Download speed', 'Queue size', 'Lamp'])
    await userEvent.selectOptions(screen.getByDisplayValue('Most thumbs'), 'new')
    expect(names()).toEqual(['Lamp', 'Download speed', 'Queue size'])
    await userEvent.selectOptions(screen.getByDisplayValue('Newest'), 'name')
    expect(names()).toEqual(['Download speed', 'Lamp', 'Queue size'])
  })

  it('karten14 ac3: an entry that left the shop is not listed unless it is installed here', async () => {
    const gone = { level: 'not_useful' as const, reason: 'Superseded.', at: '2026-10-27T10:00:00Z' }
    reset([queue, entry({ id: '5/old', slug: 'old', name: 'Old one', removed: gone }), entry({ id: '5/mine', slug: 'mine', name: 'Mine', removed: gone, installed: { slug: 'mine', version: '1.0.0', update: false, locally_changed: false } })], STATE_ON)
    renderWith(<ShopTab />)
    await screen.findByTestId('shop-list')
    expect(names()).toEqual(['Mine', 'Queue size'])
  })
})

describe('nothing found, many entries, the phone', () => {
  it('karten14 ec7: a search without a hit says "No cards match" and "Clear filters" brings the list back', async () => {
    renderWith(<ShopTab />)
    const search = await screen.findByRole('textbox', { name: 'Search by name, author or service' })
    await userEvent.type(search, 'zzzz')
    expect(screen.getByText('No cards match')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(screen.queryByText('No cards match')).toBeNull()
    expect(names()).toEqual(['Download speed', 'Queue size', 'Lamp'])
    expect(search).toHaveValue('')
  })

  it('karten14 ec8: a thousand entries draw 48 tiles at first, the rest on "Show more", and the search still finds any', async () => {
    const many = Array.from({ length: 1000 }, (_, index) => entry({ id: `1/card-${index}`, slug: `card-${index}`, name: `Card ${String(index).padStart(4, '0')}`, thumbs: 1000 - index }))
    reset(many, STATE_ON)
    renderWith(<ShopTab />)
    await screen.findByTestId('shop-list')
    expect(names()).toHaveLength(48)
    expect(screen.getByText('1000 entries')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show 952 more' }))
    expect(names()).toHaveLength(96)
    await userEvent.type(screen.getByRole('textbox', { name: 'Search by name, author or service' }), 'Card 0999')
    expect(names()).toEqual(['Card 0999'])
  })

  it('karten14 ec8: every picture waits until it comes into view', async () => {
    renderWith(<ShopTab />)
    const tile = await screen.findByTestId('shop-tile-123/queue-size')
    expect(tile.querySelector('img')).toHaveAttribute('loading', 'lazy')
  })

  it('karten14 ec10: on a phone one tile stands in each row', async () => {
    renderWith(<ShopTab />)
    await screen.findByTestId('shop-list')
    const grid = screen.getByRole('list', { name: 'Entries of the Card shop' })
    // grid-cols-1 is the base; wider screens add columns with breakpoints only.
    expect(grid.className.split(' ').filter((one) => /grid-cols-/.test(one) && !/^(sm|md|lg|xl):/.test(one))).toEqual(['grid-cols-1'])
  })

  it('karten14 ac3: a catalog served from memory because GitHub was not reachable says so', async () => {
    reset([queue], STATE_ON)
    const { world } = await import('../../../test/shopWorld')
    world.catalog = { ...world.catalog, warning: { code: 'github_unreachable', message: 'GitHub cannot be reached.' } }
    renderWith(<ShopTab />)
    expect(await screen.findByTestId('shop-stale')).toHaveTextContent('GitHub could not be reached, so this is the catalog from')
  })

  it('karten14 ec5: turning the shop off from its list saves the switch and shows the off state', async () => {
    renderWith(<ShopTab />)
    await userEvent.click(await screen.findByRole('button', { name: 'Turn off the Card shop' }))
    expect(await screen.findByTestId('shop-off')).toBeInTheDocument()
    expect(githubWasAsked().length).toBe(1)
  })
})
