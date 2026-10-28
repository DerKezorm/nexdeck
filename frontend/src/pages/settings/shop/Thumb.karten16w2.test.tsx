/** W2 (Etappe 8): the thumb on the discussion of an entry, set from nexdeck in the administrator's own GitHub name. */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import de from '../../../i18n/de.json'

import { calls, entry, failure, renderWith, reset, STATE_ON, stub, world } from '../../../test/shopWorld'
import { ShopTab } from './ShopTab'

const SLUG = 'queue-size'
const THUMB = '/workshop/entries/123/queue-size/thumb'
const DISCUSSION = 'https://github.com/DerKezorm/nexdeck-workshop/discussions/4'
const SIGNED_IN = { signed_in: true, login: 'someone', github_id: '4242', until: '2027-04-30T10:00:00Z', pending: null }
const detail = (over = {}) => ({ ...entry({ discussion: DISCUSSION, ...over }), readme: null, changelog: null, files_warning: null, offered_integrations: [] })

beforeEach(() => {
  localStorage.clear()
  reset([entry({ discussion: DISCUSSION })], STATE_ON)
  stub()
  world.given[`GET /workshop/entries/123/${SLUG}`] = { status: 200, body: detail() }
})
afterEach(async () => {
  vi.unstubAllGlobals()
  await i18next.changeLanguage('en')
})

async function openDetail(name = 'Queue size') {
  renderWith(<ShopTab />)
  await userEvent.click(await screen.findByRole('button', { name }))
  return screen.findByTestId('shop-detail')
}

