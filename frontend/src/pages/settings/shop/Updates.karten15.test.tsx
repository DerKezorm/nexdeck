/**
 * Updates and recalls of the Card shop (KARTEN-15): the notices in the shop, in Custom cards and on the card, the update
 * dialog with its changes, the rights that change and the buttons to confirm one by one, a card changed here, "Later",
 * "Already up to date", a version that is too new, and the shop being off.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ShopCardNote } from '../../../components/ShopCardNote'
import { WidgetCard } from '../../../components/WidgetCard'
import { DEMO_VIEWS } from '../../../demo/board'
import deScreen from '../../../i18n/de.json'
import type { WidgetData, WidgetView } from '../../../lib/types'
import { useAuth } from '../../../stores/auth'
import { calls, entry, failure, renderWith, reset, STATE_OFF, STATE_ON, stub, world } from '../../../test/shopWorld'
import { CustomCardsSettings } from '../CustomCardsSettings'
import { ShopTab } from './ShopTab'

const SLUG = 'queue-size'
const UPDATE_PATH = `/workshop/updates/${SLUG}`

const installed = (over = {}) => ({ slug: SLUG, version: '1.0.0', update: true, locally_changed: false, ...over })
const BUTTON = { id: 'restart', label: { en: 'Restart' }, method: 'POST', path: '/api/restart', send: 'json', body: { hard: true }, where: 'card' }
const WIPE = { id: 'wipe', label: { en: 'Wipe' }, method: 'DELETE', path: '/api/wipe', send: 'json', body: null, where: 'row' }

const UPDATE = (over: Record<string, unknown> = {}) => ({
  slug: SLUG,
  name: { en: 'Queue size' },
  ref: '123/queue-size',
  installed_version: '1.0.0',
  new_version: '1.1.0',
  needs_newer: false,
  min_nexdeck: null,
  changelog: '1.1.0: counts the episodes too',
  locally_changed: false,
  permissions: { requires: { added: [], removed: [] }, requests: { added: [], changed: [], removed: [] }, buttons: { added: [], changed: [], removed: [] } },
  buttons_to_confirm: [],
  connection_changed: false,
  placed_on: 2,
  ...over,
})

const row = (over = {}) => ({
  slug: SLUG,
  name: { en: 'Queue size' },
  description: null,
  form: 'value',
  version: '1.0.0',
  author: 'someone',
  requires: [],
  origin: 'shop',
  shop_version: '1.0.0',
  boards: [],
  users_may_place: false,
  updated_at: '2026-10-25T10:00:00Z',
  shop: { ref: '123/queue-size', update: true, removed: null },
  ...over,
})

function serveCards(rows: unknown[]) {
  world.given['GET /cards'] = { status: 200, body: { cards: rows, limit: 200 } }
}

beforeEach(() => {
  localStorage.clear()
  reset([entry({ installed: installed() })], STATE_ON)
  world.updates = { enabled: true, catalog_known: true, updates: [{ slug: SLUG, ref: '123/queue-size', name: { en: 'Queue size' }, installed_version: '1.0.0', new_version: '1.1.0', needs_newer: false, min_nexdeck: null, locally_changed: false }], removed: [] }
  world.given[`GET ${UPDATE_PATH}`] = { status: 200, body: UPDATE() }
  world.given[`POST ${UPDATE_PATH}/accept`] = { status: 200, body: { status: 'updated', slug: SLUG, version: '1.1.0', copy_slug: null } }
  serveCards([row()])
  stub()
})
afterEach(async () => {
  vi.unstubAllGlobals()
  useAuth.setState({ user: null })
  await i18next.changeLanguage('en')
})

const openUpdate = async () => {
  renderWith(<CustomCardsSettings />, '/system/cards')
  await userEvent.click(await screen.findByTestId('shop-note-update'))
  return await screen.findByRole('dialog', { name: 'Update Queue size' })
}

describe('the notices', () => {
  it('karten15 ac1: the shop and Custom cards both say "Update available" for a newer version', async () => {
    const first = renderWith(<ShopTab />)
    const tile = await screen.findByTestId('shop-tile-123/queue-size')
    expect(within(tile).getByTestId('shop-update')).toHaveTextContent('Update available')
    first.unmount()
    renderWith(<CustomCardsSettings />, '/system/cards')
    const card = (await screen.findByText('Queue size')).closest('li')!
    expect(within(card).getByTestId('shop-note-update')).toHaveTextContent('Update available')
  })

  it('karten15 ac6: a card taken out of the shop says so with the reason in the shop, in Custom cards and on the card, which goes on running', async () => {
    const removed = { level: 'not_useful' as const, reason: 'Superseded by another card.', at: '2026-10-27T10:00:00Z' }
    reset([entry({ installed: installed({ update: false }), removed })], STATE_ON)
    world.updates = { enabled: true, catalog_known: true, updates: [], removed: [{ slug: SLUG, ref: '123/queue-size', name: { en: 'Queue size' }, ...removed }] }
    serveCards([row({ shop: { ref: '123/queue-size', update: false, removed } })])
    stub()
    const first = renderWith(<ShopTab />)
    expect(await screen.findByTestId('shop-removed')).toHaveTextContent('Removed from the Card shop')
    first.unmount()
    const second = renderWith(<CustomCardsSettings />, '/system/cards')
    const card = (await screen.findByText('Queue size')).closest('li')!
    expect(within(card).getByTestId('shop-note-removed')).toHaveTextContent('Removed from the Card shop: Superseded by another card.')
    expect(within(card).queryByTestId('shop-note-update')).toBeNull()
    // The card is still there to be placed and edited: nothing about it is switched off.
    expect(within(card).getByRole('button', { name: 'Edit Queue size' })).toBeEnabled()
    second.unmount()
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <ShopCardNote slug={SLUG} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(await screen.findByTestId('card-shop-note')).toHaveAttribute('aria-label', 'Removed from the Card shop: Superseded by another card.')
  })

  it('karten15 ac7: "harmful" is red and the other reasons are not', async () => {
    const harmful = { level: 'harmful' as const, reason: 'It deletes things.', at: '2026-10-27T10:00:00Z' }
    serveCards([row({ shop: { ref: '1/a', update: false, removed: harmful } }), row({ slug: 'two', name: { en: 'Two' }, shop: { ref: '1/b', update: false, removed: { ...harmful, level: 'withdrawn', reason: 'Author left.' } } })])
    renderWith(<CustomCardsSettings />, '/system/cards')
    const red = (await screen.findByText('Queue size')).closest('li')!.querySelector('[data-testid="shop-note-removed"]')!
    const calm = screen.getByText('Two').closest('li')!.querySelector('[data-testid="shop-note-removed"]')!
    expect(red).toHaveAttribute('data-level', 'harmful')
    expect(red.className).toContain('text-bad')
    expect(calm.className).not.toContain('text-bad')
  })

  it('karten15 ac6: a card that is removed and has a newer version shows the recall only, since there is nothing to update to', async () => {
    const gone = { level: 'harmful' as const, reason: 'It deletes things.', at: '2026-10-27T10:00:00Z' }
    serveCards([row({ shop: { ref: '1/a', update: true, removed: gone } })])
    renderWith(<CustomCardsSettings />, '/system/cards')
    const card = (await screen.findByText('Queue size')).closest('li')!
    expect(within(card).getByTestId('shop-note-removed')).toBeInTheDocument()
    expect(within(card).queryByTestId('shop-note-update')).toBeNull()
  })

  it('karten15 ac6: on the card, an administrator sees the note and somebody else does not', async () => {
    const view = { ...DEMO_VIEWS[0], id: 41, kind: 'custom.value', renderer: 'value', title: 'Queue', options: { card: SLUG }, link: '' } as WidgetView
    const data = { status: 'ok', primary: { label: 'Queue', value: 1, format: 'number', text: '1' }, meta: { custom: true } } as unknown as WidgetData
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const draw = () =>
      render(
        <QueryClientProvider client={client}>
          <MemoryRouter>
            <div className="@container" style={{ width: 400 }}>
              <WidgetCard widget={view} data={data} />
            </div>
          </MemoryRouter>
        </QueryClientProvider>,
      )
    useAuth.setState({ user: { id: 2, username: 'kim', role: 'user' } as never })
    const first = draw()
    await screen.findByRole('region', { name: 'Queue' })
    expect(screen.queryByTestId('card-shop-note')).toBeNull()
    expect(calls('GET', '/workshop/updates')).toHaveLength(0)
    first.unmount()
    useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin' } as never })
    draw()
    expect(await screen.findByTestId('card-shop-note')).toHaveAttribute('aria-label', 'Update available')
  })

  it('karten15 ec3: with the shop off Custom cards says in a sentence that there are no notices', async () => {
    reset([], STATE_OFF)
    serveCards([row({ shop: null })])
    stub()
    renderWith(<CustomCardsSettings />, '/system/cards')
    const card = (await screen.findByText('Queue size')).closest('li')!
    expect(within(card).queryByTestId('shop-note')).toBeNull()
    expect(await screen.findByText(/no notices about updates or removed cards/)).toBeInTheDocument()
  })

  it('karten15 ec6: a placed card whose connection no longer fits says so, in the viewer\'s language', async () => {
    await i18next.changeLanguage('de')
    i18next.addResourceBundle('de', 'translation', deScreen, true, true)
    expect(i18next.t('errors.widget.kind_mismatch')).toBe('Die Verbindung passt nicht mehr zu dieser Karte.')
    await i18next.changeLanguage('en')
    expect(i18next.t('errors.widget.kind_mismatch')).toBe('The connection no longer fits this card.')
  })
})

describe('the update dialog', () => {
  it('karten15 ac2: shows the list of changes and the rights that change: sources, addresses, buttons', async () => {
    world.given[`GET ${UPDATE_PATH}`] = {
      status: 200,
      body: UPDATE({
        permissions: {
          requires: { added: ['radarr'], removed: [] },
          requests: { added: [{ id: 'q', path: '/api/v3/queue' }], changed: [{ id: 'm', before: '/api/old', after: '/api/new' }], removed: [] },
          buttons: { added: [BUTTON], changed: [{ before: WIPE, after: { ...WIPE, path: '/api/wipe-all' } }], removed: [] },
        },
        buttons_to_confirm: ['restart', 'wipe'],
      }),
    }
    const dialog = await openUpdate()
    expect(await within(dialog).findByTestId('update-changelog')).toHaveTextContent('1.1.0: counts the episodes too')
    const rights = within(dialog).getByTestId('update-permissions')
    expect(rights).toHaveTextContent('Now also reads through radarr')
    expect(rights).toHaveTextContent('/api/v3/queue')
    expect(rights).toHaveTextContent('/api/old → /api/new')
    expect(rights).toHaveTextContent('New button: Restart POST /api/restart {"hard":true}')
    expect(rights).toHaveTextContent('Changed button: Wipe DELETE /api/wipe → Wipe DELETE /api/wipe-all')
    expect(within(dialog).getByText('From version 1.0.0 to version 1.1.0.')).toBeInTheDocument()
  })

  it('karten15 ac2: an update that changes no right says so', async () => {
    const dialog = await openUpdate()
    expect(await within(dialog).findByTestId('update-permissions')).toHaveTextContent('It reads the same and has the same buttons as before.')
    expect(within(dialog).queryByTestId('update-confirm')).toBeNull()
  })

  it('karten15 ac3: with a new or changed button "Update now" stays locked until every one is confirmed', async () => {
    world.given[`GET ${UPDATE_PATH}`] = {
      status: 200,
      body: UPDATE({ permissions: { requires: { added: [], removed: [] }, requests: { added: [], changed: [], removed: [] }, buttons: { added: [BUTTON], changed: [{ before: WIPE, after: { ...WIPE, path: '/api/x' } }], removed: [] } }, buttons_to_confirm: ['restart', 'wipe'] }),
    }
    const dialog = await openUpdate()
    const confirm = await within(dialog).findByTestId('update-confirm')
    const accept = within(dialog).getByRole('button', { name: 'Update now' })
    expect(accept).toBeDisabled()
    const boxes = within(confirm).getAllByRole('checkbox')
    expect(boxes).toHaveLength(2)
    await userEvent.click(boxes[0])
    expect(accept).toBeDisabled()
    await userEvent.click(boxes[1])
    expect(accept).toBeEnabled()
    await userEvent.click(accept)
    await waitFor(() => expect(calls('POST', `${UPDATE_PATH}/accept`)).toHaveLength(1))
    expect(calls('POST', `${UPDATE_PATH}/accept`)[0].body).toEqual({ confirmed_buttons: ['restart', 'wipe'], keep_mine: true, expected_version: '1.1.0' })
  })

  it('karten15 ac4: accepting says that the boards follow at once and refreshes the list', async () => {
    const dialog = await openUpdate()
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Update now' }))
    expect(await within(dialog).findByTestId('update-done')).toHaveTextContent('Updated to version 1.1.0. Every board that shows the card has it already.')
    await waitFor(() => expect(calls('GET', '/cards').length).toBeGreaterThan(1))
  })

  it('karten15 ac5: "Later" closes the dialog, asks for nothing and leaves the notice', async () => {
    const dialog = await openUpdate()
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Later' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(calls('POST', `${UPDATE_PATH}/accept`)).toHaveLength(0)
    expect(screen.getByTestId('shop-note-update')).toBeInTheDocument()
  })

  it('karten15 ec1: a version that needs a newer nexdeck says so and cannot be accepted', async () => {
    world.given[`GET ${UPDATE_PATH}`] = { status: 200, body: UPDATE({ needs_newer: true, min_nexdeck: '0.99.0' }) }
    const dialog = await openUpdate()
    expect(await within(dialog).findByTestId('update-needs-newer')).toHaveTextContent('Needs nexdeck 0.99.0')
    expect(within(dialog).getByRole('button', { name: 'Update now' })).toBeDisabled()
  })

  it('karten15 ec2: a card changed here is warned about, and "Keep mine as a copy" is ticked at first', async () => {
    world.given[`GET ${UPDATE_PATH}`] = { status: 200, body: UPDATE({ locally_changed: true }) }
    world.given[`POST ${UPDATE_PATH}/accept`] = { status: 200, body: { status: 'updated', slug: SLUG, version: '1.1.0', copy_slug: 'queue-size-mine' } }
    const dialog = await openUpdate()
    const local = await within(dialog).findByTestId('update-local')
    expect(local).toHaveTextContent('The update replaces your changes.')
    const keep = within(local).getByRole('checkbox', { name: 'Keep mine as a copy' })
    expect(keep).toBeChecked()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Update now' }))
    expect(calls('POST', `${UPDATE_PATH}/accept`)[0].body).toMatchObject({ keep_mine: true })
    expect(await within(dialog).findByText(/kept as a copy, queue-size-mine/)).toBeInTheDocument()
  })

  it('karten15 ec2: unticking "Keep mine as a copy" sends it so', async () => {
    world.given[`GET ${UPDATE_PATH}`] = { status: 200, body: UPDATE({ locally_changed: true }) }
    const dialog = await openUpdate()
    await userEvent.click(await within(dialog).findByRole('checkbox', { name: 'Keep mine as a copy' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Update now' }))
    await waitFor(() => expect(calls('POST', `${UPDATE_PATH}/accept`)).toHaveLength(1))
    expect(calls('POST', `${UPDATE_PATH}/accept`)[0].body).toMatchObject({ keep_mine: false })
  })

  it('karten15 ec5: when another administrator was first it says "Already up to date"', async () => {
    world.given[`POST ${UPDATE_PATH}/accept`] = { status: 200, body: { status: 'already_up_to_date', slug: SLUG, version: '1.1.0', copy_slug: null } }
    const dialog = await openUpdate()
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Update now' }))
    expect(await within(dialog).findByTestId('update-done')).toHaveTextContent('Already up to date.')
  })

  it('karten15 ec5: an update that is no longer there says "Already up to date" too', async () => {
    world.given[`GET ${UPDATE_PATH}`] = failure(409, 'no_update')
    const dialog = await openUpdate()
    expect(await within(dialog).findByTestId('update-failed')).toHaveTextContent('Already up to date.')
  })

  it('karten15 ac3: a newer version that came in meanwhile is read again, with the reason said', async () => {
    world.given[`POST ${UPDATE_PATH}/accept`] = failure(409, 'update_changed')
    const dialog = await openUpdate()
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Update now' }))
    expect(await within(dialog).findByTestId('update-error')).toHaveTextContent('A newer version came in meanwhile. Read the changes again.')
    await waitFor(() => expect(calls('GET', UPDATE_PATH).length).toBeGreaterThan(1))
  })

  it('karten15 ec6: an update that changes the connection says so', async () => {
    world.given[`GET ${UPDATE_PATH}`] = { status: 200, body: UPDATE({ connection_changed: true, permissions: { requires: { added: ['radarr'], removed: ['sonarr'] }, requests: { added: [], changed: [], removed: [] }, buttons: { added: [], changed: [], removed: [] } } }) }
    const dialog = await openUpdate()
    expect(await within(dialog).findByTestId('update-connection')).toHaveTextContent('which connection the card needs')
    expect(within(dialog).getByTestId('update-permissions')).toHaveTextContent('No longer reads through sonarr')
  })

  it('karten15 ac2: from the shop page an installed entry with an update offers "Update"', async () => {
    renderWith(<ShopTab />)
    await userEvent.click(await screen.findByText('Queue size'))
    await userEvent.click(await screen.findByRole('button', { name: 'Update' }))
    expect(await screen.findByRole('dialog', { name: 'Update Queue size' })).toBeInTheDocument()
  })
})
