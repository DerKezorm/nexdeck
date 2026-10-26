/**
 * What the review of the guided way found (26.10.2026), one test group per finding: each fails without its fix.
 */
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { readAt } from '../../../lib/cardDocument'
import { editor, openCard, openNew, prepare, sent } from '../../../test/cardEditor'
import { ANSWERS, stubGuided } from '../../../test/guidedWorld'
import { answerOf } from '../../../test/probeAnswers'
import { thresholdOf } from './FinishStep'

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

describe('review 4: thresholds take decimals, a comma and a minus sign', () => {
  async function finish() {
    await openNew()
    await click(/^Home/)
    await click(/^Devices and sensors/)
    await waitFor(() => expect(editor().shapedPath).toBe('/api/states'))
    await click('Next')
    await click('Next')
    return { yellow: screen.getByRole('textbox', { name: 'Threshold for yellow' }), red: screen.getByRole('textbox', { name: 'Threshold for red' }) }
  }
  const rules = () => readAt(card(), ['value', 'rules'])

  it('0.5 is typed as 0.5 and stored as 0.5, not as 5', async () => {
    const { yellow } = await finish()
    await userEvent.clear(yellow)
    await userEvent.type(yellow, '0.5')
    expect(yellow).toHaveValue('0.5')
    expect(rules()).toEqual([{ op: '>=', than: 0.5, then: 'warn' }])
  })

  it('a comma works like a point, a minus sign gives a negative number, and what is not a number changes nothing', async () => {
    const { yellow, red } = await finish()
    await userEvent.type(red, '2,5')
    expect(red).toHaveValue('2,5')
    expect(rules()).toEqual([
      { op: '>=', than: 8, then: 'warn' },
      { op: '>=', than: 2.5, then: 'bad' },
    ])
    await userEvent.clear(yellow)
    await userEvent.type(yellow, '-')
    expect(yellow).toHaveValue('-')
    expect(rules()).toEqual([{ op: '>=', than: 2.5, then: 'bad' }])
    await userEvent.type(yellow, '5')
    expect(yellow).toHaveValue('-5')
    expect(rules()).toEqual([
      { op: '>=', than: -5, then: 'warn' },
      { op: '>=', than: 2.5, then: 'bad' },
    ])
    await userEvent.type(yellow, 'x')
    expect(rules()).toEqual([
      { op: '>=', than: -5, then: 'warn' },
      { op: '>=', than: 2.5, then: 'bad' },
    ])
  })

  it('a step back shows the earlier number in the field', async () => {
    const { yellow } = await finish()
    await userEvent.clear(yellow)
    await userEvent.type(yellow, '12')
    // Typing in one field is one step back (KARTEN-9 EC-10): one step takes the 8 back.
    await act(async () => editor().undo())
    expect(screen.getByRole('textbox', { name: 'Threshold for yellow' })).toHaveValue('8')
    await act(async () => editor().redo())
    expect(screen.getByRole('textbox', { name: 'Threshold for yellow' })).toHaveValue('12')
  })

  it('reads a text as a number, as nothing, or as not yet a number', () => {
    expect([thresholdOf('0.5'), thresholdOf('0,5'), thresholdOf('-5'), thresholdOf(' 12 '), thresholdOf('.5'), thresholdOf('7.')]).toEqual([0.5, 0.5, -5, 12, 0.5, 7])
    expect([thresholdOf(''), thresholdOf('  ')]).toEqual([null, null])
    expect([thresholdOf('-'), thresholdOf('0x10'), thresholdOf('1e3'), thresholdOf('abc'), thresholdOf('1.2.3')]).toEqual([undefined, undefined, undefined, undefined, undefined])
  })
})


