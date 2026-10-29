/**
 * "Start from an example" (KARTEN-19 AC-4, EC-1): the examples of the Card shop in the card editor and in the editor of an
 * own connection. The server is replaced; what it was asked is kept.
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuth } from '../../stores/auth'
import { calls, entry, failure, githubWasAsked, renderWith, reset, STATE_OFF, STATE_ON, stub, world } from '../../test/shopWorld'
import { memoryStorage } from '../../test/cardEditor'
import { parseCard, readAt } from '../../lib/cardDocument'
import { CardEditorPage } from './CardEditorPage'
import { NEW_CARD } from './templates'
import { useCardEditor } from './store'
import { IntegrationEditorPage } from '../integrationEditor/IntegrationEditorPage'
import { useIntegrationEditor } from '../integrationEditor/store'

const CARD = `nexdeck-card: 1
slug: queue-size
name: Queue size
version: "1.0.0"
requires: [sonarr]
requests:
  - id: queue
    path: /api/v3/queue
form: value
value: totalRecords
`

const TEMPLATE = `nexdeck: integration
short: example
name: Example
fields: []
auth:
  type: none
test: /api/status
`

const WALLABAG = `nexdeck: integration
short: wallabag
name: Wallabag
fields: []
auth:
  type: none
test: /api/info
`

const example = (over: Record<string, unknown> = {}) => entry({ starter: true, ...over })
const radarr = () => example({ id: '123/radarr-missing', slug: 'radarr-missing', name: { en: 'Missing movies' }, description: 'Counts the movies Radarr still waits for.', picture_version: '1.0.0' })
const wallabag = () =>
  example({
    id: '123/wallabag', slug: 'wallabag', type: 'integration', name: { en: 'Wallabag' }, description: 'Reads the articles you saved in Wallabag.', version: '',
    requires: [], fits: true, connections: [],
  })

function serve() {
  world.other = (asked) => {
    if (asked.method === 'GET' && asked.url === '/cards/sources') return { status: 200, body: [] }
    if (asked.method === 'GET' && asked.url === '/integrations') return { status: 200, body: [] }
    if (asked.method === 'GET' && asked.url === '/own-integrations/template') return { status: 200, body: { yaml: TEMPLATE } }
    if (asked.method === 'POST' && (asked.url === '/cards/check' || asked.url === '/own-integrations/check')) return { status: 200, body: { ok: true } }
    if (asked.method === 'GET' && asked.url.startsWith('/cards/')) return { status: 200, body: [] }
    return undefined
  }
  world.given['GET /workshop/examples/123/radarr-missing'] = { status: 200, body: { id: '123/radarr-missing', type: 'card', slug: 'radarr-missing', text: CARD.replace('slug: queue-size', 'slug: radarr-missing') } }
  world.given['GET /workshop/examples/123/wallabag'] = { status: 200, body: { id: '123/wallabag', type: 'integration', slug: 'wallabag-2', text: WALLABAG } }
}

function newCard() {
  return renderWith(
    <Routes>
      <Route path="/system/custom-cards/new" element={<CardEditorPage />} />
      <Route path="*" element={<p>Somewhere else</p>} />
    </Routes>,
    '/system/custom-cards/new',
  )
}

function newIntegration() {
  return renderWith(
    <Routes>
      <Route path="/system/custom-cards/integrations/new" element={<IntegrationEditorPage />} />
      <Route path="*" element={<p>Somewhere else</p>} />
    </Routes>,
    '/system/custom-cards/integrations/new',
  )
}

const openList = async () => {
  await userEvent.click(await screen.findByRole('button', { name: 'Start from an example' }))
  return screen.findByRole('dialog')
}

beforeEach(() => {
  vi.stubGlobal('localStorage', memoryStorage())
  useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin' } as never, loading: false })
  useCardEditor.setState({ now: () => Date.now() })
  reset([radarr(), wallabag(), entry(), example({ id: '123/gone', slug: 'gone', removed: { level: 'harmful', reason: 'No.', at: '2026-10-28T10:00:00Z' } })], STATE_ON)
  stub()
  serve()
})
afterEach(async () => {
  vi.unstubAllGlobals()
  await i18next.changeLanguage('en')
})

describe('karten19 ac4: the card editor', () => {
  it('lists the examples of the kind being made, with name, description and picture', async () => {
    newCard()
    const dialog = await openList()
    const row = await within(dialog).findByTestId('example-123/radarr-missing')
    expect(within(row).getByText('Missing movies')).toBeInTheDocument()
    expect(within(row).getByText('Counts the movies Radarr still waits for.')).toBeInTheDocument()
    expect(row.querySelector('img')!.getAttribute('src')).toMatch(/\/workshop\/entries\/123\/queue-size\/image\/(light|dark)\?v=1\.0\.0$/)
    // Not a connection, not an entry that is no example, not a removed one.
    expect(within(dialog).queryByText('Wallabag')).not.toBeInTheDocument()
    expect(within(dialog).queryByText('Queue size')).not.toBeInTheDocument()
    expect(within(dialog).queryByTestId('example-123/gone')).not.toBeInTheDocument()
  })

  it('opens the choice as a new draft with the checked text, installs and saves nothing', async () => {
    newCard()
    expect(useCardEditor.getState().text).toBe(NEW_CARD)
    const dialog = await openList()
    await userEvent.click(within(await within(dialog).findByTestId('example-123/radarr-missing')).getByRole('button', { name: 'Start from this' }))
    await waitFor(() => expect(useCardEditor.getState().text).not.toBe(NEW_CARD))
    const state = useCardEditor.getState()
    expect(calls('GET', '/workshop/examples/123/radarr-missing')).toHaveLength(1)
    expect(state.slug).toBeNull()
    expect(state.savedText).toBeNull()
    const read = parseCard(state.text)
    expect(read.ok && readAt(read.card, ['slug'])).toBe('radarr-missing')
    expect(read.ok && readAt(read.card, ['name'])).toBe('Queue size')
    expect(world.asked.filter((one) => one.method !== 'GET' && !one.url.endsWith('/check') && !one.url.endsWith('/preview'))).toEqual([])
    // The bar is gone once the card is not the empty one any more, and the dialog is closed.
    expect(screen.queryByTestId('example-start')).not.toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('takes the short name the server found free, not the one of the example', async () => {
    world.given['GET /workshop/examples/123/radarr-missing'] = { status: 200, body: { id: '123/radarr-missing', type: 'card', slug: 'radarr-missing-2', text: CARD.replace('slug: queue-size', 'slug: radarr-missing') } }
    newCard()
    const dialog = await openList()
    await userEvent.click(within(await within(dialog).findByTestId('example-123/radarr-missing')).getByRole('button', { name: 'Start from this' }))
    await waitFor(() => expect(useCardEditor.getState().text).not.toBe(NEW_CARD))
    const read = parseCard(useCardEditor.getState().text)
    expect(read.ok && readAt(read.card, ['slug'])).toBe('radarr-missing-2')
  })

  it('says it when no connection fits the card, and still offers it', async () => {
    reset([radarr(), example({ id: '123/other', slug: 'other', name: { en: 'Fits' }, fits: true })], STATE_ON)
    world.catalog.entries[0] = { ...radarr(), fits: false }
    serve()
    newCard()
    const dialog = await openList()
    const row = await within(dialog).findByTestId('example-123/radarr-missing')
    expect(within(row).getByTestId('example-no-connection')).toHaveTextContent('no connection this card can read from yet')
    expect(within(row).getByRole('button', { name: 'Start from this' })).toBeEnabled()
    expect(within(await within(dialog).findByTestId('example-123/other')).queryByTestId('example-no-connection')).not.toBeInTheDocument()
  })

  it('leaves the editor as it was when the example cannot be opened', async () => {
    world.given['GET /workshop/examples/123/radarr-missing'] = failure(409, 'checksum_mismatch', 'The file does not match the checksum of the catalog.')
    newCard()
    const dialog = await openList()
    await userEvent.click(within(await within(dialog).findByTestId('example-123/radarr-missing')).getByRole('button', { name: 'Start from this' }))
    expect(await within(dialog).findByTestId('example-trouble')).toHaveTextContent('This example could not be opened: The file does not match the checksum of the catalog.')
    expect(useCardEditor.getState().text).toBe(NEW_CARD)
  })

  it('says so when the shop has no examples of this kind', async () => {
    reset([wallabag()], STATE_ON)
    serve()
    newCard()
    expect(await within(await openList()).findByTestId('example-none')).toHaveTextContent('no card examples')
  })

  it('is not offered on a card that is saved or has been touched', async () => {
    newCard()
    expect(await screen.findByTestId('example-start')).toBeInTheDocument()
    useCardEditor.getState().setText(CARD)
    await waitFor(() => expect(screen.queryByTestId('example-start')).not.toBeInTheDocument())
  })
})

describe('karten19 ec1: the shop is off', () => {
  beforeEach(() => {
    reset([radarr()], STATE_OFF)
    serve()
  })

  it('says that examples come from the shop and offers to turn it on, asking GitHub nothing', async () => {
    newCard()
    const dialog = await openList()
    expect(await within(dialog).findByTestId('example-shop-off')).toHaveTextContent('Examples come from the Card shop. Turn it on to see them.')
    expect(within(dialog).getByRole('button', { name: 'Turn on the Card shop' })).toBeInTheDocument()
    expect(within(dialog).queryByTestId('example-123/radarr-missing')).not.toBeInTheDocument()
    expect(githubWasAsked()).toEqual([])
    // The hint of the shop about what it sends is the same one.
    await userEvent.click(within(dialog).getByRole('button', { name: 'What it sends' }))
    expect(within(dialog).getByTestId('example-shop-sends')).toHaveTextContent('Nothing from your installation goes out.')
    expect(githubWasAsked()).toEqual([])
  })

  it('turns the shop on the way the shop tab does, and then lists the examples', async () => {
    newCard()
    const dialog = await openList()
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Turn on the Card shop' }))
    expect(await within(dialog).findByTestId('example-123/radarr-missing')).toBeInTheDocument()
    expect(calls('PUT', '/workshop/settings')).toHaveLength(1)
    expect(calls('PUT', '/workshop/settings')[0].body).toEqual({ enabled: true })
  })
})

describe('karten19 ac4: the editor of an own connection', () => {
  it('lists the connection examples and opens the choice as a new draft with a free short name', async () => {
    newIntegration()
    await waitFor(() => expect(useIntegrationEditor.getState().text).toBe(TEMPLATE))
    const dialog = await openList()
    expect(await within(dialog).findByTestId('example-123/wallabag')).toBeInTheDocument()
    expect(within(dialog).queryByText('Missing movies')).not.toBeInTheDocument()
    await userEvent.click(within(within(dialog).getByTestId('example-123/wallabag')).getByRole('button', { name: 'Start from this' }))
    await waitFor(() => expect(useIntegrationEditor.getState().text).not.toBe(TEMPLATE))
    const state = useIntegrationEditor.getState()
    const read = parseCard(state.text)
    expect(read.ok && readAt(read.card, ['short'])).toBe('wallabag-2')
    expect(read.ok && readAt(read.card, ['name'])).toBe('Wallabag')
    expect(state.short).toBeNull()
    expect(state.saved).toBe(TEMPLATE)
    expect(world.asked.filter((one) => one.method !== 'GET' && !one.url.endsWith('/check'))).toEqual([])
    expect(screen.queryByTestId('example-start')).not.toBeInTheDocument()
  })

  it('says that examples come from the shop when it is off', async () => {
    reset([wallabag()], STATE_OFF)
    serve()
    newIntegration()
    const dialog = await openList()
    expect(await within(dialog).findByTestId('example-shop-off')).toBeInTheDocument()
    expect(githubWasAsked()).toEqual([])
  })
})
