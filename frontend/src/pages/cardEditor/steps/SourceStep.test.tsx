/**
 * Step 1, Source (KARTEN-9 AC-2 to AC-5, AC-10, EC-1, EC-2, EC-4, EC-6, EC-9): kinds and connection, requests, the
 * probe and its tree, putting fields on the card by click, keyboard and drag, and demo data from an answer.
 */
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import deScreen from '../../../i18n/de.json'
import editorDe from '../../../i18n/editor.de.json'
import { readAt } from '../../../lib/cardDocument'
import { editor, openCard, prepare, sent, stub } from '../../../test/cardEditor'
import { HA_STATES, SONARR_QUEUE } from '../../../test/probeAnswers'
import { draftKey } from '../draft'

const CARD = `nexdeck-card: 1
slug: queue
name: Queue
version: "1.0.0"
requires: [sonarr]
requests:
  - id: queue
    path: /api/v3/queue
form: value
# how many are waiting
value: totalRecords
demo:
  queue: {totalRecords: 3}
`

const probed = { 'POST /cards/probe': { status: 200, body: SONARR_QUEUE } }

beforeEach(() => {
  prepare()
  stub(CARD, probed)
})

afterEach(async () => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  await i18next.changeLanguage('en')
})

async function probe() {
  await openCard('Queue')
  await waitFor(() => expect(screen.getByLabelText('Probe with')).toHaveValue('7'))
  await userEvent.click(screen.getAllByRole('button', { name: 'Probe' })[0])
  return screen.findByRole('tree', { name: 'Answer of the probe' })
}

const item = (name: RegExp) => screen.getByRole('treeitem', { name })

function dataTransfer() {
  const data: Record<string, string> = {}
  return {
    setData: (type: string, value: string) => void (data[type] = value),
    getData: (type: string) => data[type] ?? '',
    get types() {
      return Object.keys(data)
    },
    dropEffect: 'none',
    effectAllowed: 'all',
  }
}

describe('karten9: kinds, connection and requests', () => {
  it('karten9 AC-2: offers only switched-on connections of the kinds the card works with, and keeps the choice out of the card', async () => {
    await openCard('Queue')
    const select = screen.getByLabelText('Probe with')
    await waitFor(() => expect(select).toHaveValue('7'))
    const offered = within(select).getAllByRole('option').map((option) => option.textContent)
    expect(offered).toEqual(['Sonarr (NAS)'])
    // Another kind, and its connection is offered too.
    await userEvent.selectOptions(screen.getByLabelText('Another kind'), 'jellyfin')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    expect(readAt(editor().card!, ['requires'])).toEqual(['sonarr', 'jellyfin'])
    await userEvent.selectOptions(select, '8')
    expect(editor().integrationId).toBe(8)
    expect(editor().text).not.toContain('8')
    expect(editor().text).not.toContain('Jellyfin (')
  })

  it('karten9 AC-2: the requests are edited in place: name, path, how often, another one', async () => {
    await openCard('Queue')
    await userEvent.selectOptions(screen.getByLabelText('Ask every'), '5m')
    expect(editor().text).toContain('    every: 5m\n')
    expect(screen.getByRole('option', { name: '5 minutes' })).toBeInTheDocument()
    const path = screen.getByLabelText('Path')
    await userEvent.clear(path)
    await userEvent.type(path, '/api/v3/calendar')
    expect(readAt(editor().card!, ['requests', 0, 'path'])).toBe('/api/v3/calendar')
    // A new name takes the demo answer along.
    const name = screen.getByLabelText('Name of the request')
    await userEvent.clear(name)
    await userEvent.type(name, 'cal')
    expect(readAt(editor().card!, ['demo'])).toEqual({ cal: { totalRecords: 3 } })
    await userEvent.click(screen.getByRole('button', { name: 'Another request' }))
    expect(readAt(editor().card!, ['requests', 1])).toEqual({ id: 'request2', path: '/' })
    await userEvent.click(within(screen.getByRole('group', { name: 'Request 2' })).getByRole('button', { name: 'Remove this request' }))
    expect(readAt(editor().card!, ['requests'])).toHaveLength(1)
  })

  it('karten9 EC-6: without a connection of the kind it says so and leads to adding one', async () => {
    stub(CARD.replace('requires: [sonarr]', 'requires: [homeassistant]'), probed)
    await openCard('Queue')
    const note = await screen.findByTestId('card-no-connection')
    expect(note).toHaveTextContent('There is no connection of the kind Home Assistant yet.')
    expect(within(note).getByRole('link', { name: 'Add an integration' })).toHaveAttribute('href', '/system/integrations?add=homeassistant')
    expect(screen.getByRole('button', { name: 'Probe' })).toBeDisabled()
  })
})

