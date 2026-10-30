/**
 * Skins in the Card shop (skins, phase D): found by their type, said to reach nothing, installed under the name the
 * server gives them with nothing to choose, refused when this nexdeck cannot wear them, and updated in a dialog of
 * their own.
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { calls, entry, renderWith, reset, STATE_ON, stub, world } from '../../../test/shopWorld'
import { ShopTab } from './ShopTab'

const PATH = '/workshop/entries/7/pixel-desk'
const skin = (over = {}) =>
  entry({
    id: '7/pixel-desk',
    author_id: '7',
    slug: 'pixel-desk',
    type: 'skin',
    name: 'Pixel desk',
    description: 'Bricks behind the cards and red title bars.',
    requires: [],
    reads: [],
    connections: [],
    fits: true,
    images: { light: `/api/v1${PATH}/image/light`, dark: `/api/v1${PATH}/image/dark` },
    ...over,
  })
const card = entry()
const CHECK = (over = {}) => ({ entry: skin(), ok: true, documents: [], problems: [], skin_key: 'pixel-desk-2', missing_integrations: [], offered_integrations: [], risk_acknowledged: false, ...over })

async function open() {
  renderWith(<ShopTab />)
  await userEvent.click(await screen.findByText('Pixel desk'))
  return await screen.findByTestId('shop-detail')
}

async function installDialog() {
  const page = await open()
  await userEvent.click(within(page).getByRole('button', { name: 'Install' }))
  return await screen.findByRole('dialog', { name: 'Install Pixel desk' })
}

beforeEach(() => {
  localStorage.clear()
  reset([skin(), card], STATE_ON)
  world.given[`GET ${PATH}`] = { status: 200, body: { ...skin(), readme: null, changelog: null, files_warning: null, offered_integrations: [] } }
  world.given[`POST ${PATH}/install/check`] = { status: 200, body: CHECK() }
  world.given[`POST ${PATH}/install`] = { status: 201, body: { slug: null, integration: null, skin: 'pixel-desk-2', integrations: [], outcome: null, missing_integrations: [], place_url: '/system/skins' } }
  stub()
})
afterEach(() => vi.unstubAllGlobals())

describe('a skin in the list', () => {
  it('is found by its type, and its tile names no reach', async () => {
    renderWith(<ShopTab />)
    const tile = await screen.findByTestId('shop-tile-7/pixel-desk')
    expect(within(tile).getByText('Skin')).toBeInTheDocument()
    expect(within(tile).queryByText('Only reads')).toBeNull()
    expect(within(screen.getByTestId('shop-tile-123/queue-size')).getByText('Only reads')).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByDisplayValue('Every type'), 'skin')
    await waitFor(() => expect(screen.queryByTestId('shop-tile-123/queue-size')).toBeNull())
    expect(screen.getByTestId('shop-tile-7/pixel-desk')).toBeInTheDocument()
  })

  it('says on its page that a skin only changes the look, instead of what it reads and presses', async () => {
    const page = await open()
    expect(within(page).getByTestId('shop-skin-acts')).toHaveTextContent('A skin only changes how nexdeck looks.')
    expect(within(page).queryByTestId('shop-reads')).toBeNull()
    expect(within(page).queryByText('Only reads')).toBeNull()
  })
})

describe('installing a skin', () => {
  it('says the name it gets here, asks only about the risk, and leads to the skins afterwards', async () => {
    const dialog = await installDialog()
    expect(await within(dialog).findByText('It becomes the skin pixel-desk-2. Choose it under Look or in your profile.')).toBeInTheDocument()
    const install = within(dialog).getByRole('button', { name: 'Install' })
    expect(install).toBeDisabled()
    await userEvent.click(within(dialog).getByRole('checkbox', { name: /at my own risk/ }))
    expect(install).toBeEnabled()
    await userEvent.click(install)
    await waitFor(() => expect(calls('POST', `${PATH}/install`)).toHaveLength(1))
    expect(calls('POST', `${PATH}/install`)[0].body).toMatchObject({ accept_risk: true })
    const page = screen.getByTestId('shop-detail')
    expect(await within(page).findByRole('link', { name: 'To the skins' })).toHaveAttribute('href', '/system/skins')
  })

  it('is not offered when this nexdeck cannot wear it, and says why', async () => {
    world.given[`POST ${PATH}/install/check`] = { status: 200, body: CHECK({ ok: false, risk_acknowledged: true, problems: [{ path: 'css', message: '!important is not allowed.' }] }) }
    const dialog = await installDialog()
    expect(await within(dialog).findByTestId('install-skin-problems')).toHaveTextContent('css: !important is not allowed.')
    expect(within(dialog).getByRole('button', { name: 'Install' })).toBeDisabled()
  })
})

describe('updating a skin', () => {
  it('shows both versions and takes the update, keeping what was changed here as a copy', async () => {
    reset([skin({ installed: { slug: 'pixel-desk', version: '1.0.0', update: true, locally_changed: true } }), card], STATE_ON)
    world.given[`GET ${PATH}`] = { status: 200, body: { ...skin({ installed: { slug: 'pixel-desk', version: '1.0.0', update: true, locally_changed: true } }), readme: null, changelog: null, files_warning: null, offered_integrations: [] } }
    world.given['GET /workshop/updates/skins/pixel-desk'] = {
      status: 200,
      body: { key: 'pixel-desk', name: 'Pixel desk', installed_version: '1.0.0', new_version: '1.1.0', needs_newer: false, min_nexdeck: null, changelog: '## 1.1.0\n\nBrighter bricks.', locally_changed: true },
    }
    world.given['POST /workshop/updates/skins/pixel-desk/accept'] = { status: 200, body: { status: 'updated', key: 'pixel-desk', version: '1.1.0', copy_key: 'pixel-desk-mine' } }
    const page = await open()
    await userEvent.click(within(page).getByRole('button', { name: 'Update' }))
    const dialog = await screen.findByTestId('skin-update')
    expect(await within(dialog).findByText(/From version 1\.0\.0 to 1\.1\.0/)).toBeInTheDocument()
    expect(within(dialog).getByRole('checkbox', { name: 'Keep what I changed here as a copy' })).toBeChecked()
    await userEvent.click(within(screen.getByRole('dialog', { name: 'Update Pixel desk' })).getByRole('button', { name: 'Update' }))
    await waitFor(() => expect(calls('POST', '/workshop/updates/skins/pixel-desk/accept')).toHaveLength(1))
    expect(calls('POST', '/workshop/updates/skins/pixel-desk/accept')[0].body).toEqual({ keep_mine: true, expected_version: '1.1.0' })
    expect(await within(dialog).findByText('Updated. Your changes are kept as the skin pixel-desk-mine.')).toBeInTheDocument()
  })
})