describe('review 5: begins with, ends with and contains compare text, so 007 stays 007', () => {
  const LIST_ONLY = `${HEAD}requests:
  - id: states
    path: /api/states
form: list
rows: {select: "@"}
item: {title: entity_id}
`
  const FILTERED = `${HEAD}requests:
  - id: states
    path: /api/states
form: list
rows:
  select: "@"
  filter: [{field: entity_id, op: "==", value: "light.kitchen"}]
item: {title: entity_id}
rules:
  - {value: "@", op: "==", than: 1, then: warn}
`

  it('in the guided way a text comparison keeps the text and a number comparison keeps the number', async () => {
    await openNew()
    await click(/^Home/)
    await click(/^Devices and sensors/)
    await waitFor(() => expect(editor().shapedPath).toBe('/api/states'))
    await click('Next')
    const filter = ['value', 'total', 'rows', 'filter', 0] as const
    const value = () => screen.getAllByRole('textbox', { name: 'Value' })[0]
    // starts with: "007" and "1.50" are texts, also when they read like numbers
    await userEvent.clear(value())
    await userEvent.type(value(), '007')
    expect(readAt(card(), [...filter, 'value'])).toBe('007')
    expect(editor().text).toContain('"007"')
    await userEvent.clear(value())
    await userEvent.type(value(), '1.50')
    expect(readAt(card(), [...filter, 'value'])).toBe('1.50')
    // greater than: a number
    await userEvent.selectOptions(screen.getAllByRole('combobox', { name: 'Comparison' })[0], '>')
    expect(readAt(card(), [...filter, 'op'])).toBe('>')
    await userEvent.clear(value())
    await userEvent.type(value(), '12')
    expect(readAt(card(), [...filter, 'value'])).toBe(12)
    // and back to a text comparison: the number becomes its text
    await userEvent.selectOptions(screen.getAllByRole('combobox', { name: 'Comparison' })[0], 'ends_with')
    expect(readAt(card(), [...filter, 'value'])).toBe('12')
    await userEvent.selectOptions(screen.getAllByRole('combobox', { name: 'Comparison' })[0], 'contains')
    await userEvent.clear(value())
    await userEvent.type(value(), '0070')
    expect(readAt(card(), [...filter, 'value'])).toBe('0070')
  })

  it('in the guided way the rule of a line compares a text as text, too', async () => {
    stubGuided(LIST_ONLY, { 'POST /cards/probe': { status: 200, body: { nodes: 5, cut: false, tree: answerOf([{ entity_id: 'light.kitchen', state: 'on' }]) } } })
    await openCard('Queue', 'guided')
    await click(/^3 Display/)
    const rule = within(await screen.findByRole('group', { name: 'Line red when' }))
    await userEvent.selectOptions(rule.getByRole('combobox', { name: 'Comparison' }), 'starts_with')
    await userEvent.type(rule.getByRole('textbox', { name: 'Value' }), '007')
    expect(readAt(card(), ['item', 'status', 0, 'than'])).toBe('007')
  })

  it('under All settings the filter and the rule keep a text comparison as text as well', async () => {
    stubGuided(FILTERED)
    await openCard('Queue')
    await click(/^2 Look/)
    const filter = within(screen.getByRole('group', { name: /^Filter 1/ }))
    await userEvent.selectOptions(filter.getByRole('combobox', { name: 'Comparison' }), 'starts_with')
    await userEvent.clear(filter.getByRole('textbox', { name: 'Value' }))
    await userEvent.type(filter.getByRole('textbox', { name: 'Value' }), '007')
    expect(readAt(card(), ['rows', 'filter', 0, 'value'])).toBe('007')
    await userEvent.selectOptions(filter.getByRole('combobox', { name: 'Comparison' }), '>')
    await userEvent.clear(filter.getByRole('textbox', { name: 'Value' }))
    await userEvent.type(filter.getByRole('textbox', { name: 'Value' }), '7')
    expect(readAt(card(), ['rows', 'filter', 0, 'value'])).toBe(7)
    await userEvent.selectOptions(filter.getByRole('combobox', { name: 'Comparison' }), 'ends_with')
    expect(readAt(card(), ['rows', 'filter', 0, 'value'])).toBe('7')

    await click(/^3 Rules/)
    const rule = within(screen.getByRole('group', { name: /^Rule 1/ }))
    await userEvent.selectOptions(rule.getByRole('combobox', { name: 'Comparison' }), 'starts_with')
    await userEvent.clear(rule.getByRole('textbox', { name: 'Compared with' }))
    await userEvent.type(rule.getByRole('textbox', { name: 'Compared with' }), '007')
    expect(readAt(card(), ['rules', 0, 'than'])).toBe('007')
  })
})