describe('karten9: the probe and its tree', () => {
  it('karten9 AC-3: asks the path of the chosen connection and shows the answer as a tree with names, types and values', async () => {
    const tree = await probe()
    expect(sent('POST', '/cards/probe')[0].body).toEqual({ integration_id: 7, path: '/api/v3/queue' })
    expect(within(tree).getByRole('treeitem', { name: /^totalRecords, number, 1236/ })).toBeInTheDocument()
    expect(item(/^records, list, 1236 items/)).toHaveAttribute('aria-expanded', 'true')
    expect(item(/^title, text, "Example.Show.S02E05"/)).toHaveAttribute('aria-level', '4')
    // A row after the first starts closed, and opens with a click on its arrow.
    const second = item(/^\[1\], object, 3 fields/)
    expect(second).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(second.querySelector('button')!)
    expect(item(/^title, text, "Another.Show.S01E09"/)).toBeInTheDocument()
  })

  it('karten9 EC-1: a cut answer says so, and a long list ends in "… N more items"', async () => {
    await probe()
    expect(screen.getByText(/shown shortened: at most 500 fields/)).toBeInTheDocument()
    expect(screen.getByTestId('card-tree-more')).toHaveTextContent('… 1,234 more items')
    expect(screen.getByText(/14 fields shown/)).toBeInTheDocument()
  })

  it('karten9 EC-1: in German the number is written the German way', async () => {
    i18next.addResourceBundle('de', 'translation', { ...deScreen, ...editorDe }, true, true)
    await i18next.changeLanguage('de')
    stub(CARD, probed)
    await openCard('Queue')
    await waitFor(() => expect(screen.getByLabelText('Abfragen mit')).toHaveValue('7'))
    await userEvent.click(screen.getByRole('button', { name: 'Probe' }))
    expect(await screen.findByTestId('card-tree-more')).toHaveTextContent('… 1.234 weitere Einträge')
  })

  it('karten9 EC-2: a failed probe gives the reason the way a card does, in the language on screen', async () => {
    const failed = { status: 502, body: { detail: { code: 'auth_failed', message: 'Sonarr refused the API key (401).', hint: 'Check the key of the connection.' } } }
    stub(CARD, { 'POST /cards/probe': failed })
    await openCard('Queue')
    await waitFor(() => expect(screen.getByLabelText('Probe with')).toHaveValue('7'))
    await userEvent.click(screen.getByRole('button', { name: 'Probe' }))
    const note = await screen.findByTestId('card-failure')
    expect(note).toHaveTextContent('Sonarr refused the API key (401).')
    expect(note).toHaveTextContent('Check the key of the connection.')
    expect(note).toHaveAttribute('data-code', 'auth_failed')
    // Still signed in: a 502 is the service's, not the session's.
    expect(screen.queryByText('Sign in again to save')).toBeNull()

    i18next.addResourceBundle('de', 'translation', { ...deScreen, ...editorDe }, true, true)
    await act(() => i18next.changeLanguage('de'))
    expect(await screen.findByText(deScreen.errors.widget.auth_failed)).toBeInTheDocument()
  })

  it('karten9 EC-4: the answer stays in this tab, never in the draft kept in the browser', async () => {
    await probe()
    // A change makes a draft; the answer's values are not in it.
    await userEvent.selectOptions(screen.getByLabelText('Ask every'), '60s')
    const draft = localStorage.getItem(draftKey('queue'))
    expect(draft).toContain('every: 60s')
    expect(draft).not.toContain('Example.Show')
    expect(draft).not.toContain('downloading')
    expect(JSON.stringify(Object.fromEntries(Object.entries(localStorage)))).not.toContain('Example Show')
    expect(screen.getByText(/Only you see this answer/)).toBeInTheDocument()
  })
})

