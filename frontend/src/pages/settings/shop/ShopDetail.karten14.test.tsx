/**
 * The page of one entry of the Card shop: what it says, the preview with the administrator's data, installing with the
 * risk notice, the own integrations on offer, a taken name, a bad checksum, a version that is too new, and placing the
 * card on a board afterwards (KARTEN-14 AC-5 to AC-9, AC-14, EC-1 to EC-4).
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { calls, entry, failure, renderWith, reset, STATE_ON, stub, world } from '../../../test/shopWorld'
import { ShopTab } from './ShopTab'

const PATH = '/workshop/entries/123/queue-size'

const lamp = entry({ id: '9/lamp', author_id: '9', slug: 'lamp', name: 'Lamp driver', type: 'integration', requires: [], reads: [], fits: true, connections: [] })
const base = entry({ id: '5/base', author_id: '5', slug: 'base', name: 'Queue base', thumbs: 1 })
const queue = (over = {}) =>
  entry({
    based_on: '5/base',
    reads: [{ kind: 'sonarr', path: '/api/v3/queue' }],
    buttons: [{ label: { en: 'Clear queue' }, method: 'DELETE', path: '/api/v3/queue/bulk' }],
    discussion: 'https://github.com/DerKezorm/nexdeck-workshop/discussions/4',
    ...over,
  })

const SHOWN = { status: 'ok', primary: { value: 7, text: '7', format: 'number', label: 'Waiting' }, secondary: [], items: [], meta: { custom: true } }
const DOC = (over = {}) => ({ type: 'card', id: 'card:queue-size', slug: 'queue-size', name: 'Queue size', requires: ['sonarr'], buttons: [], form: 'value', problems: [], exists: false, same: false, ...over })
const CHECK = (over = {}) => ({ entry: queue(), ok: true, documents: [DOC()], missing_integrations: [], offered_integrations: [], risk_acknowledged: false, ...over })

function serve(extra: Record<string, unknown> = {}) {
  world.given[`GET ${PATH}`] = { status: 200, body: { ...queue(), readme: 'A longer story about the card.', changelog: '1.2.0: faster\n1.1.0: first version', offered_integrations: [], ...extra } }
  world.given[`POST ${PATH}/preview`] = { status: 200, body: SHOWN }
  world.given[`POST ${PATH}/install/check`] = { status: 200, body: CHECK() }
  world.given[`POST ${PATH}/install`] = { status: 201, body: { slug: 'queue-size', integration: null, missing_integrations: [], place_url: '/system/custom-cards' } }
}

async function open(name = 'Queue size') {
  renderWith(<ShopTab />)
  await userEvent.click(await screen.findByText(name))
  return await screen.findByTestId('shop-detail')
}

beforeEach(() => {
  localStorage.clear()
  reset([queue(), base, lamp], STATE_ON)
  serve()
  stub()
})
afterEach(() => vi.unstubAllGlobals())

describe('what the page says', () => {
  it('karten14 ac5: description, list of changes, where it is based, what it reads and its buttons', async () => {
    const page = await open()
    expect(within(page).getByText('Shows how many episodes wait in the queue.')).toBeInTheDocument()
    expect(await within(page).findByTestId('shop-changelog')).toHaveTextContent('1.2.0: faster')
    expect(within(page).getByRole('button', { name: 'Queue base' })).toBeInTheDocument()
    expect(within(page).getByTestId('shop-reads')).toHaveTextContent('Sonarr /api/v3/queue')
    expect(within(page).getByTestId('shop-buttons')).toHaveTextContent('Clear queue DELETE /api/v3/queue/bulk')
  })

  it('karten14 ac5: "based on" opens the entry it is based on', async () => {
    const page = await open()
    await userEvent.click(within(page).getByRole('button', { name: 'Queue base' }))
    expect(await screen.findByRole('heading', { name: 'Queue base' })).toBeInTheDocument()
  })

  it('karten14 ac14: author, thumbs, version, license and the day it last changed', async () => {
    const page = await open()
    const facts = within(page).getAllByRole('definition').map((one) => (one.textContent ?? '').trim())
    expect(facts).toEqual(['someone', '12 · Rate on GitHub', '1.2.0', 'MIT', 'October 20, 2026', 'Queue base'])
  })

  it('karten14 ac14: a license the catalog does not name is said to be not stated', async () => {
    reset([queue({ license: null })], STATE_ON)
    serve()
    const page = await open()
    expect(within(page).getByText('Not stated')).toBeInTheDocument()
  })

  it('karten14 ac5: a description with markup is drawn as text', async () => {
    reset([queue({ description: '<img src=x onerror=alert(1)> hello' })], STATE_ON)
    serve()
    const page = await open()
    expect(within(page).getByText('<img src=x onerror=alert(1)> hello')).toBeInTheDocument()
    expect(page.querySelector('img[src="x"]')).toBeNull()
  })
})

describe('the preview', () => {
  it('karten14 ac6: "Preview with my data" draws the card with a connection and installs nothing', async () => {
    const page = await open()
    await userEvent.click(within(page).getByRole('button', { name: 'Preview with my data' }))
    const drawn = await within(page).findByTestId('shop-preview', {}, { timeout: 20000 })
    expect(drawn).toHaveTextContent('Waiting')
    expect(calls('POST', `${PATH}/preview`)[0].body).toEqual({ integration_id: 3 })
    expect(calls('POST', `${PATH}/install`)).toHaveLength(0)
    expect(calls('POST', `${PATH}/install/check`)).toHaveLength(0)
  })

  it('karten14 ac6: without a fitting connection the preview cannot be asked for', async () => {
    localStorage.setItem('nexdeck.shop.fits', '0')
    reset([queue({ connections: [], fits: false })], STATE_ON)
    serve()
    const page = await open()
    expect(within(page).getByRole('button', { name: 'Preview with my data' })).toBeDisabled()
    expect(within(page).getByText('A preview needs a connection of the kind this card reads from.')).toBeInTheDocument()
  })

  it('karten14 ac6: a refused preview says why', async () => {
    world.given[`POST ${PATH}/preview`] = failure(409, 'checksum_mismatch', 'The file does not match the checksum of the catalog.')
    const page = await open()
    await userEvent.click(within(page).getByRole('button', { name: 'Preview with my data' }))
    expect(await within(page).findByTestId('shop-preview-failed')).toHaveTextContent('does not match the checksum')
  })
})

describe('with the keyboard', () => {
  it('karten14 ac5: a tile is reached with Tab and opened with Enter, and Escape closes the install dialog', async () => {
    renderWith(<ShopTab />)
    const tile = await screen.findByTestId('shop-tile-123/queue-size')
    const button = within(tile).getByRole('button', { name: 'Queue size' })
    button.focus()
    expect(button).toHaveFocus()
    await userEvent.keyboard('{Enter}')
    const page = await screen.findByTestId('shop-detail')
    await userEvent.click(within(page).getByRole('button', { name: 'Install' }))
    expect(await screen.findByRole('dialog', { name: 'Install Queue size' })).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })
})

describe('on a phone', () => {
  it('karten14 ec10: "Install" is a big button that fills the width on a narrow screen', async () => {
    const page = await open()
    const install = within(page).getByRole('button', { name: 'Install' })
    expect(install.className).toContain('max-sm:w-full')
    expect(install.className).toContain('max-sm:h-12')
    expect(within(page).getByTestId('shop-actions').className).toContain('max-sm:flex-col')
  })
})

describe('installing', () => {
  const installDialog = async () => {
    const page = await open()
    await userEvent.click(within(page).getByRole('button', { name: 'Install' }))
    return await screen.findByRole('dialog', { name: 'Install Queue size' })
  }

  it('karten14 ac9: before the first install the dialog says once that cards come from strangers and runs at your own risk', async () => {
    const dialog = await installDialog()
    expect(await within(dialog).findByTestId('install-risk')).toHaveTextContent('Cards from the Card shop come from strangers')
    expect(within(dialog).getByRole('button', { name: 'Install' })).toBeDisabled()
    await userEvent.click(within(dialog).getByRole('checkbox', { name: /at my own risk/ }))
    expect(within(dialog).getByRole('button', { name: 'Install' })).toBeEnabled()
  })

  it('karten14 ac9: an administrator who has read it is not asked again', async () => {
    world.given[`POST ${PATH}/install/check`] = { status: 200, body: CHECK({ risk_acknowledged: true }) }
    const dialog = await installDialog()
    await waitFor(() => expect(within(dialog).getByRole('button', { name: 'Install' })).toBeEnabled())
    expect(within(dialog).queryByTestId('install-risk')).toBeNull()
  })

  it('karten14 ac7: Install sends the word about the risk, then offers "Place on a board"', async () => {
    const dialog = await installDialog()
    await userEvent.click(await within(dialog).findByRole('checkbox', { name: /at my own risk/ }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Install' }))
    await waitFor(() => expect(calls('POST', `${PATH}/install`)).toHaveLength(1))
    expect(calls('POST', `${PATH}/install`)[0].body).toEqual({ choices: {}, with_integrations: [], accept_risk: true, confirm_dropped: false })
    expect(await screen.findByRole('dialog', { name: 'Place on a board' })).toBeInTheDocument()
  })

  it('karten14 ac8: an own integration that is missing is offered along, and unticking it leaves it out', async () => {
    world.given[`POST ${PATH}/install/check`] = { status: 200, body: CHECK({ risk_acknowledged: true, offered_integrations: [lamp] }) }
    const dialog = await installDialog()
    const take = await within(dialog).findByRole('checkbox', { name: 'Also add the integration Lamp driver by someone' })
    expect(take).toBeChecked()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Install' }))
    await waitFor(() => expect(calls('POST', `${PATH}/install`)).toHaveLength(1))
    expect(calls('POST', `${PATH}/install`)[0].body).toMatchObject({ with_integrations: ['9/lamp'] })
  })

  it('karten14 ac8: unticked, the integration is not sent', async () => {
    world.given[`POST ${PATH}/install/check`] = { status: 200, body: CHECK({ risk_acknowledged: true, offered_integrations: [lamp] }) }
    const dialog = await installDialog()
    await userEvent.click(await within(dialog).findByRole('checkbox', { name: 'Also add the integration Lamp driver by someone' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Install' }))
    await waitFor(() => expect(calls('POST', `${PATH}/install`)).toHaveLength(1))
    expect(calls('POST', `${PATH}/install`)[0].body).toMatchObject({ with_integrations: [] })
  })

  it('karten14 ec1: a checksum that does not match stops the install, says why, and nothing is placed', async () => {
    world.given[`POST ${PATH}/install/check`] = { status: 200, body: CHECK({ risk_acknowledged: true }) }
    world.given[`POST ${PATH}/install`] = failure(409, 'checksum_mismatch', 'The file does not match.')
    const dialog = await installDialog()
    await waitFor(() => expect(within(dialog).getByRole('button', { name: 'Install' })).toBeEnabled())
    await userEvent.click(within(dialog).getByRole('button', { name: 'Install' }))
    expect(await within(dialog).findByTestId('install-error')).toHaveTextContent('The file does not match the checksum of the catalog. Nothing was installed.')
    expect(screen.queryByRole('dialog', { name: 'Place on a board' })).toBeNull()
  })

  it('karten14 ec1: a checksum that fails already at the check is said at once and nothing can be installed', async () => {
    world.given[`POST ${PATH}/install/check`] = failure(409, 'checksum_mismatch')
    const dialog = await installDialog()
    expect(await within(dialog).findByTestId('install-check-failed')).toHaveTextContent('Nothing was installed.')
    expect(within(dialog).getByRole('button', { name: 'Install' })).toBeDisabled()
  })

  it('karten14 ec4: a short name that is taken asks for a choice, and the choice goes with the install', async () => {
    world.given[`POST ${PATH}/install/check`] = { status: 200, body: CHECK({ risk_acknowledged: true, documents: [DOC({ exists: true })] }) }
    const dialog = await installDialog()
    const conflict = await within(dialog).findByTestId('install-conflict-card:queue-size')
    expect(within(dialog).getByRole('button', { name: 'Install' })).toBeDisabled()
    await userEvent.click(within(conflict).getByRole('radio', { name: 'Import as copy' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Install' }))
    await waitFor(() => expect(calls('POST', `${PATH}/install`)).toHaveLength(1))
    expect(calls('POST', `${PATH}/install`)[0].body).toMatchObject({ choices: { 'card:queue-size': 'copy' } })
  })
})

describe('what the page offers instead of "Install"', () => {
  it('karten14 ec2: an entry that needs a newer nexdeck says so and cannot be installed', async () => {
    reset([queue({ needs_newer: true, min_nexdeck: '0.99.0' })], STATE_ON)
    serve()
    const page = await open()
    expect(within(page).getByRole('button', { name: 'Needs nexdeck 0.99.0' })).toBeDisabled()
    expect(within(page).queryByRole('button', { name: 'Install' })).toBeNull()
  })

  it('karten14 ec3: an installed entry says "Installed" with its version and offers "Place on a board", not "Install"', async () => {
    reset([queue({ installed: { slug: 'queue-size', version: '1.1.0', update: false, locally_changed: false } })], STATE_ON)
    serve()
    const page = await open()
    expect(within(page).getByTestId('shop-installed-version')).toHaveTextContent('Installed, version 1.1.0')
    expect(within(page).queryByRole('button', { name: 'Install' })).toBeNull()
    expect(within(page).getByRole('button', { name: 'Place on a board' })).toBeEnabled()
  })

  it('karten14 ec3: a removed entry cannot be installed and says why it left', async () => {
    reset([queue({ removed: { level: 'not_useful', reason: 'Superseded by another card.', at: '2026-10-27T10:00:00Z' }, installed: { slug: 'queue-size', version: '1.1.0', update: false, locally_changed: false } })], STATE_ON)
    serve()
    const page = await open()
    expect(within(page).getByTestId('shop-removed-note')).toHaveTextContent('Removed from the Card shop: Superseded by another card.')
    expect(within(page).queryByRole('button', { name: 'Install' })).toBeNull()
  })
})

describe('an entry that is gone', () => {
  it('karten14 ec3: opened through "based on", a removed entry that is not installed has no "Install" and no preview', async () => {
    const gone = entry({ id: '5/old', author_id: '5', slug: 'old', name: 'Old one', removed: { level: 'harmful', reason: 'It deletes things.', at: '2026-10-27T10:00:00Z' } })
    reset([queue({ based_on: '5/old' }), gone], STATE_ON)
    serve()
    const page = await open()
    await userEvent.click(within(page).getByRole('button', { name: 'Old one' }))
    const other = await screen.findByRole('heading', { name: 'Old one' })
    const here = other.closest('[data-testid="shop-detail"]') as HTMLElement
    expect(within(here).getByTestId('shop-removed-note')).toHaveAttribute('data-level', 'harmful')
    expect(within(here).queryByRole('button', { name: 'Install' })).toBeNull()
    expect(within(here).queryByRole('button', { name: 'Preview with my data' })).toBeNull()
  })
})

describe('placing the installed card', () => {
  it('karten14 ac7: "Place on a board" puts the card on the first page of the chosen board', async () => {
    reset([queue({ installed: { slug: 'queue-size', version: '1.2.0', update: false, locally_changed: false } })], STATE_ON)
    serve()
    world.other = (asked) => {
      if (asked.method === 'GET' && asked.url === '/boards') return { status: 200, body: [{ id: 1, slug: 'home', name: 'Home', permission: 'owner', pages: [{ id: 11, name: 'Main', slug: 'main', widget_count: 0 }] }] }
      if (asked.method === 'GET' && asked.url === '/cards/library') return { status: 200, body: { cards: [{ slug: 'queue-size', name: 'Queue size', form: 'value', version: '1.2.0', requires: [], fits: [{ id: 3, name: 'Sonarr home', kind: 'sonarr' }] }] } }
      if (asked.method === 'POST' && asked.url === '/pages/11/widgets') return { status: 201, body: { widget: { id: 5 } } }
      return undefined
    }
    const page = await open()
    await userEvent.click(within(page).getByRole('button', { name: 'Place on a board' }))
    const dialog = await screen.findByRole('dialog', { name: 'Place on a board' })
    await waitFor(() => expect(within(dialog).getByRole('button', { name: 'Place on a board' })).toBeEnabled())
    await userEvent.click(within(dialog).getByRole('button', { name: 'Place on a board' }))
    await waitFor(() => expect(calls('POST', '/pages/11/widgets')).toHaveLength(1))
    expect(calls('POST', '/pages/11/widgets')[0].body).toEqual({ kind: 'custom.value', title: 'Queue size', integration_id: 3, options: { card: 'queue-size' } })
    expect(await within(dialog).findByText('The card is on the board.')).toBeInTheDocument()
  })
})
