/** W3 (Etappe 8): Share is off for what came unchanged from the Card shop. */
import { screen, within } from '@testing-library/react'
import i18next from 'i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import deScreen from '../../../i18n/de.json'
import { entry, renderWith, reset, STATE_ON, stub, world } from '../../../test/shopWorld'
import { CustomCardsSettings } from '../CustomCardsSettings'

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

describe('W3: Share is off for what came unchanged from the shop', () => {
  const row = (over: Record<string, unknown> = {}) => ({
    slug: SLUG, name: { en: 'Queue size' }, description: null, form: 'value', version: '1.0.0', author: 'someone', requires: [], origin: 'shop', shop_version: '1.0.0', boards: [], users_may_place: false,
    updated_at: '2026-10-25T10:00:00Z', shop: { ref: '123/queue-size', update: false, removed: null, locally_changed: false }, ...over,
  })
  const SENTENCE = 'This came unchanged from the Card shop. Change it to share your own version.'

  it('karten8n_w3: an unchanged card from the shop has the button off, with the sentence as title; changed, it is on', async () => {
    world.given['GET /cards'] = { status: 200, body: { cards: [row(), row({ slug: 'other', name: { en: 'Other' }, shop: { ref: '1/other', update: false, removed: null, locally_changed: true } })], limit: 200 } }
    renderWith(<CustomCardsSettings />, '/system/cards')
    const unchanged = (await screen.findByText('Queue size')).closest('li')!
    const off = within(unchanged).getByRole('button', { name: 'Share Queue size in the Card shop' })
    expect(off).toBeDisabled()
    expect(off).toHaveAttribute('title', SENTENCE)
    const changed = (await screen.findByText('Other')).closest('li')!
    expect(within(changed).getByRole('button', { name: 'Share Other in the Card shop' })).toBeEnabled()
  })

  it('karten8n_w3: a card of your own, and an answer that does not say, keep the button on', async () => {
    world.given['GET /cards'] = { status: 200, body: { cards: [row({ origin: 'local', shop: null }), row({ slug: 'old', name: { en: 'Old' }, shop: { ref: '1/old', update: false, removed: null } })], limit: 200 } }
    renderWith(<CustomCardsSettings />, '/system/cards')
    expect(within((await screen.findByText('Queue size')).closest('li')!).getByRole('button', { name: 'Share Queue size in the Card shop' })).toBeEnabled()
    expect(within((await screen.findByText('Old')).closest('li')!).getByRole('button', { name: 'Share Old in the Card shop' })).toBeEnabled()
  })

  it('karten8n_w3: the same for an own integration that came from the shop', async () => {
    const own = (over: Record<string, unknown>) => ({ short: 'memos', kind: 'custom:memos', name: 'Memos', logo: 'memos', description: '', connections: 0, updated_at: '2026-10-26T10:00:00Z', updated_by: 'admin', ...over })
    world.given['GET /own-integrations'] = {
      status: 200,
      body: [own({ shop_ref: '5/memos', locally_changed: false }), own({ short: 'notes', name: 'Notes', shop_ref: '5/notes', locally_changed: true }), own({ short: 'mine', name: 'Mine', shop_ref: '', locally_changed: false })],
    }
    renderWith(<CustomCardsSettings />, '/system/cards?tab=integrations')
    const list = await screen.findByTestId('own-integrations')
    const share = (name: string) => within(list).getByRole('button', { name: `Share ${name} in the Card shop` })
    expect(share('Memos')).toBeDisabled()
    expect(share('Memos')).toHaveAttribute('title', SENTENCE)
    expect(share('Notes')).toBeEnabled()
    expect(share('Mine')).toBeEnabled()
  })

  it('karten8n_w3: the sentence is there in German too', async () => {
    await i18next.changeLanguage('de')
    i18next.addResourceBundle('de', 'translation', deScreen, true, true)
    expect(deScreen.cards.share.problem.unchanged_from_shop).toBe('Das kommt unverändert aus dem Card shop. Ändere es, um deine eigene Version zu teilen.')
    world.given['GET /cards'] = { status: 200, body: { cards: [row()], limit: 200 } }
    renderWith(<CustomCardsSettings />, '/system/cards')
    const button = await screen.findByRole('button', { name: /im Card shop teilen/ })
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('title', deScreen.cards.share.problem.unchanged_from_shop)
  })
})