describe('karten9: from the tree onto the card', () => {
  it('karten9 AC-4: a field clicked goes on the place picked, the tree marks it, and the preview asks with it at once', async () => {
    await probe()
    fireEvent.click(item(/^sizeleft, number, 1024/))
    const menu = screen.getByRole('menu', { name: 'Use sizeleft as' })
    await userEvent.click(within(menu).getByRole('menuitem', { name: 'Use as Value' }))
    expect(editor().text).toContain('# how many are waiting\nvalue: records[0].sizeleft\n')
    expect(item(/^sizeleft, number, 1024, Value/)).toBeInTheDocument()
    await waitFor(() => expect(sent('POST', '/cards/preview').some((one) => String(one.body?.yaml).includes('value: records[0].sizeleft'))).toBe(true))
    expect(within(screen.getByTestId('card-place-value')).getByText('records[0].sizeleft')).toBeInTheDocument()
  })

  it('karten9 AC-4: a field dragged onto a place of the card goes there', async () => {
    await probe()
    const carried = dataTransfer()
    fireEvent.dragStart(item(/^totalRecords, number/), { dataTransfer: carried })
    editor().set(['value'], 'records')
    const place = screen.getByTestId('card-place-value')
    fireEvent.dragOver(place, { dataTransfer: carried })
    fireEvent.drop(place, { dataTransfer: carried })
    expect(readAt(editor().card!, ['value'])).toBe('totalRecords')
  })

  it('karten9 AC-5: a list is offered as a list or as pictures, asks before the value goes, and its fields go into each row', async () => {
    await probe()
    fireEvent.click(item(/^records, list/))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Show this list as a list' }))
    // The value has no room on a list: asked first, and Cancel keeps everything.
    expect(screen.getByRole('dialog', { name: 'Change the form?' })).toHaveTextContent('value')
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(readAt(editor().card!, ['form'])).toBe('value')
    fireEvent.click(item(/^records, list/))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Show this list as a list' }))
    await userEvent.click(screen.getByRole('button', { name: 'Change form' }))
    expect(readAt(editor().card!, ['form'])).toBe('list')
    expect(readAt(editor().card!, ['rows', 'select'])).toBe('records')
    expect(readAt(editor().card!, ['item', 'title'])).toBe('title')
    expect(readAt(editor().card!, ['value'])).toBeUndefined()
    expect(item(/^records, list, 1236 items, Shown as list/)).toBeInTheDocument()

    fireEvent.click(item(/^title, text, "Example Show"/))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Second line of each row' }))
    expect(readAt(editor().card!, ['item', 'subtitle'])).toBe('series.title')
    // The same field in another row is the same cell.
    fireEvent.click(item(/^\[1\], object/).querySelector('button')!)
    expect(item(/^title, text, "Another.Show.S01E09", Title/)).toBeInTheDocument()

    // A list at the top of the answer is the answer itself.
    stub(CARD, { 'POST /cards/probe': { status: 200, body: HA_STATES } })
    await userEvent.click(screen.getByRole('button', { name: 'Probe' }))
    fireEvent.click(await screen.findByRole('treeitem', { name: /^Answer, list/ }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Show this list as pictures' }))
    expect(readAt(editor().card!, ['form'])).toBe('posters')
    expect(readAt(editor().card!, ['rows', 'select'])).toBe('@')
    expect(readAt(editor().card!, ['item', 'title'])).toBe('title')
  })

  it('karten9 AC-5: with several requests a path starts with the name of its request', async () => {
    stub(CARD.replace('form: value', '  - id: other\n    path: /api/v3/system\nform: value'), probed)
    await probe()
    fireEvent.click(item(/^totalRecords, number/))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Use as Value' }))
    expect(readAt(editor().card!, ['value'])).toBe('queue.totalRecords')
  })

  it('karten9 EC-9: the arrow keys move through the tree, Enter opens "Use as …", Escape goes back', async () => {
    await probe()
    const top = item(/^Answer, object/)
    top.focus()
    await userEvent.keyboard('{ArrowDown}')
    expect(item(/^totalRecords/)).toHaveFocus()
    await userEvent.keyboard('{ArrowDown}')
    const records = item(/^records, list/)
    expect(records).toHaveFocus()
    await userEvent.keyboard('{ArrowLeft}')
    expect(records).toHaveAttribute('aria-expanded', 'false')
    await userEvent.keyboard('{ArrowRight}')
    expect(records).toHaveAttribute('aria-expanded', 'true')
    await userEvent.keyboard('{ArrowRight}')
    expect(item(/^\[0\], object/)).toHaveFocus()
    await userEvent.keyboard('{ArrowLeft}{ArrowLeft}')
    expect(records).toHaveFocus()
    await userEvent.keyboard('{End}')
    expect(item(/^\[1\], object/)).toHaveFocus()
    await userEvent.keyboard('{Home}')
    expect(top).toHaveFocus()
    await userEvent.keyboard('{ArrowDown}{Enter}')
    const menu = screen.getByRole('menu', { name: 'Use totalRecords as' })
    expect(within(menu).getByRole('menuitem', { name: 'Use as Value' })).toHaveFocus()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).toBeNull()
    expect(item(/^totalRecords/)).toHaveFocus()
    await userEvent.keyboard('{Enter}{Enter}')
    expect(readAt(editor().card!, ['value'])).toBe('totalRecords')
  })
})

describe('karten9: demo data from an answer', () => {
  it('karten9 AC-10: the disguised answer is shown first, a value can be changed, and only then it becomes the demo data', async () => {
    const disguised = { demo: { queue: { totalRecords: 871, records: [{ title: 'Amber.Valley.S07E01', sizeleft: 2048, done: false }] } }, cut: true }
    stub(CARD, { ...probed, 'POST /cards/demo': { status: 200, body: disguised } })
    await probe()
    await userEvent.click(screen.getByRole('button', { name: 'Use this answer as demo data' }))
    const dialog = await screen.findByRole('dialog', { name: 'Demo data from this answer' })
    expect(sent('POST', '/cards/demo')[0].body).toEqual({ yaml: editor().text, integration_id: 7 })
    expect(within(dialog).getByText('Long lists and texts were shortened.')).toBeInTheDocument()
    expect(within(dialog).getByLabelText('queue.records[0].title')).toHaveValue('Amber.Valley.S07E01')
    // Nothing is in the card yet.
    expect(readAt(editor().card!, ['demo'])).toEqual({ queue: { totalRecords: 3 } })
    const count = within(dialog).getByLabelText('queue.totalRecords')
    await userEvent.clear(count)
    await userEvent.type(count, '12')
    await userEvent.selectOptions(within(dialog).getByLabelText('queue.records[0].done'), 'true')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Use as demo data' }))
    expect(readAt(editor().card!, ['demo'])).toEqual({ queue: { totalRecords: 12, records: [{ title: 'Amber.Valley.S07E01', sizeleft: 2048, done: true }] } })
  })

  it('karten9 AC-10: Cancel leaves the demo data as it was', async () => {
    stub(CARD, { ...probed, 'POST /cards/demo': { status: 200, body: { demo: { queue: { totalRecords: 5 } } } } })
    await probe()
    await userEvent.click(screen.getByRole('button', { name: 'Use this answer as demo data' }))
    await screen.findByLabelText('queue.totalRecords')
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }))
    expect(readAt(editor().card!, ['demo'])).toEqual({ queue: { totalRecords: 3 } })
  })
})
