/**
 * The Card shop after the review: what an entry reads and presses is shown from its checked file and not from the words of
 * the catalog, a file that cannot be used is said, replacing an own connection that loses fields waits for a word, an own
 * connection by a stranger is not taken along unasked, and the update dialog shows how a button asks (KARTEN-14, KARTEN-15).
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { NoticeList } from '../../../components/NoticeDrawer'
import { calls, entry, failure, renderWith, reset, STATE_ON, stub, world } from '../../../test/shopWorld'
import { ShopTab } from './ShopTab'

const PATH = '/workshop/entries/123/queue-size'
/** What the catalog claims in the list: a card that only reads. */
const listed = entry({ class: 'read', buttons: [], reads: [], verified: false })
const WIPE = { label: { en: 'Wipe' }, method: 'DELETE', path: '/api/wipe' }
const DOC = (over = {}) => ({ type: 'card', id: 'card:queue-size', slug: 'queue-size', name: 'Queue size', requires: ['sonarr'], buttons: [], form: 'value', problems: [], exists: false, same: false, ...over })
const TRUTH = (over = {}) => entry({ class: 'buttons', buttons: [WIPE], verified: true, claims_differ: ['class', 'buttons'], ...over })

function serve(detail: Record<string, unknown> = {}, check: Record<string, unknown> = {}) {
  world.given[`GET ${PATH}`] = { status: 200, body: { ...TRUTH(), readme: 'Story.', changelog: '1.0.0: first', files_warning: null, offered_integrations: [], ...detail } }
  world.given[`POST ${PATH}/install/check`] = { status: 200, body: { entry: TRUTH(), ok: true, documents: [DOC()], missing_integrations: [], offered_integrations: [], risk_acknowledged: true, ...check } }
  world.given[`POST ${PATH}/install`] = { status: 201, body: { slug: 'queue-size', integration: null, missing_integrations: [], place_url: '/system/custom-cards' } }
}

async function open() {
  renderWith(<ShopTab />)
  await userEvent.click(await screen.findByText('Queue size'))
  return await screen.findByTestId('shop-detail')
}

const installDialog = async () => {
  const page = await open()
  await userEvent.click(within(page).getByRole('button', { name: 'Install' }))
  return await screen.findByRole('dialog', { name: 'Install Queue size' })
}

beforeEach(() => {
  localStorage.clear()
  reset([listed], STATE_ON)
  serve()
  stub()
})
afterEach(() => vi.unstubAllGlobals())

describe('what the page shows is read from the file', () => {
  it('karten14 review: the buttons and the class come from the checked file and the page says where the catalog differs', async () => {
    const page = await open()
    expect(await within(page).findByTestId('shop-buttons')).toHaveTextContent('Wipe DELETE /api/wipe')
    expect(within(page).getByText('Has buttons')).toBeInTheDocument()
    expect(within(page).queryByText('Only reads')).toBeNull()
    expect(within(page).getByTestId('shop-claims-differ')).toHaveTextContent('its class, its buttons')
  })

  it('karten14 review: nothing is claimed while the file is being fetched', async () => {
    world.given[`GET ${PATH}`] = () => ({ status: 200, body: {} })
    let release: () => void = () => undefined
    const slow = new Promise<void>((resolve) => (release = resolve))
    const real = globalThis.fetch
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith(PATH) && (init?.method ?? 'GET') === 'GET') await slow
      return real(input, init)
    })
    serve()
    const page = await open()
    expect(within(page).getByTestId('shop-acts-loading')).toBeInTheDocument()
    expect(within(page).queryByTestId('shop-buttons')).toBeNull()
    expect(within(page).queryByText('Only reads')).toBeNull()
    release()
    expect(await within(page).findByTestId('shop-buttons')).toBeInTheDocument()
  })

  it('karten14 review: a file that cannot be read shows no class and no buttons, and says why', async () => {
    serve({ class: 'unknown', reads: [], buttons: [], verified: false, claims_differ: [], files_warning: { code: 'type_mismatch', message: 'The catalog calls this entry a card.' } })
    const page = await open()
    expect(await within(page).findByTestId('shop-unchecked')).toBeInTheDocument()
    expect(within(page).getByText('Not checked')).toBeInTheDocument()
    expect(within(page).queryByTestId('shop-buttons')).toBeNull()
    expect(within(page).getByTestId('shop-files-warning')).toHaveTextContent('The file is not what the catalog says it is')
  })

  it('karten14 review: a text that could not be fetched is said, and the rest of the page stays', async () => {
    serve({ readme: null, changelog: null, files_warning: { code: 'github_unreachable', message: 'GitHub cannot be reached.' } })
    const page = await open()
    expect(await within(page).findByTestId('shop-files-warning')).toHaveTextContent('GitHub cannot be reached. Cards you installed keep working.')
    expect(within(page).getByTestId('shop-buttons')).toHaveTextContent('Wipe')
  })

  it('karten14 review: when the entry cannot be fetched at all the page claims nothing', async () => {
    world.given[`GET ${PATH}`] = failure(502, 'github_unreachable')
    const page = await open()
    expect(await within(page).findByTestId('shop-unchecked')).toBeInTheDocument()
    expect(within(page).queryByText('Only reads')).toBeNull()
  })

  it('karten14 review: the check before installing shows the buttons of the file', async () => {
    const dialog = await installDialog()
    expect(await within(dialog).findByTestId('install-acts')).toHaveTextContent('Wipe DELETE /api/wipe')
    expect(within(dialog).getByTestId('shop-claims-differ')).toBeInTheDocument()
  })
})

