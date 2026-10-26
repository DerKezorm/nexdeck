/**
 * What the review of the guided way found (26.10.2026), one test group per finding: each fails without its fix.
 */
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { readAt } from '../../../lib/cardDocument'
import { editor, openCard, openNew, prepare, sent } from '../../../test/cardEditor'
import { stubGuided } from '../../../test/guidedWorld'
import { answerOf } from '../../../test/probeAnswers'

const click = async (name: string | RegExp) => userEvent.click(await screen.findByRole('button', { name }))
const card = () => editor().card!

const CALENDARS = { nodes: 5, cut: false, tree: answerOf([{ entity_id: 'calendar.home', name: 'Home' }, { entity_id: 'calendar.work', name: 'Work' }]) }

const HEAD = `nexdeck-card: 1
slug: queue
name: Queue
version: "1.0.0"
requires: [homeassistant]
`

beforeEach(() => {
  prepare()
  stubGuided()
})

afterEach(async () => {
  vi.unstubAllGlobals()
  await i18next.changeLanguage('en')
})

describe('review 1: nothing the guided way cannot show goes away unasked', () => {
  const FORMULA = `${HEAD}requests:
  - id: config
    path: /api/config
form: value
value:
  formula: "version * 2"
  label: Double
`
  const RICH_LIST = `nexdeck-card: 1
slug: queue
name: Queue
version: "1.0.0"
requires: [proxmox]
requests:
  - id: guests
    path: /api2/json/cluster/resources?type=vm
form: list
rows: {select: data}
item:
  title: name
  link: {template: "https://pve.example.com/{name}"}
rules:
  - {value: data, op: ">", than: 3, then: warn}
`

  it('a suggestion over a card with a formula asks first: Cancel changes nothing, Replace lists and replaces', async () => {
    stubGuided(FORMULA, { 'POST /cards/probe': { status: 200, body: CALENDARS } })
    await openCard('Queue', 'guided')
    expect(editor().view).toBe('editor')
    const before = editor().text
    await click('Guided')
    await click(/^2 Data/)
    // The card's own path is asked once the step needs its answer; the question is about the pick that follows.
    await waitFor(() => expect(sent('POST', '/cards/probe')).toHaveLength(1))
    await click(/^Calendars/)
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByTestId('card-guided-replace')).toHaveTextContent('A formula')
    expect(editor().text).toBe(before)
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(editor().text).toBe(before)
    expect(sent('POST', '/cards/probe')).toHaveLength(1)

    await click(/^Calendars/)
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Replace' }))
    await waitFor(() => expect(editor().shapedPath).toBe('/api/calendars'))
    expect(readAt(card(), ['requests', 0, 'path'])).toBe('/api/calendars')
    expect(editor().text).not.toContain('formula')
  })

  it('another kind of service over such a card asks first, too', async () => {
    stubGuided(FORMULA)
    await openCard('Queue', 'guided')
    await click('Guided')
    await click(/^pve/)
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('A formula')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(readAt(card(), ['requires'])).toEqual(['homeassistant'])
    expect(readAt(card(), ['value', 'formula'])).toBe('version * 2')
    // The same kind of service with another connection is no replacement and asks nothing.
    await click(/^Home/)
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(readAt(card(), ['value', 'formula'])).toBe('version * 2')
  })

  it('a form over a list with colour rules and links of its own asks first and names both', async () => {
    stubGuided(RICH_LIST)
    await openCard('Queue', 'guided')
    expect(editor().view).toBe('editor')
    await click('Guided')
    await click(/^3 Display/)
    const before = editor().text
    await click(/^A number/)
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('Colour rules of the whole card')
    expect(dialog).toHaveTextContent('Links of the lines')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(editor().text).toBe(before)
    await click(/^A number/)
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Replace' }))
    expect(readAt(card(), ['form'])).toBe('value')
    expect(readAt(card(), ['rules'])).toBeUndefined()
    expect(readAt(card(), ['item'])).toBeUndefined()
  })

  it('a card the guided way shows whole is changed without a question', async () => {
    stubGuided(`${HEAD}requests:\n  - id: states\n    path: /api/states\nform: value\nvalue:\n  total: {fn: count, rows: {select: "@", filter: [{field: state, op: "==", value: "on"}]}}\n`)
    await openCard('Queue', 'guided')
    await click(/^2 Data/)
    await click(/^Calendars/)
    expect(screen.queryByRole('dialog')).toBeNull()
    await waitFor(() => expect(readAt(card(), ['requests', 0, 'path'])).toBe('/api/calendars'))
  })

  it('asking the same path again leaves the display as the author set it', async () => {
    await openNew()
    await click(/^Weather/)
    await userEvent.clear(screen.getByRole('textbox', { name: 'Path to ask' }))
    await userEvent.type(screen.getByRole('textbox', { name: 'Path to ask' }), '/v1/forecast')
    await click('Ask')
    await waitFor(() => expect(editor().shapedPath).toBe('/v1/forecast'))
    await act(async () => card() && editor().set(['value', 'path'], 'wind'))
    await click('Ask')
    await waitFor(() => expect(sent('POST', '/cards/probe').length).toBeGreaterThan(1))
    expect(readAt(card(), ['value', 'path'])).toBe('wind')
  })
})

