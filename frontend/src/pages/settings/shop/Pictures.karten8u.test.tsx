/**
 * B2 of a review of 1.0.2: the picture paths a custom card's text makes are fetched with the connection's credentials. A
 * card that leaves one out says why, in the viewer's language; the Card shop shows them before installing, and an update
 * that brings a new one stays locked until each is confirmed.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { BuilderCard } from '../../../components/BuilderCard'
import { PostersCard } from '../../../components/renderers'
import de from '../../../i18n/texts.de.json'
import { registerTexts, type TextBundle } from '../../../i18n/texts'
import type { ShopEntry } from '../../../lib/cardShop'
import type { WidgetView } from '../../../lib/types'
import { useAuth } from '../../../stores/auth'
import { calls, entry, renderWith, reset, STATE_ON, stub, world } from '../../../test/shopWorld'
import { CustomCardsSettings } from '../CustomCardsSettings'
import { ShopActs } from './ShopActs'

const NOTICE = 'A picture of this card is not shown: its path asks the service to do something, and a card only reads.'
const widget: WidgetView = { id: 9, kind: 'custom.posters', title: 'Pictures', icon: '', link: '', renderer: 'posters', options: {}, integration_id: 1, refresh_seconds: null }

describe('a card that leaves a picture out', () => {
  afterEach(async () => {
    await i18next.changeLanguage('en')
  })

  it('karten8u b2: a wall of pictures says why, in the viewer\'s language', async () => {
    registerTexts('de', de as TextBundle)
    const data = { status: 'ok' as const, items: [{ title: 'a' }], meta: { custom: true, notice: NOTICE } }
    const { rerender } = render(<PostersCard widget={widget} data={data} />)
    expect(screen.getByTestId('card-notice')).toHaveTextContent(NOTICE)
    await i18next.changeLanguage('de')
    rerender(<PostersCard widget={widget} data={{ ...data }} />)
    expect(screen.getByTestId('card-notice')).toHaveTextContent('Ein Bild dieser Karte wird nicht gezeigt')
  })

  it('karten8u b2: a card of blocks says it too', () => {
    render(<BuilderCard widget={{ ...widget, renderer: 'builder' }} data={{ status: 'ok', meta: { custom: true, blocks: [], notice: NOTICE } }} />)
    expect(screen.getByTestId('card-notice')).toHaveTextContent(NOTICE)
  })
})

describe('the Card shop', () => {
  it('karten8u b2: shows the picture paths of the checked definition beside what it reads', () => {
    const shown = { ...entry(), verified: true, pictures: [{ kind: 'jsonapi', path: '/api/{id}/thumb.jpg' }] } as ShopEntry
    render(<ShopActs entry={shown} />)
    expect(screen.getByTestId('shop-pictures')).toHaveTextContent('/api/{id}/thumb.jpg')
  })

  it('karten8u b2: an entry without pictures shows no such part', () => {
    render(<ShopActs entry={{ ...entry(), verified: true } as ShopEntry} />)
    expect(screen.queryByTestId('shop-pictures')).toBeNull()
  })
})

describe('the update dialog', () => {
  const SLUG = 'queue-size'
  const UPDATE_PATH = `/workshop/updates/${SLUG}`
  const PICTURE = '/api/{id}/thumb.jpg'

  beforeEach(() => {
    localStorage.clear()
    reset([entry({ installed: { slug: SLUG, version: '1.0.0', update: true, locally_changed: false } })], STATE_ON)
    world.updates = { enabled: true, catalog_known: true, updates: [{ slug: SLUG, ref: '123/queue-size', name: { en: 'Queue size' }, installed_version: '1.0.0', new_version: '1.1.0', needs_newer: false, min_nexdeck: null, locally_changed: false }], removed: [] }
    world.given[`GET ${UPDATE_PATH}`] = {
      status: 200,
      body: {
        slug: SLUG, name: { en: 'Queue size' }, ref: '123/queue-size', installed_version: '1.0.0', new_version: '1.1.0', needs_newer: false, min_nexdeck: null,
        changelog: '1.1.0: pictures', locally_changed: false, connection_changed: false, placed_on: 1, buttons_to_confirm: [], pictures_to_confirm: [PICTURE],
        permissions: { requires: { added: [], removed: [] }, requests: { added: [], changed: [], removed: [] }, buttons: { added: [], changed: [], removed: [] }, pictures: { added: [PICTURE], removed: [] } },
      },
    }
    world.given[`POST ${UPDATE_PATH}/accept`] = { status: 200, body: { status: 'updated', slug: SLUG, version: '1.1.0', copy_slug: null } }
    world.given['GET /cards'] = {
      status: 200,
      body: {
        cards: [{ slug: SLUG, name: { en: 'Queue size' }, description: null, form: 'value', version: '1.0.0', author: 'someone', requires: [], origin: 'shop', shop_version: '1.0.0', boards: [], users_may_place: false, updated_at: '2026-10-25T10:00:00Z', shop: { ref: '123/queue-size', update: true, removed: null } }],
        limit: 200,
      },
    }
    stub()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    useAuth.setState({ user: null })
  })

  it('karten8u b2: a new picture path is listed and "Update now" stays locked until it is confirmed', async () => {
    renderWith(<CustomCardsSettings />, '/system/cards')
    await userEvent.click(await screen.findByTestId('shop-note-update'))
    const dialog = await screen.findByRole('dialog', { name: 'Update Queue size' })
    expect(await within(dialog).findByTestId('update-permissions')).toHaveTextContent(`New picture path: ${PICTURE}`)
    const confirm = within(dialog).getByTestId('update-confirm-pictures')
    const accept = within(dialog).getByRole('button', { name: 'Update now' })
    expect(accept).toBeDisabled()
    await userEvent.click(within(confirm).getByRole('checkbox'))
    expect(accept).toBeEnabled()
    await userEvent.click(accept)
    await waitFor(() => expect(calls('POST', `${UPDATE_PATH}/accept`)).toHaveLength(1))
    expect(calls('POST', `${UPDATE_PATH}/accept`)[0].body).toEqual({ confirmed_buttons: [], confirmed_pictures: [PICTURE], keep_mine: true, expected_version: '1.1.0' })
  })
})