describe('replacing an own connection that loses fields', () => {
  const LAMP = (over = {}) => ({ type: 'integration', id: 'integration:lamp', short: 'lamp', name: 'Lamp driver', requires: [], buttons: [], form: null, problems: [], exists: true, same: false, dropped_fields: ['token_id'], ...over })

  const replaceDialog = async (document = LAMP()) => {
    serve({}, { documents: [document] })
    const dialog = await installDialog()
    await userEvent.click(await within(dialog).findByRole('radio', { name: 'Replace' }))
    return dialog
  }

  it('karten14 review: the fields are named and Install waits for a word that the values are lost', async () => {
    const dialog = await replaceDialog()
    expect(within(dialog).getByTestId('install-dropped')).toHaveTextContent('token_id')
    expect(within(dialog).getByRole('button', { name: 'Install' })).toBeDisabled()
    await userEvent.click(within(dialog).getByRole('checkbox', { name: 'I understand that these values are lost' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Install' }))
    await waitFor(() => expect(calls('POST', `${PATH}/install`)).toHaveLength(1))
    expect(calls('POST', `${PATH}/install`)[0].body).toMatchObject({ choices: { 'integration:lamp': 'replace' }, confirm_dropped: true })
  })

  it('karten14 review: a copy loses nothing and asks nothing', async () => {
    serve({}, { documents: [LAMP()] })
    const dialog = await installDialog()
    await userEvent.click(await within(dialog).findByRole('radio', { name: 'Import as copy' }))
    expect(within(dialog).queryByTestId('install-dropped')).toBeNull()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Install' }))
    await waitFor(() => expect(calls('POST', `${PATH}/install`)).toHaveLength(1))
    expect(calls('POST', `${PATH}/install`)[0].body).toMatchObject({ confirm_dropped: false })
  })

  it('karten14 review: replacing without dropped fields asks nothing more', async () => {
    const dialog = await replaceDialog(LAMP({ dropped_fields: [] }))
    expect(within(dialog).queryByTestId('install-dropped')).toBeNull()
    expect(within(dialog).getByRole('button', { name: 'Install' })).toBeEnabled()
  })

  it('karten14 review: the server refusing without the word is said in the interface language', async () => {
    const dialog = await replaceDialog()
    world.given[`POST ${PATH}/install`] = failure(409, 'dropped_not_confirmed', 'x', { documents: [] })
    await userEvent.click(within(dialog).getByRole('checkbox', { name: 'I understand that these values are lost' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Install' }))
    expect(await within(dialog).findByTestId('install-error')).toHaveTextContent('Confirm first that the stored values may be thrown away.')
  })
})

describe('an own connection that comes along', () => {
  const stranger = entry({ id: '9/lamp', author_id: '9', slug: 'lamp', name: 'Lamp driver', type: 'integration', requires: [], reads: [], author: { id: '9', login: 'stranger' } })

  it('karten14 review: one by another author names the author, is not ticked and is taken only when ticked', async () => {
    serve({}, { offered_integrations: [stranger] })
    const dialog = await installDialog()
    const take = await within(dialog).findByRole('checkbox', { name: 'Also add the integration Lamp driver by stranger' })
    expect(take).not.toBeChecked()
    expect(within(dialog).getByTestId('install-offered')).toHaveTextContent('By someone other than the author of this card')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Install' }))
    await waitFor(() => expect(calls('POST', `${PATH}/install`)).toHaveLength(1))
    expect(calls('POST', `${PATH}/install`)[0].body).toMatchObject({ with_integrations: [] })
  })

  it('karten14 review: an unticked one that would lose fields asks for no word, and a ticked one does', async () => {
    const taken = { type: 'integration', id: 'integration:lamp', short: 'lamp', name: 'Lamp driver', requires: [], buttons: [], form: null, problems: [], exists: true, same: false, dropped_fields: ['token_id'] }
    serve({}, { offered_integrations: [stranger], documents: [DOC(), taken] })
    const dialog = await installDialog()
    await userEvent.click(await within(dialog).findByRole('radio', { name: 'Replace' }))
    expect(within(dialog).queryByTestId('install-dropped')).toBeNull()
    await userEvent.click(within(dialog).getByRole('checkbox', { name: 'Also add the integration Lamp driver by stranger' }))
    expect(within(dialog).getByTestId('install-dropped')).toHaveTextContent('token_id')
  })

  it('karten14 review: ticking it sends it', async () => {
    serve({}, { offered_integrations: [stranger] })
    const dialog = await installDialog()
    await userEvent.click(await within(dialog).findByRole('checkbox', { name: 'Also add the integration Lamp driver by stranger' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Install' }))
    await waitFor(() => expect(calls('POST', `${PATH}/install`)).toHaveLength(1))
    expect(calls('POST', `${PATH}/install`)[0].body).toMatchObject({ with_integrations: ['9/lamp'] })
  })
})

describe('the update dialog', () => {
  const asking = { id: 'wipe', label: { en: 'Wipe' }, method: 'DELETE', path: '/api/wipe', send: 'json', body: null, where: 'row', confirm: true, danger: true, asks: [{ name: 'n' }], answer: 'done' }
  const quiet = { ...asking, confirm: false, danger: false, asks: [], answer: null }
  const UPDATE = {
    slug: 'queue-size', name: { en: 'Queue size' }, ref: '123/queue-size', installed_version: '1.0.0', new_version: '1.1.0', needs_newer: false, min_nexdeck: null, changelog: null, locally_changed: false,
    permissions: { requires: { added: [], removed: [] }, requests: { added: [], changed: [], removed: [] }, buttons: { added: [], changed: [{ before: asking, after: quiet }], removed: [] } },
    buttons_to_confirm: ['wipe'], connection_changed: false, placed_on: 0,
  }

  async function updateDialog() {
    reset([entry({ installed: { slug: 'queue-size', version: '1.0.0', update: true, locally_changed: false } })], STATE_ON)
    world.given['GET /workshop/updates/queue-size'] = { status: 200, body: UPDATE }
    serve()
    const page = await open()
    await userEvent.click(within(page).getByRole('button', { name: 'Update' }))
    return await screen.findByRole('dialog', { name: 'Update Queue size' })
  }

  it('karten15 review: a button that stops asking is shown with how it asked before and after', async () => {
    const dialog = await updateDialog()
    const rights = await within(dialog).findByTestId('update-permissions')
    expect(rights).toHaveTextContent('asks first')
    expect(rights).toHaveTextContent('marked dangerous')
    expect(rights).toHaveTextContent('asks for: n')
    expect(rights).toHaveTextContent('shows the answer')
  })

  it.each([
    ['update_invalid', 'The new version cannot be read. Nothing was changed.'],
    ['too_many_cards', 'There are too many custom cards to keep a copy of yours.'],
    ['github_rejected', 'GitHub refused the request.'],
    ['type_mismatch', 'The file is not what the catalog says it is'],
  ])('karten15 review: %s is said in the interface language and not in the words of the server', async (code, text) => {
    const dialog = await updateDialog()
    world.given['POST /workshop/updates/queue-size/accept'] = failure(400, code, 'English words of the server')
    await userEvent.click(await within(dialog).findByRole('checkbox'))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Update now' }))
    const shown = await within(dialog).findByTestId('update-error')
    expect(shown).toHaveTextContent(text)
    expect(shown).not.toHaveTextContent('English words of the server')
  })
})

describe('the bell', () => {
  it('karten15 review: the words of a recall are drawn as text, whatever they contain', () => {
    render(
      <MemoryRouter>
        <NoticeList
          notices={[{ id: 1, event: 'card_recalled', level: 'error', title: '<b>Queue</b> was removed from the Card shop as harmful', body: '<script>alert(1)</script> steals data', link: '/system/custom-cards', read_at: null, created_at: '2026-10-28T10:00:00Z' }]}
        />
      </MemoryRouter>,
    )
    expect(screen.getByText('<b>Queue</b> was removed from the Card shop as harmful')).toBeInTheDocument()
    expect(screen.getByText('<script>alert(1)</script> steals data')).toBeInTheDocument()
    expect(document.querySelector('script')).toBeNull()
    expect(screen.getByRole('link', { name: 'Open' })).toHaveAttribute('href', '/system/custom-cards')
  })
})