describe('review 6: another form keeps what the author set, as the mock-up does', () => {
  async function toDisplay() {
    await openNew()
    await click(/^Home/)
    await click(/^Devices and sensors/)
    await waitFor(() => expect(editor().shapedPath).toBe('/api/states'))
    await click('Next')
  }
  const value = () => screen.getAllByRole('textbox', { name: 'Value' })[0]

  it('a number with its own sentence, label and yellow threshold is the same number after a list and back', async () => {
    await toDisplay()
    await userEvent.clear(value())
    await userEvent.type(value(), 'sensor.')
    await userEvent.clear(screen.getByRole('textbox', { name: 'Label below the number' }))
    await userEvent.type(screen.getByRole('textbox', { name: 'Label below the number' }), 'Mine')
    act(() => editor().set(['value', 'rules'], [{ op: '>=', than: 8, then: 'warn' }]))
    const number = readAt(card(), ['value'])
    expect(readAt(card(), ['value', 'total', 'rows', 'filter', 0, 'value'])).toBe('sensor.')

    await click(/^A list/)
    expect(readAt(card(), ['form'])).toBe('list')
    expect(readAt(card(), ['value'])).toBeUndefined()
    await click(/^A number/)
    expect(readAt(card(), ['form'])).toBe('value')
    expect(readAt(card(), ['value'])).toEqual(number)
    expect(screen.getAllByRole('textbox', { name: 'Value' })[0]).toHaveValue('sensor.')
    expect(screen.getByRole('textbox', { name: 'Label below the number' })).toHaveValue('Mine')
  })

  it('"Several numbers" starts with that number, its label and its colours, and "A number" takes the first one back', async () => {
    await toDisplay()
    await userEvent.clear(value())
    await userEvent.type(value(), 'sensor.')
    act(() => editor().set(['value', 'rules'], [{ op: '>=', than: 8, then: 'warn' }]))
    act(() => editor().set(['value', 'label'], 'Mine'))
    await click(/^Several numbers/)
    expect(readAt(card(), ['stats', 0, 'label'])).toBe('Mine')
    expect(readAt(card(), ['stats', 0, 'total', 'rows', 'filter', 0, 'value'])).toBe('sensor.')
    expect(readAt(card(), ['stats', 0, 'rules'])).toEqual([{ op: '>=', than: 8, then: 'warn' }])
    expect(readAt(card(), ['stats', 1, 'rules'])).toEqual([{ op: '>=', than: 8, then: 'warn' }])
    expect(readAt(card(), ['value'])).toBeUndefined()
    act(() => editor().set(['stats', 0, 'label'], 'Changed'))
    await click(/^A number/)
    expect(readAt(card(), ['value', 'label'])).toBe('Changed')
    expect(readAt(card(), ['value', 'rules'])).toEqual([{ op: '>=', than: 8, then: 'warn' }])
  })

  it('a list keeps its places and its red rule across Pictures and back, and the main text and the text below go along', async () => {
    stubGuided('', { 'POST /cards/probe': { status: 200, body: { nodes: 9, cut: false, tree: answerOf({ data: [{ name: 'a', type: 'qemu', mem: 1, thumb: '/t/1.jpg', status: 'running' }] }) } } })
    await openNew()
    await click(/^pve/)
    await click(/^Virtual machines and containers/)
    await waitFor(() => expect(editor().shapedPath).toBe('/api2/json/cluster/resources?type=vm'))
    await click('Next')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Main text' }), 'type')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Right' }), 'mem')
    const item = readAt(card(), ['item'])
    await click(/^Pictures/)
    expect(readAt(card(), ['item', 'title'])).toBe('type')
    expect(readAt(card(), ['item', 'subtitle'])).toBe('type')
    await click(/^A list/)
    expect(readAt(card(), ['item'])).toEqual({ ...(item as object), subtitle: 'type' })
    expect(readAt(card(), ['item', 'value'])).toBe('mem')
    expect(readAt(card(), ['item', 'status'])).toEqual([{ value: 'status', op: '!=', than: 'running', then: 'bad' }])
  })

  it('another answer starts over: nothing remembered of the old one comes back', async () => {
    stubGuided('', { 'POST /cards/probe': (body) => ({ status: 200, body: body?.path === '/api/calendars' ? CALENDARS : ANSWERS['/api/states'] }) })
    await toDisplay()
    await userEvent.clear(value())
    await userEvent.type(value(), 'sensor.')
    await click(/^A list/)
    expect(editor().shapeMemory.value).toBeDefined()
    await click(/^2 Data/)
    await click(/^Calendars/)
    await waitFor(() => expect(editor().shapeMemory).toEqual({}))
  })
})