describe('the detail page', () => {
  it('karten16w2_detail: the thumb is a button with the catalog number; it sets the thumb, says the number is counted once a day, and takes it away again', async () => {
    world.given[`GET ${THUMB}`] = { status: 200, body: { signed_in: true, on: false } }
    world.given[`PUT ${THUMB}`] = (asked) => ({ status: 200, body: { on: asked.body?.on } })
    const page = await openDetail()
    const thumb = await within(page).findByRole('button', { name: '12 thumbs up' })
    await waitFor(() => expect(calls('GET', THUMB)).toHaveLength(1))
    expect(thumb).toHaveAttribute('aria-pressed', 'false')
    expect(within(page).queryByTestId('thumb-counted')).toBeNull()

    await userEvent.click(thumb)
    await waitFor(() => expect(thumb).toHaveAttribute('aria-pressed', 'true'))
    expect(calls('PUT', THUMB).map((one) => one.body)).toEqual([{ on: true }])
    expect(thumb).toHaveTextContent('12')
    expect(within(page).getByTestId('thumb-counted')).toHaveTextContent('Counted once a day.')

    await userEvent.click(thumb)
    await waitFor(() => expect(thumb).toHaveAttribute('aria-pressed', 'false'))
    expect(calls('PUT', THUMB).map((one) => one.body)).toEqual([{ on: true }, { on: false }])
    expect(within(page).getByRole('link', { name: 'Rate on GitHub' })).toHaveAttribute('href', DISCUSSION)
    expect(within(page).getByRole('link', { name: 'Rate on GitHub' })).toHaveAttribute('rel', 'noopener noreferrer')
    expect(within(page).getByRole('link', { name: 'Rate on GitHub' })).toHaveAttribute('target', '_blank')
  })

  it('karten16w2_detail: when the thumb is already up the button shows it pressed', async () => {
    world.given[`GET ${THUMB}`] = { status: 200, body: { signed_in: true, on: true } }
    const page = await openDetail()
    await waitFor(() => expect(within(page).getByRole('button', { name: '12 thumbs up' })).toHaveAttribute('aria-pressed', 'true'))
  })

  it('karten16w2_detail: nobody signed in: the click shows the GitHub sign-in, and the thumb goes up when GitHub has said yes', async () => {
    world.given[`GET ${THUMB}`] = { status: 200, body: { signed_in: false, on: null } }
    world.given['GET /workshop/github'] = { status: 200, body: { signed_in: false, login: null, github_id: null, until: null, pending: null } }
    world.given['POST /workshop/github/login'] = { status: 200, body: { user_code: 'WDJB-1001', verification_uri: 'https://github.com/login/device', expires_in: 900, interval: 1 } }
    world.given['POST /workshop/github/login/poll'] = { status: 200, body: { status: 'signed_in', ...SIGNED_IN } }
    world.given[`PUT ${THUMB}`] = { status: 200, body: { on: true } }
    const page = await openDetail()
    const thumb = await within(page).findByRole('button', { name: '12 thumbs up' })
    await waitFor(() => expect(calls('GET', THUMB)).toHaveLength(1))
    await userEvent.click(thumb)
    expect(await within(page).findByTestId('github-signin')).toHaveTextContent('Sign in to GitHub to put your thumb on this entry.')
    expect(calls('PUT', THUMB)).toHaveLength(0)
    await userEvent.click(within(page).getByRole('button', { name: 'Sign in to GitHub' }))
    expect(await within(page).findByTestId('github-code')).toHaveTextContent('WDJB-1001')
    await waitFor(() => expect(calls('PUT', THUMB)).toHaveLength(1), { timeout: 4000 })
    expect(calls('PUT', THUMB)[0].body).toEqual({ on: true })
    await waitFor(() => expect(thumb).toHaveAttribute('aria-pressed', 'true'))
    expect(within(page).queryByTestId('github-signin')).toBeNull()
    expect(within(page).getByTestId('thumb-counted')).toBeInTheDocument()
  })

  it('karten16w2_detail: a sign-in the server no longer knows asks for the GitHub sign-in as well', async () => {
    world.given[`GET ${THUMB}`] = { status: 200, body: { signed_in: true, on: false } }
    world.given[`PUT ${THUMB}`] = failure(409, 'github_login_needed', 'Sign in to GitHub again to go on.')
    world.given['GET /workshop/github'] = { status: 200, body: { signed_in: false, login: null, github_id: null, until: null, pending: null } }
    const page = await openDetail()
    await userEvent.click(await within(page).findByRole('button', { name: '12 thumbs up' }))
    expect(await within(page).findByTestId('github-signin')).toBeInTheDocument()
  })

  it('karten16w2_detail: without the right of the App the sentence is shown, in the viewer\'s language, and the link stays', async () => {
    i18next.addResourceBundle('de', 'translation', de, true, true)
    await i18next.changeLanguage('de')
    world.given[`GET ${THUMB}`] = { status: 200, body: { signed_in: true, on: false } }
    world.given[`PUT ${THUMB}`] = failure(403, 'github_no_discussions', 'The Workshop app may not react to discussions yet. Rate it on GitHub instead.')
    const page = await openDetail('Warteschlange')
    await userEvent.click(await within(page).findByRole('button', { name: '12 Daumen' }))
    expect(await within(page).findByTestId('thumb-note')).toHaveTextContent('Die Workshop-App darf vielleicht noch nicht auf Diskussionen reagieren. Bewerte stattdessen auf GitHub.')
    expect(within(page).getByRole('link', { name: 'Auf GitHub bewerten' })).toHaveAttribute('href', DISCUSSION)
    expect(within(page).queryByTestId('thumb-counted')).toBeNull()
  })

  it('karten16w2_detail: the reading that says the right is missing shows the sentence at once', async () => {
    world.given[`GET ${THUMB}`] = failure(403, 'github_no_discussions')
    const page = await openDetail()
    expect(await within(page).findByTestId('thumb-note')).toHaveTextContent('The Workshop app may not react to discussions yet. Rate it on GitHub instead.')
  })

  it('karten16w2_detail: an entry without a discussion has no button, only the number, and the server is not asked', async () => {
    reset([entry()], STATE_ON)
    world.given[`GET /workshop/entries/123/${SLUG}`] = { status: 200, body: detail({ discussion: null }) }
    const page = await openDetail()
    await screen.findByTestId('shop-detail')
    expect(within(page).queryByRole('button', { name: '12 thumbs up' })).toBeNull()
    expect(page).toHaveTextContent('12')
    expect(within(page).queryByRole('link', { name: 'Rate on GitHub' })).toBeNull()
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(calls('GET', THUMB)).toHaveLength(0)
  })

  it('karten16w2_detail: a discussion address that is no web address gives no button and no link', async () => {
    reset([entry({ discussion: 'javascript:alert(1)' })], STATE_ON)
    world.given[`GET /workshop/entries/123/${SLUG}`] = { status: 200, body: detail({ discussion: 'javascript:alert(1)' }) }
    const page = await openDetail()
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(within(page).queryByRole('button', { name: '12 thumbs up' })).toBeNull()
    expect(calls('GET', THUMB)).toHaveLength(0)
  })
})

