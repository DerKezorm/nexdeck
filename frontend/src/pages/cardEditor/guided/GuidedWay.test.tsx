/**
 * The guided way on screen (umbau U1 to U11): the three ways of the accepted mock-up, Home Assistant as a number
 * "Lights on", Proxmox VE as a list and Plex as pictures, with the services' answers in their real shapes; and what
 * the guided way does with a card it cannot show.
 */
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import de from '../../../i18n/editor.de.json'
import en from '../../../i18n/editor.en.json'
import { readAt } from '../../../lib/cardDocument'
import { editor, openCard, openNew, prepare, sent } from '../../../test/cardEditor'
import { stubGuided } from '../../../test/guidedWorld'

const click = async (name: string | RegExp) => userEvent.click(await screen.findByRole('button', { name }))
const next = () => click('Next')
const card = () => editor().card!

beforeEach(() => {
  prepare()
  stubGuided()
})

afterEach(async () => {
  vi.unstubAllGlobals()
  await i18next.changeLanguage('en')
})

describe('umbau U3: Service', () => {
  it('offers the kinds of service a card can read as tiles; a tile sets the kind and the connection to try it with', async () => {
    await openNew()
    const tiles = within(screen.getByRole('region', { name: 'Which service is the card for?' }))
    // One tile for each kind, by the name of the kind (the connections are named in dienst-art D2): Plex (old) is
    // switched off, qBittorrent cannot be read by a card.
    expect((await tiles.findAllByRole('button', { pressed: false })).map((one) => one.textContent)).toEqual([
      'Home Assistant',
      'JSON API',
      'Plex',
      'Proxmox VE',
      'Synology DSM2 integrations',
      'SABnzbd',
      'Sonarr',
    ])
    expect(screen.getByRole('button', { name: '2 Data' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
    expect(screen.getByRole('link', { name: /Add an integration/ })).toHaveAttribute('href', '/system/integrations')

    await click(/^Proxmox/)
    expect(readAt(card(), ['requires'])).toEqual(['proxmox'])
    expect(editor().integrationId).toBe(12)
    expect(editor().guidedStep).toBe('data')
    // Another service replaces the kind, it is never added to it, and starts over with nothing chosen.
    await click(/^1 Service/)
    await click(/^Home/)
    expect(readAt(card(), ['requires'])).toEqual(['homeassistant'])
    expect(readAt(card(), ['requests'])).toEqual([{ id: 'main', path: '/' }])
    // The connection is never written into the card (decision 4).
    expect(editor().text).not.toMatch(/11|Home\b/)
  })
})

describe('umbau: the three ways of the mock-up', () => {
  it('Home Assistant: devices and sensors, counted where the id starts with light. and the state is on, "Lights on", yellow from 8, saved and put on a board', async () => {
    await openNew()
    await click(/^Home/)
    expect(screen.getByRole('heading', { name: 'What should the card show?', level: 2 })).toBeInTheDocument()
    expect(screen.getByText(/nexdeck knows the most important data of Home Assistant/)).toBeInTheDocument()
    await click(/^Devices and sensors/)
    await waitFor(() => expect(editor().shapedPath).toBe('/api/states'))
    expect(sent('POST', '/cards/probe').at(-1)?.body).toEqual({ integration_id: 11, path: '/api/states' })
    expect(readAt(card(), ['requests'])).toEqual([{ id: 'states', path: '/api/states', every: '30s' }])
    const answer = screen.getByTestId('card-answer-table')
    // The name for people, the real name of the field small beneath it.
    const heads = within(answer).getAllByRole('columnheader')
    expect(heads.map((one) => one.firstChild?.textContent)).toEqual(['Name', 'ID', 'State', 'Changed'])
    expect(heads.map((one) => one.querySelector('small')?.textContent)).toEqual(['attributes.friendly_name', 'entity_id', 'state', 'last_changed'])
    expect(answer).toHaveTextContent('23 entries')
    expect(answer).toHaveTextContent('… and 15 more entries')

    await next()
    expect(screen.getByRole('button', { name: /^A number/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getAllByRole('combobox', { name: 'Column' }).map((one) => (one as HTMLSelectElement).value)).toEqual(['entity_id', 'state'])
    expect(screen.getAllByRole('combobox', { name: 'Comparison' }).map((one) => (one as HTMLSelectElement).value)).toEqual(['starts_with', '=='])
    expect(screen.getAllByRole('textbox', { name: 'Value' }).map((one) => (one as HTMLInputElement).value)).toEqual(['light.', 'on'])
    expect(readAt(card(), ['value', 'total'])).toEqual({
      fn: 'count',
      rows: { select: '@', filter: [{ field: 'entity_id', op: 'starts_with', value: 'light.' }, { field: 'state', op: '==', value: 'on' }] },
    })
    // The number is the server's; the rows shown that match are marked.
    expect(await screen.findByTestId('card-guided-result')).toHaveTextContent('Result: 6 of 23 entries. They are marked in the table.')
    const table = screen.getByTestId('card-answer-table')
    expect(table.querySelectorAll('tr[data-hit="true"]')).toHaveLength(2)
    expect(table).toHaveTextContent('2 match')
    expect(screen.getByRole('textbox', { name: 'Label below the number' })).toHaveValue('Lights on')

    // A condition more, changed, and taken away again.
    await click('+ Condition')
    expect(screen.getAllByRole('combobox', { name: 'Column' })).toHaveLength(3)
    await userEvent.selectOptions(screen.getAllByRole('combobox', { name: 'Comparison' })[1], 'ends_with')
    expect(readAt(card(), ['value', 'total', 'rows', 'filter', 1, 'op'])).toBe('ends_with')
    await userEvent.selectOptions(screen.getAllByRole('combobox', { name: 'Comparison' })[1], '==')
    await userEvent.click(screen.getAllByRole('button', { name: 'Remove condition' })[2])
    expect(readAt(card(), ['value', 'total', 'rows', 'filter'])).toHaveLength(2)

    await next()
    expect(screen.getByRole('textbox', { name: 'Name of the card' })).toHaveValue('Lights on')
    expect(screen.getByRole('textbox', { name: 'Threshold for yellow' })).toHaveValue('8')
    expect(screen.getByRole('textbox', { name: 'Threshold for red' })).toHaveValue('')
    expect(screen.getByRole('textbox', { name: 'Threshold for red' })).toHaveAttribute('placeholder', 'empty = never')
    expect(readAt(card(), ['value', 'rules'])).toEqual([{ op: '>=', than: 8, then: 'warn' }])
    await userEvent.type(screen.getByRole('textbox', { name: 'Threshold for red' }), '10')
    expect(readAt(card(), ['value', 'rules'])).toEqual([
      { op: '>=', than: 8, then: 'warn' },
      { op: '>=', than: 10, then: 'bad' },
    ])
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Look again every' }), '5m')
    expect(readAt(card(), ['requests', 0, 'every'])).toBe('5m')
    expect(readAt(card(), ['slug'])).toBe('lights-on')

    await userEvent.click(within(screen.getByRole('region', { name: 'Finish' })).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(sent('POST', '/cards')).toHaveLength(1))
    const saved = await screen.findByTestId('card-guided-saved')
    expect(saved).toHaveTextContent('Saved.')
    expect(await within(saved).findByText('The card is now under System › Custom cards. Put it on a board right away?')).toBeInTheDocument()
    // Only boards this account may change; the page of the board can be picked.
    expect(within(saved).getByRole('combobox', { name: 'Board' })).toHaveTextContent('Home')
    expect(within(saved).getByRole('combobox', { name: 'Board' })).not.toHaveTextContent('Shared')
    await userEvent.selectOptions(within(saved).getByRole('combobox', { name: 'Page' }), '6')
    await userEvent.click(within(saved).getByRole('button', { name: 'Put on the board' }))
    await waitFor(() => expect(sent('POST', '/pages/6/widgets')).toHaveLength(1))
    expect(sent('POST', '/pages/6/widgets')[0].body).toEqual({ kind: 'custom.value', title: 'Lights on', integration_id: 11, options: { card: 'lights-on' } })
    expect(await within(saved).findByText('The card is on Home now.')).toBeInTheDocument()
    expect(within(saved).getByRole('link', { name: 'Open the board' })).toHaveAttribute('href', '/b/home')
    expect(screen.getByRole('button', { name: 'Save again' })).toBeInTheDocument()
  })

  it('Proxmox VE: the guests as a list with name, type and memory, a line red when the state is not running', async () => {
    await openNew()
    await click(/^Proxmox/)
    await click(/^Virtual machines and containers/)
    await waitFor(() => expect(editor().shapedPath).toBe('/api2/json/cluster/resources?type=vm'))
    await next()
    expect(screen.getByRole('button', { name: /^A list/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('combobox', { name: 'Main text' })).toHaveValue('name')
    expect(screen.getByRole('combobox', { name: 'Below, small' })).toHaveValue('type')
    expect(screen.getByRole('combobox', { name: 'Right' })).toHaveValue('mem')
    expect(screen.getByText('e.g. docker-live')).toBeInTheDocument()
    expect(readAt(card(), ['rows'])).toEqual({ select: 'data' })
    expect(readAt(card(), ['item'])).toEqual({ title: 'name', subtitle: 'type', value: 'mem', status: [{ value: 'status', op: '!=', than: 'running', then: 'bad' }] })

    const rule = within(screen.getByRole('group', { name: 'Line red when' }))
    expect((rule.getByRole('combobox', { name: 'Column' }) as HTMLSelectElement).value).toBe('status')
    expect((rule.getByRole('combobox', { name: 'Comparison' }) as HTMLSelectElement).value).toBe('!=')
    expect(rule.getByRole('textbox', { name: 'Value' })).toHaveValue('running')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Right' }), 'maxmem')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Below, small' }), '')
    expect(readAt(card(), ['item', 'value'])).toBe('maxmem')
    expect(readAt(card(), ['item', 'subtitle'])).toBeUndefined()
    // Without a value there is no rule; the sentence stays as it was.
    await userEvent.clear(rule.getByRole('textbox', { name: 'Value' }))
    expect(readAt(card(), ['item', 'status'])).toBeUndefined()
    expect((rule.getByRole('combobox', { name: 'Column' }) as HTMLSelectElement).value).toBe('status')
    await userEvent.type(rule.getByRole('textbox', { name: 'Value' }), 'stopped')
    await userEvent.selectOptions(rule.getByRole('combobox', { name: 'Comparison' }), '==')
    expect(readAt(card(), ['item', 'status'])).toEqual([{ value: 'status', op: '==', than: 'stopped', then: 'bad' }])

    await next()
    expect(screen.getByRole('textbox', { name: 'Name of the card' })).toHaveValue('Virtual machines and containers')
    // Colours as sentences are for numbers; a list has its line rule.
    expect(screen.queryByRole('textbox', { name: 'Threshold for yellow' })).toBeNull()
  })

  it('Plex: recently added as pictures with poster, title and year', async () => {
    await openNew()
    await click(/^Plex/)
    await click(/^Recently added/)
    await waitFor(() => expect(editor().shapedPath).toMatch(/^\/library\/recentlyAdded/))
    await next()
    expect(screen.getByRole('button', { name: /^Pictures/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('combobox', { name: 'Picture' })).toHaveValue('thumb')
    expect(screen.getByRole('combobox', { name: 'Title' })).toHaveValue('title')
    expect(screen.getByRole('combobox', { name: 'Below' })).toHaveValue('year')
    expect(readAt(card(), ['form'])).toBe('posters')
    expect(readAt(card(), ['rows'])).toEqual({ select: 'MediaContainer.Metadata' })
    expect(readAt(card(), ['item'])).toEqual({ image: 'thumb', title: 'title', subtitle: 'year' })
  })
})

describe('umbau U4: Data', () => {
  it('a kind without suggestions has its own address open at once; Ask asks it', async () => {
    await openNew()
    await click(/^JSON API/)
    expect(screen.getByText(/Type what the card should ask JSON API/)).toBeInTheDocument()
    const own = screen.getByRole('textbox', { name: 'Path to ask' })
    expect(own).toBeVisible()
    await userEvent.clear(own)
    await userEvent.type(own, '/v1/forecast')
    // into the card when the author leaves the field (review 16); nothing is asked of the service before
    await userEvent.tab()
    expect(readAt(card(), ['requests', 0, 'path'])).toBe('/v1/forecast')
    expect(sent('POST', '/cards/probe')).toHaveLength(0)
    await click('Ask')
    await waitFor(() => expect(editor().shapedPath).toBe('/v1/forecast'))
    expect(sent('POST', '/cards/probe')[0].body).toEqual({ integration_id: 14, path: '/v1/forecast' })
    expect(within(screen.getByTestId('card-answer-table')).getAllByRole('columnheader').map((one) => one.textContent)).toEqual(['Field', 'Value'])
    // A number of a single value, named after the service until the author names it.
    expect(readAt(card(), ['value'])).toEqual({ path: 'temperature' })
    expect(readAt(card(), ['name'])).toBe('JSON API')
  })

  it('a failed answer says why, the way a card does, and Next waits', async () => {
    await openNew()
    await click(/^JSON API/)
    await userEvent.clear(screen.getByRole('textbox', { name: 'Path to ask' }))
    await userEvent.type(screen.getByRole('textbox', { name: 'Path to ask' }), '/nothing')
    await click('Ask')
    expect(await screen.findByText('The service answered 404.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
  })
})

describe('lesen L4: what nexdeck can ask a kind of service, from the code', () => {
  const read = { path: '/v1/forecast', widgets: [{ kind: 'value', label: 'Value' }] }
  const more = { path: '/v1/alerts', widgets: [{ kind: 'value', label: 'Value' }, { kind: 'list', label: 'List' }, { kind: 'chart', label: 'Chart' }] }
  const docs = { path: '/api/config/{site}', widgets: [] }

  it('offers the paths of the kind, names the cards that ask them, and a pick asks the service and sets the path', async () => {
    stubGuided('', { 'GET /cards/sources/jsonapi/reads': { status: 200, body: { reads: [read, more, docs] } } })
    await openNew()
    await click(/^JSON API/)
    const entry = await screen.findByRole('button', { name: /Like the card ‘Value’(?! and)/ })
    expect(within(entry).getByText('/v1/forecast')).toBeInTheDocument()
    expect(screen.getByText('What nexdeck can ask JSON API')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Like the card ‘Value’ and 2 more/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /From the documentation of JSON API/ })).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Path to ask' })).not.toBeVisible()
    await userEvent.click(entry)
    await waitFor(() => expect(editor().shapedPath).toBe('/v1/forecast'))
    expect(sent('POST', '/cards/probe')[0].body).toEqual({ integration_id: 14, path: '/v1/forecast' })
    expect(readAt(card(), ['requests', 0, 'path'])).toBe('/v1/forecast')
    expect(screen.getByRole('button', { name: /Like the card ‘Value’(?! and)/ })).toHaveAttribute('aria-pressed', 'true')
  })

  it('is there without a connection of the kind, and a pick then only sets the path', async () => {
    stubGuided('', { 'GET /cards/sources/sabnzbd/reads': { status: 200, body: { reads: [{ path: '/api?mode=queue', widgets: [{ kind: 'queue', label: 'Queue' }] }] } } })
    await openNew()
    await click(/^SABnzbd/)
    const entry = await screen.findByRole('button', { name: /Like the card ‘Queue’/ })
    expect(screen.getByTestId('card-no-connection')).toBeInTheDocument()
    await userEvent.click(entry)
    await waitFor(() => expect(readAt(card(), ['requests', 0, 'path'])).toBe('/api?mode=queue'))
    expect(sent('POST', '/cards/probe')).toHaveLength(0)
  })

  it('does not ask a path that has a place in it, and opens the own address for it', async () => {
    stubGuided('', { 'GET /cards/sources/jsonapi/reads': { status: 200, body: { reads: [docs] } } })
    await openNew()
    await click(/^JSON API/)
    await userEvent.click(await screen.findByRole('button', { name: /From the documentation/ }))
    await waitFor(() => expect(readAt(card(), ['requests', 0, 'path'])).toBe('/api/config/{site}'))
    expect(sent('POST', '/cards/probe')).toHaveLength(0)
    expect(screen.getByRole('textbox', { name: 'Path to ask' })).toBeVisible()
  })

  it('shows a path once when the suggestions of the kind already hold it', async () => {
    stubGuided('', { 'GET /cards/sources/homeassistant/reads': { status: 200, body: { reads: [{ path: '/api/states', widgets: [{ kind: 'entities', label: 'Entity list' }] }, { path: '/api/events', widgets: [] }] } } })
    await openNew()
    await click(/^Home Assistant/)
    expect(await screen.findByText('/api/events')).toBeInTheDocument()
    expect(screen.queryByText('/api/states')).not.toBeInTheDocument()
  })

  it('says there is nothing to suggest for a kind without reads, and keeps the own address open', async () => {
    stubGuided('', { 'GET /cards/sources/jsonapi/reads': { status: 200, body: { reads: [] } } })
    await openNew()
    await click(/^JSON API/)
    expect(await screen.findByText(/Nothing to suggest for JSON API/)).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Path to ask' })).toBeVisible()
  })

  it('speaks German without dashes and without words of programmers', async () => {
    await i18next.changeLanguage('de')
    expect(de.editor.guided.data.readsTitle).toBe('Was nexdeck bei {{service}} abfragen kann')
    for (const key of ['readsTitle', 'readsLike', 'readsLikeMore', 'readsDocs', 'readsNone'] as const) {
      expect(de.editor.guided.data[key]).not.toMatch(/[–—]/)
    }
    expect(en.editor.guided.data.readsLike).toContain('{{name}}')
    expect('readsNoCards' in en.editor.guided.data || 'readsNotYet' in en.editor.guided.data).toBe(false)
  })
})

describe('umbau U1: three ways into one card', () => {
  const COUNTED = `nexdeck-card: 1
slug: queue
name: Queue
version: "1.0.0"
requires: [homeassistant]
requests:
  - id: states
    path: /api/states
form: value
# counted by the guided way
value:
  total: {fn: count, rows: {select: "@", filter: [{field: state, op: "==", value: "on"}]}}
`

  it('a card the guided way can show opens there, and Guided, All settings and YAML show the same text', async () => {
    stubGuided(COUNTED)
    await openCard('Queue', 'guided')
    expect(editor().view).toBe('guided')
    expect(screen.queryByTestId('card-guided-refused')).toBeNull()
    await click('All settings')
    expect(screen.getByRole('heading', { name: 'Source', level: 2 })).toBeInTheDocument()
    await click('Guided')
    await next()
    await next()
    expect(await screen.findByTestId('card-guided-result')).toBeInTheDocument()
    expect(editor().text).toBe(COUNTED)
  })

  it('a card it cannot show opens in All settings and says why; in the guided way the expression stays and is named', async () => {
    stubGuided(COUNTED.replace(/value:\n {2}total: .*\n/, `value: "length([?state == 'on'])"\n`))
    await openCard('Queue', 'guided')
    expect(editor().view).toBe('editor')
    expect(screen.getByTestId('card-guided-refused')).toHaveTextContent('The guided way cannot show all of this card, because it uses an expression.')
    const before = editor().text
    await click('Guided')
    await next()
    await next()
    expect(screen.getAllByTestId('card-guided-expression')[0]).toHaveTextContent('This card uses an expression; edit it under All settings.')
    expect(screen.getByRole('button', { name: /^A list/ })).toBeDisabled()
    expect(editor().text).toBe(before)
    await userEvent.click(screen.getAllByRole('button', { name: 'Open All settings' })[0])
    expect(editor().view).toBe('editor')
  })
})

describe('umbau U8 to U11: Finish, preview, words and narrow screens', () => {
  it('in German the name has its English beside it, and more languages can be added', async () => {
    await act(() => i18next.changeLanguage('de'))
    await openNew()
    await click(/^Home/)
    await click(/^Geräte und Sensoren/)
    await waitFor(() => expect(editor().shapedPath).toBe('/api/states'))
    // The suggestion's words in both languages.
    expect(readAt(card(), ['name'])).toEqual({ en: 'Lights on', de: 'Lichter an' })
    expect(readAt(card(), ['value', 'label'])).toEqual({ en: 'Lights on', de: 'Lichter an' })
    await click('Weiter')
    await click('Weiter')
    expect(screen.getByText('Auf Englisch zeigt sie:')).toBeInTheDocument()
    const own = screen.getByRole('textbox', { name: 'Name der Karte' })
    const english = screen.getByRole('textbox', { name: 'Name auf Englisch' })
    expect(english).toHaveValue('Lights on')
    await userEvent.clear(own)
    await userEvent.type(own, 'Lampen')
    // English stays as it was once it differs.
    expect(readAt(card(), ['name'])).toEqual({ en: 'Lights on', de: 'Lampen' })
    expect(readAt(card(), ['slug'])).toBe('lights-on')
    await click('+ Sprache')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: '+ Sprache' }), 'fr')
    await userEvent.type(screen.getByRole('textbox', { name: 'Name auf Französisch' }), 'Lumières')
    expect(readAt(card(), ['name'])).toEqual({ en: 'Lights on', de: 'Lampen', fr: 'Lumières' })
    // U9: the preview stays beside it, live data or example data.
    const preview = within(screen.getByTestId('card-preview'))
    expect(preview.getByRole('button', { name: 'Echte Daten' })).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(preview.getByRole('button', { name: 'Beispieldaten' }))
    await waitFor(() => expect(sent('POST', '/cards/preview').some((one) => one.body?.demo === true)).toBe(true))
  })

  it('U9: before anything is chosen the preview says what comes, and does not ask', async () => {
    await openNew()
    expect(screen.getByTestId('card-preview-empty')).toHaveTextContent('As soon as you have chosen what the card shows, it appears here.')
    await new Promise((resolve) => setTimeout(resolve, 500))
    expect(sent('POST', '/cards/preview')).toHaveLength(0)
  })

  it('U10: the guided way speaks without the words of programmers', () => {
    const own = ['data.own', 'data.path', 'data.pathHint']
    for (const words of [en, de]) {
      const walk = (node: unknown, path: string[]): [string, string][] =>
        typeof node === 'string' ? [[path.join('.'), node]] : Object.entries(node as object).flatMap(([key, value]) => walk(value, [...path, key]))
      const texts = walk((words as { editor: { guided: object } }).editor.guided, []).filter(([key]) => !own.includes(key))
      expect(texts.length).toBeGreaterThan(150)
      expect(texts.filter(([, text]) => /\b(JSON|JMESPath|requests?|endpoints?|Feldpfad|field path|API)\b/i.test(text))).toEqual([])
    }
  })

  it('U11: the table scrolls sideways in its own box', async () => {
    await openNew()
    await click(/^Proxmox/)
    await click(/^Virtual machines and containers/)
    const table = await screen.findByTestId('card-answer-table')
    expect(table.querySelector('table')?.parentElement).toHaveClass('overflow-x-auto')
  })
})

