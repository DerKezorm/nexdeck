/** N9 (Etappe 8): the sentence of the conflict box when installing. */
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

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

describe('N9: the sentence of the conflict box', () => {
  it('karten8n_n9: the line of a taken short name sits inside the box (the legend is not on the frame)', async () => {
    const DOC = { type: 'card', id: 'card:queue-size', slug: 'queue-size', name: 'Queue size', requires: ['sonarr'], buttons: [], form: 'value', problems: [], exists: true, same: false }
    world.given[`GET ${PATH}`] = { status: 200, body: { ...entry(), readme: null, changelog: null, files_warning: null, offered_integrations: [] } }
    world.given[`POST ${PATH}/install/check`] = { status: 200, body: { entry: entry(), ok: true, documents: [DOC], missing_integrations: [], offered_integrations: [], risk_acknowledged: true } }
    renderWith(<ShopTab />)
    await userEvent.click(await screen.findByText('Queue size'))
    await userEvent.click(await screen.findByRole('button', { name: 'Install' }))
    const box = await screen.findByTestId('install-conflict-card:queue-size')
    const legend = box.querySelector('legend')!
    // A legend that is not floated is drawn into the frame and breaks it; floated, it is a line inside the box.
    expect(legend.className).toContain('float-left')
    expect(legend.className).toContain('w-full')
    expect(legend.textContent).toContain('Queue size')
    expect(box.querySelector('.clear-both')).not.toBeNull()
  })
})