describe('the tile', () => {
  it('karten16w2_tile: the thumb sets (never takes away), is filled afterwards, and the list never reads the thumb', async () => {
    world.given[`PUT ${THUMB}`] = { status: 200, body: { on: true } }
    renderWith(<ShopTab />)
    const tile = await screen.findByTestId('shop-tile-123/queue-size')
    const thumb = within(tile).getByRole('button', { name: '12 thumbs up' })
    expect(thumb).toHaveAttribute('aria-pressed', 'false')
    await userEvent.click(thumb)
    await waitFor(() => expect(thumb).toHaveAttribute('aria-pressed', 'true'))
    await userEvent.click(thumb)
    expect(calls('PUT', THUMB).map((one) => one.body)).toEqual([{ on: true }, { on: true }])
    expect(calls('GET', THUMB)).toHaveLength(0)
    expect(within(tile).getByTestId('thumb-counted')).toBeInTheDocument()
    expect(screen.queryByTestId('shop-detail')).toBeNull()
  })

  it('karten16w2_tile: nobody signed in: the thumb opens the detail page', async () => {
    world.given[`PUT ${THUMB}`] = failure(409, 'github_login_needed', 'Sign in to GitHub again to go on.')
    world.given[`GET ${THUMB}`] = { status: 200, body: { signed_in: false, on: null } }
    world.given['GET /workshop/github'] = { status: 200, body: { signed_in: false, login: null, github_id: null, until: null, pending: null } }
    renderWith(<ShopTab />)
    const tile = await screen.findByTestId('shop-tile-123/queue-size')
    await userEvent.click(within(tile).getByRole('button', { name: '12 thumbs up' }))
    expect(await screen.findByTestId('shop-detail')).toBeInTheDocument()
  })

  it('karten16w2_tile: without a discussion the tile has the number and no button for it; the name opens the detail', async () => {
    reset([entry()], STATE_ON)
    world.given[`GET /workshop/entries/123/${SLUG}`] = { status: 200, body: detail({ discussion: null }) }
    renderWith(<ShopTab />)
    const tile = await screen.findByTestId('shop-tile-123/queue-size')
    expect(within(tile).getByRole('img', { name: '12 thumbs up' })).toBeInTheDocument()
    expect(within(tile).getAllByRole('button')).toHaveLength(1)
    await userEvent.click(within(tile).getByRole('button', { name: 'Queue size' }))
    expect(await screen.findByTestId('shop-detail')).toBeInTheDocument()
  })

  it('karten16w2_tile: the thumb does not open the detail page by itself', async () => {
    world.given[`PUT ${THUMB}`] = { status: 200, body: { on: true } }
    renderWith(<ShopTab />)
    const tile = await screen.findByTestId('shop-tile-123/queue-size')
    await userEvent.click(within(tile).getByRole('button', { name: '12 thumbs up' }))
    await waitFor(() => expect(calls('PUT', THUMB)).toHaveLength(1))
    expect(screen.queryByTestId('shop-detail')).toBeNull()
  })
})
