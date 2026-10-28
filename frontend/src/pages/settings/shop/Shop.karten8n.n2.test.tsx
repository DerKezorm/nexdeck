/** N2 (Etappe 8): the preview picture of an entry carries the version of the picture in its address. */
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { pictureSrc } from '../../../lib/cardShop'
import { entry, renderWith, reset, STATE_ON, stub, world } from '../../../test/shopWorld'
import { ShopTab } from './ShopTab'

const PATH = '/workshop/entries/123/queue-size'

beforeEach(() => {
  localStorage.clear()
  reset([entry()], STATE_ON)
  stub()
})
afterEach(async () => {
  vi.unstubAllGlobals()
  await i18next.changeLanguage('en')
})

describe('N2: the picture carries its version', () => {
  it('karten8n_n2: the address adds ?v= with the version of the picture, encoded', () => {
    const base = entry({ picture_version: '1.2.0' })
    expect(pictureSrc(base, 'dark')).toBe('/api/v1/workshop/entries/123/queue-size/image/dark?v=1.2.0')
    expect(pictureSrc({ ...base, picture_version: '2026-10-28T10:00:00+02:00' }, 'light')).toBe('/api/v1/workshop/entries/123/queue-size/image/light?v=2026-10-28T10%3A00%3A00%2B02%3A00')
  })

  it('karten8n_n2: without the field the address stays as it was', () => {
    expect(pictureSrc(entry(), 'light')).toBe('/api/v1/workshop/entries/123/queue-size/image/light')
  })

  it('karten8n_n2: the tile and the detail page draw the picture with ?v=', async () => {
    reset([entry({ picture_version: '1.2.0' })], STATE_ON)
    world.given[`GET ${PATH}`] = { status: 200, body: { ...entry({ picture_version: '1.2.0' }), readme: null, changelog: null, files_warning: null, offered_integrations: [] } }
    renderWith(<ShopTab />)
    const tile = await screen.findByTestId('shop-tile-123/queue-size')
    expect(tile.querySelector('img')!.getAttribute('src')).toMatch(/\/image\/(light|dark)\?v=1\.2\.0$/)
    await userEvent.click(within(tile).getByRole('button'))
    const page = await screen.findByTestId('shop-detail')
    expect(page.querySelector('img')!.getAttribute('src')).toMatch(/\/image\/(light|dark)\?v=1\.2\.0$/)
  })
})