describe('review 7: Save at the top jumps to Finish after the first save of a new card', () => {
  it('saved from the step Display, the offer to put the card on a board stands there, with Finish as the step', async () => {
    await openNew()
    await click(/^Home/)
    await click(/^Devices and sensors/)
    await waitFor(() => expect(editor().shapedPath).toBe('/api/states'))
    await click('Next')
    expect(editor().guidedStep).toBe('display')
    // the Save of the bar on top, not the one of the step
    await userEvent.click(within(screen.getByRole('group', { name: 'View' })).getByText('Guided'))
    const top = screen.getAllByRole('button', { name: 'Save' })[0]
    await userEvent.click(top)
    const saved = await screen.findByTestId('card-guided-saved')
    expect(editor().guidedStep).toBe('finish')
    expect(within(saved).getByRole('button', { name: 'Put on the board' })).toBeEnabled()
    expect(screen.getByRole('heading', { name: 'Finish', level: 2 })).toBeInTheDocument()
  })

  it('saved from All settings it stays there: the view is not taken away', async () => {
    await openNew()
    await click(/^Home/)
    await click(/^Devices and sensors/)
    await waitFor(() => expect(editor().shapedPath).toBe('/api/states'))
    await click('All settings')
    await userEvent.click(screen.getAllByRole('button', { name: 'Save' })[0])
    await waitFor(() => expect(sent('POST', '/cards')).toHaveLength(1))
    await waitFor(() => expect(editor().created).toBe(true))
    expect(editor().view).toBe('editor')
    expect(editor().guidedStep).not.toBe('finish')
  })
})


describe('review 8: YAML to Guided opens the steps the card has earned, as YAML to All settings does', () => {
  const TYPED = `${HEAD}requests:
  - id: states
    path: /api/states
form: value
value:
  total: {fn: count, rows: {select: "@", filter: [{field: state, op: "==", value: "on"}]}}
`

  it('a card typed in YAML with a service, a path and a form: Display and Finish are open, nothing is asked again', async () => {
    await openNew()
    await click('YAML')
    act(() => editor().setText(TYPED))
    await click('Guided')
    expect(editor().view).toBe('guided')
    expect(editor().shapedPath).toBe('/api/states')
    expect(screen.getByRole('button', { name: /^3 Display/ })).toBeEnabled()
    expect(screen.getByRole('button', { name: /^4 Finish/ })).toBeEnabled()
    await click(/^3 Display/)
    expect(await screen.findByTestId('card-guided-result')).toBeInTheDocument()
    // what was typed is what the card shows, not a suggestion's start
    expect(editor().text).toBe(TYPED)
  })

  it('a card the guided way cannot show still opens in Guided from YAML when the author asks for it, with the reason noted', async () => {
    await openNew()
    await click('YAML')
    act(() => editor().setText(TYPED.replace(/value:\n {2}total: .*\n/, 'value: "length([?state == \'on\'])"\n')))
    await click('Guided')
    expect(editor().view).toBe('guided')
    expect(editor().refusal).toBe('expression')
    expect(screen.getByRole('button', { name: /^3 Display/ })).toBeEnabled()
  })

  it('to All settings from YAML, and from there to Guided, the steps are open as well', async () => {
    await openNew()
    await click('YAML')
    act(() => editor().setText(TYPED))
    await click('All settings')
    expect(editor().view).toBe('editor')
    await click('Guided')
    expect(screen.getByRole('button', { name: /^3 Display/ })).toBeEnabled()
  })
})
