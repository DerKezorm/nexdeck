/**
 * Sharing a skin in the Card shop (skins, phase D): the dialog of a card, without a category to pick (the shop finds
 * skins by their type) and with a line about the pictures the Workshop draws instead of a preview of a card.
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { calls, renderWith, reset, STATE_ON, stub, world } from '../../../test/shopWorld'
import { ShareDialog } from './ShareDialog'

const SIGNED_IN = { signed_in: true, login: 'someone', github_id: '4242', until: '2027-04-30T10:00:00Z', pending: null }
const CHECK = {
  type: 'skin',
  slug: 'pixel-desk',
  name: 'Pixel desk',
  version: '1.0.0',
  problems: [],
  warnings: { real_values: [] },
  signed_in: true,
  login: 'someone',
  mode: 'new',
  previous_version: null,
  based_on: null,
  removed: null,
  daily: { used: 0, max: 10, reached: false },
  github: null,
  suggested: { description: 'Bricks behind the cards and red title bars.', category: '' },
  reads: [],
  repo: 'DerKezorm/nexdeck-workshop',
}

beforeEach(() => {
  reset([], STATE_ON)
  world.given['GET /workshop/github'] = { status: 200, body: SIGNED_IN }
  world.given['POST /workshop/submit/check'] = { status: 200, body: CHECK }
  world.given['POST /workshop/submit'] = { status: 200, body: { issue: { number: 3, url: 'https://github.com/DerKezorm/nexdeck-workshop/issues/3', state: 'open' }, created: true, changed: true, update: false } }
  stub()
})
afterEach(() => vi.unstubAllGlobals())

describe('sharing a skin', () => {
  it('asks for no category, says how the Workshop shows it, and sends it as a skin', async () => {
    renderWith(<ShareDialog kind="skin" slug="pixel-desk" name="Pixel desk" open onClose={() => undefined} />)
    const dialog = await screen.findByRole('dialog', { name: 'Share in the Card shop' })
    expect(await within(dialog).findByTestId('share-skin')).toHaveTextContent('The Workshop draws its pictures on the stage of the editor')
    expect(calls('POST', '/workshop/submit/check')[0].body).toEqual({ type: 'skin', slug: 'pixel-desk' })
    expect(within(dialog).getByLabelText('Category').closest('div')).not.toBeVisible()
    await userEvent.click(within(dialog).getByRole('checkbox', { name: /MIT License/ }))
    const share = within(dialog).getByRole('button', { name: 'Share' })
    expect(share).toBeEnabled()
    await userEvent.click(share)
    await waitFor(() => expect(calls('POST', '/workshop/submit')).toHaveLength(1))
    expect(calls('POST', '/workshop/submit')[0].body).toMatchObject({ type: 'skin', slug: 'pixel-desk', category: 'other', description: 'Bricks behind the cards and red title bars.', license: true })
  })
})
