/**
 * The Card shop tab when it is off, when the catalog cannot be had, and the switch (KARTEN-14 AC-2, AC-10, AC-13, EC-5, EC-6).
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { calls, failure, githubWasAsked, renderWith, reset, STATE_OFF, STATE_ON, stub, world } from '../../../test/shopWorld'
import { CustomCardsSettings } from '../CustomCardsSettings'
import { ShopTab } from './ShopTab'

beforeEach(() => {
  localStorage.clear()
  reset([], STATE_OFF)
  stub()
})
afterEach(() => vi.unstubAllGlobals())

describe('the shop while it is off', () => {
  it('karten14 ac2: says one sentence and offers "Turn on", and asks the catalog of nobody', async () => {
    renderWith(<ShopTab />)
    const off = await screen.findByTestId('shop-off')
    expect(within(off).getByText(/Loads the catalog from GitHub/)).toBeInTheDocument()
    expect(within(off).getByRole('button', { name: 'Turn on' })).toBeEnabled()
    expect(githubWasAsked()).toEqual([])
  })

  it('karten14 ac2: "Turn on" saves the switch and only then loads the catalog', async () => {
    renderWith(<ShopTab />)
    await userEvent.click(await screen.findByRole('button', { name: 'Turn on' }))
    await waitFor(() => expect(calls('GET', '/workshop/catalog')).toHaveLength(1))
    expect(calls('PUT', '/workshop/settings')[0].body).toEqual({ enabled: true })
    const order = world.asked.map((one) => `${one.method} ${one.url}`)
    expect(order.indexOf('PUT /workshop/settings')).toBeLessThan(order.indexOf('GET /workshop/catalog'))
  })

  it('karten14 ac13: "What it sends" says that only the catalog and files come in and nothing goes out', async () => {
    renderWith(<ShopTab />)
    await userEvent.click(await screen.findByRole('button', { name: 'What it sends' }))
    const note = await screen.findByTestId('shop-sends')
    expect(note).toHaveTextContent('The shop only loads the catalog and the files of cards from GitHub. Nothing from your installation goes out.')
    expect(githubWasAsked()).toEqual([])
  })

  it('karten14 ac2: the switch stands under System too, in the list of cards', async () => {
    renderWith(<CustomCardsSettings />, '/system/cards')
    const row = await screen.findByTestId('shop-switch')
    const toggle = within(row).getByRole('switch', { name: 'Card shop' })
    expect(toggle).toHaveAttribute('aria-checked', 'false')
    expect(within(row).getByText(/there are no notices about updates or removed cards/)).toBeInTheDocument()
    await userEvent.click(toggle)
    await waitFor(() => expect(within(screen.getByTestId('shop-switch')).getByRole('switch')).toHaveAttribute('aria-checked', 'true'))
    expect(calls('PUT', '/workshop/settings')[0].body).toEqual({ enabled: true })
    expect(githubWasAsked()).toEqual([])
  })
})

describe('a catalog that cannot be shown', () => {
  beforeEach(() => reset([], STATE_ON))

  it('karten14 ac10: GitHub not reachable is said, and that installed cards go on', async () => {
    world.given['GET /workshop/catalog'] = failure(502, 'github_unreachable')
    renderWith(<ShopTab />)
    const problem = await screen.findByTestId('shop-problem')
    expect(within(problem).getByText('GitHub not reachable')).toBeInTheDocument()
    expect(problem).toHaveTextContent('Cards you installed keep working.')
  })

  it('karten14 ec6: a broken and an empty catalog are errors, not an empty list', async () => {
    world.given['GET /workshop/catalog'] = failure(502, 'catalog_invalid')
    const first = renderWith(<ShopTab />)
    expect(await screen.findByText('The catalog is broken')).toBeInTheDocument()
    expect(screen.queryByTestId('shop-list')).toBeNull()
    first.unmount()
    world.given['GET /workshop/catalog'] = failure(502, 'catalog_empty')
    renderWith(<ShopTab />)
    expect(await screen.findByText('The catalog is empty')).toBeInTheDocument()
    expect(screen.queryByTestId('shop-list')).toBeNull()
  })

  it('karten14 ac10: "Try again" asks for the catalog once more', async () => {
    world.given['GET /workshop/catalog'] = failure(502, 'github_unreachable')
    renderWith(<ShopTab />)
    await screen.findByTestId('shop-problem')
    delete world.given['GET /workshop/catalog']
    reset([], STATE_ON)
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByTestId('shop-list')).toBeInTheDocument()
  })
})
