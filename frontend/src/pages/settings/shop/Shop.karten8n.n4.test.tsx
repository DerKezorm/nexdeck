/** N4 (Etappe 8): the description without the README, and the changes since the installed version. */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { calls, entry, renderWith, reset, STATE_ON, stub, world } from '../../../test/shopWorld'
import { ShopTab } from './ShopTab'

const PATH = '/workshop/entries/123/queue-size'
const SLUG = 'queue-size'

beforeEach(() => {
  localStorage.clear()
  reset([entry()], STATE_ON)
  stub()
})
afterEach(async () => {
  vi.unstubAllGlobals()
  await i18next.changeLanguage('en')
})

describe('N4: description and changes', () => {
  it('karten8n_n4: the detail shows the description of the entry and not the README', async () => {
    world.given[`GET ${PATH}`] = { status: 200, body: { ...entry(), readme: '# Queue size\n\n| a | b |\n|---|---|\n| 1 | 2 |', changelog: null, files_warning: null, offered_integrations: [] } }
    renderWith(<ShopTab />)
    await userEvent.click(await screen.findByText('Queue size'))
    const page = await screen.findByTestId('shop-detail')
    expect(within(page).getByText('Shows how many episodes wait in the queue.')).toBeInTheDocument()
    await waitFor(() => expect(calls('GET', PATH)).toHaveLength(1))
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(page).not.toHaveTextContent('|---|')
    expect(page).not.toHaveTextContent('# Queue size')
  })

  it('karten8n_n4: the update dialog shows only the sections newer than the installed version, set as headings, text and a list', async () => {
    reset([entry({ installed: { slug: SLUG, version: '1.0.9', update: true, locally_changed: false } })], STATE_ON)
    world.updates = { enabled: true, catalog_known: true, updates: [{ slug: SLUG, ref: '123/queue-size', name: { en: 'Queue size' }, installed_version: '1.0.9', new_version: '1.0.10', needs_newer: false, min_nexdeck: null, locally_changed: false }], removed: [] }
    world.given[`GET /workshop/updates/${SLUG}`] = {
      status: 200,
      body: {
        slug: SLUG, name: { en: 'Queue size' }, ref: '123/queue-size', installed_version: '1.0.9', new_version: '1.0.10', needs_newer: false, min_nexdeck: null, locally_changed: false, placed_on: 0,
        changelog: '# Changelog\n\n## 1.0.10 (2026-10-30)\n\n- Faster list\n- New icon\n\nReads one request less.\n\n## 1.0.9 (2026-10-20)\n\nFixed the colour.\n',
        permissions: { requires: { added: [], removed: [] }, requests: { added: [], changed: [], removed: [] }, buttons: { added: [], changed: [], removed: [] } },
        buttons_to_confirm: [], connection_changed: false,
      },
    }
    renderWith(<ShopTab />)
    await userEvent.click(await screen.findByText('Queue size'))
    await userEvent.click(await screen.findByRole('button', { name: 'Update' }))
    const log = await screen.findByTestId('update-changelog')
    expect(within(log).getByRole('heading', { name: '1.0.10 (2026-10-30)' })).toBeInTheDocument()
    expect(within(log).getAllByRole('listitem').map((one) => one.textContent)).toEqual(['Faster list', 'New icon'])
    expect(within(log).getByText('Reads one request less.')).toBeInTheDocument()
    expect(log).not.toHaveTextContent('1.0.9')
    expect(log).not.toHaveTextContent('Fixed the colour.')
    expect(log).not.toHaveTextContent('# Changelog')
  })
})