/** The Home Assistant way up to the saved card and the offer to put it on a board. */
async function saveLightsOn() {
  await openNew()
  await click(/^Home/)
  await click(/^Devices and sensors/)
  await waitFor(() => expect(editor().shapedPath).toBe('/api/states'))
  await click('Next')
  await click('Next')
  await userEvent.click(within(screen.getByRole('region', { name: 'Finish' })).getByRole('button', { name: 'Save' }))
  return screen.findByTestId('card-guided-saved')
}

describe('review 2: put on a board offers only pages that hold cards', () => {
  it('a home page first on the board is not offered, nor a board with a network plan only; the first page that holds cards is preselected', async () => {
    const saved = await saveLightsOn()
    const board = await within(saved).findByRole('combobox', { name: 'Board' })
    expect(Array.from((board as HTMLSelectElement).options).map((one) => one.text)).toEqual(['Home'])
    const page = within(saved).getByRole('combobox', { name: 'Page' }) as HTMLSelectElement
    expect(Array.from(page.options).map((one) => one.text)).toEqual(['Main', 'Lights'])
    expect(page.value).toBe('5')
    await userEvent.click(within(saved).getByRole('button', { name: 'Put on the board' }))
    await waitFor(() => expect(sent('POST', '/pages/5/widgets')).toHaveLength(1))
  })

  it('without a board that has such a page there is only the sentence about the missing board', async () => {
    stubGuided('', { 'GET /boards': { status: 200, body: [{ id: 3, slug: 'network', name: 'Network', permission: 'owner', pages: [{ id: 8, name: 'Plan', slug: 'plan', widget_count: 0, kind: 'topology' }] }] } })
    const saved = await saveLightsOn()
    expect(await within(saved).findByText(/There is no board you may change/)).toBeInTheDocument()
    expect(within(saved).queryByRole('button', { name: 'Put on the board' })).toBeNull()
  })

  it('a board list from before (pages without a kind) still offers every page', async () => {
    stubGuided('', { 'GET /boards': { status: 200, body: [{ id: 2, slug: 'home', name: 'Home', permission: 'owner', pages: [{ id: 5, name: 'Main', slug: 'main', widget_count: 3 }] }] } })
    const saved = await saveLightsOn()
    expect(await within(saved).findByRole('button', { name: 'Put on the board' })).toBeEnabled()
  })
})

describe('review 3: a list the service leaves out because it is empty', () => {
  const NOBODY = { nodes: 3, cut: false, tree: answerOf({ MediaContainer: { size: 0 } }) }
  const PLAYING = `nexdeck-card: 1
slug: queue
name: Queue
version: "1.0.0"
requires: [plex]
requests:
  - id: playing
    path: /status/sessions
form: list
rows: {select: MediaContainer.Metadata}
item: {title: title, subtitle: User.title}
`

  it('a list card of Plex with nobody watching is a list in the guided way, with its places and the sentence about the empty answer', async () => {
    stubGuided(PLAYING, { 'POST /cards/probe': { status: 200, body: NOBODY } })
    await openCard('Queue', 'guided')
    expect(editor().view).toBe('guided')
    await click(/^3 Display/)
    expect(await screen.findByTestId('card-answer-none')).toHaveTextContent('No entries right now.')
    expect(screen.queryByTestId('card-guided-expression')).toBeNull()
    expect(screen.getByRole('button', { name: /^A list/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('combobox', { name: 'Main text' })).toHaveValue('title')
    expect(screen.getByRole('combobox', { name: 'Below, small' })).toHaveValue('User.title')
    expect(screen.getByRole('group', { name: 'Line red when' })).toBeInTheDocument()
  })

  it('a new card from "Playing now" becomes the list of the suggestion, never a number out of a side field', async () => {
    stubGuided('', { 'POST /cards/probe': { status: 200, body: NOBODY } })
    await openNew()
    await click(/^Plex$|^PlexPlex/)
    await click(/^Playing now/)
    await waitFor(() => expect(editor().shapedPath).toBe('/status/sessions'))
    expect(readAt(card(), ['form'])).toBe('list')
    expect(readAt(card(), ['rows'])).toEqual({ select: 'MediaContainer.Metadata' })
    expect(readAt(card(), ['item', 'title'])).toBe('title')
    expect(editor().text).not.toContain('MediaContainer.size')
    await click('Next')
    expect(screen.getByRole('button', { name: /^A list/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: /^Pictures/ })).toBeDisabled()
    expect(screen.queryByTestId('card-guided-expression')).toBeNull()
  })

  it('the answer with viewers shows the same list with its entries', async () => {
    const watching = { nodes: 9, cut: false, tree: answerOf({ MediaContainer: { size: 1, Metadata: [{ title: 'Example Film', User: { title: 'kim' } }] } }) }
    stubGuided(PLAYING, { 'POST /cards/probe': { status: 200, body: watching } })
    await openCard('Queue', 'guided')
    await click(/^3 Display/)
    expect(await screen.findByTestId('card-answer-table')).toHaveTextContent('Example Film')
    expect(screen.queryByTestId('card-answer-none')).toBeNull()
  })
})
