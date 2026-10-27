/**
 * Step 4, Buttons (KARTEN-8): one form per button, written into the card's own `buttons:`; content as rows of a form,
 * content the form cannot show left as written, the most there may be, inputs with their range, "Use in button" from
 * the tree, and the guided way's one line.
 */
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { readAt } from '../../../lib/cardDocument'
import { editor, openCard, prepare, stub } from '../../../test/cardEditor'
import { SONARR_QUEUE } from '../../../test/probeAnswers'

const LIST = `nexdeck-card: 1
slug: queue
name: Queue
version: "1.0.0"
requires: [sonarr]
requests:
  - id: queue
    path: /api/v3/queue
form: list
rows: {select: records}
item:
  title: title
# the buttons
buttons:
  - id: pause
    label: Pause
    where: row
    method: POST
    path: /api/pause
    send: form
    body: {hashes: "{id}"}
  - id: limit
    label: Limit speed
    method: POST
    path: /api/limit
`

const VALUE = `nexdeck-card: 1
slug: queue
name: Queue
version: "1.0.0"
requires: [sonarr]
requests:
  - id: queue
    path: /api/v3/queue
form: value
value: totalRecords
`

beforeEach(() => {
  prepare()
})

afterEach(async () => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  await i18next.changeLanguage('en')
})

async function buttons(text = LIST) {
  stub(text, { 'POST /cards/probe': { status: 200, body: SONARR_QUEUE } })
  await openCard('Queue')
  await userEvent.click(screen.getByRole('button', { name: '4 Buttons' }))
}

const form = (index: number) => screen.getByTestId(`card-button-${index}`)
const buttonAt = (index: number) => readAt(editor().card!, ['buttons', index]) as Record<string, unknown>

describe('the Buttons step', () => {
  it('karten8 ac1 comes between Rules and Texts and shows one form per button', async () => {
    await buttons()
    expect(screen.getAllByRole('button', { name: /^\d Rules|^\d Buttons|^\d Texts/ }).map((one) => one.textContent)).toEqual(['3 Rules', '4 Buttons', '5 Texts'])
    expect(screen.getByTestId('card-button-0')).toBeInTheDocument()
    expect(screen.getByTestId('card-button-1')).toBeInTheDocument()
    expect(within(form(0)).getByLabelText('Address of the request')).toHaveValue('/api/pause')
    expect(within(form(1)).getByLabelText('Method')).toHaveValue('POST')
    // The button on each row is offered, and the buttons are not shown as "adjusted in YAML".
    expect(screen.queryByTestId('card-adjusted')).toBeNull()
  })

  it('karten8 ac1 writes what is typed into the card and keeps the comments and the other buttons', async () => {
    await buttons()
    const path = within(form(1)).getByLabelText('Address of the request')
    await userEvent.clear(path)
    await userEvent.type(path, '/api/speed')
    await userEvent.selectOptions(within(form(1)).getByLabelText('Method'), 'PUT')
    await userEvent.type(within(form(1)).getByLabelText('Symbol'), 'gauge')
    expect(buttonAt(1)).toMatchObject({ id: 'limit', method: 'PUT', path: '/api/speed', icon: 'gauge' })
    expect(buttonAt(0)).toMatchObject({ id: 'pause', path: '/api/pause' })
    expect(editor().text).toContain('# the buttons')
  })

  it('karten8 ac1 adds a button that is valid at once and removes the last one with the whole list', async () => {
    await buttons(VALUE)
    expect(screen.getByText('This card has no buttons yet.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Add button' }))
    expect(buttonAt(0)).toEqual({ id: 'button', label: 'New button', where: 'card', method: 'POST', path: '/' })
    await userEvent.click(screen.getByRole('button', { name: 'Add button' }))
    expect(buttonAt(1).id).toBe('button_2')
    await userEvent.click(screen.getByRole('button', { name: 'Remove button 2' }))
    await userEvent.click(screen.getByRole('button', { name: 'Remove button 1' }))
    expect(readAt(editor().card!, ['buttons'])).toBeUndefined()
  })

  it('karten8 ac10 offers no eleventh button and says why', async () => {
    const many = VALUE + 'buttons:\n' + Array.from({ length: 10 }, (_, n) => `  - {id: b${n}, label: B${n}, method: POST, path: /x}\n`).join('')
    await buttons(many)
    expect(screen.getByRole('button', { name: 'Add button' })).toBeDisabled()
    expect(screen.getByText('A card has at most 10 buttons.')).toBeInTheDocument()
  })

  it('karten8 ac1 moves a button up and down with its comment', async () => {
    await buttons()
    await userEvent.click(within(form(1)).getByRole('button', { name: 'Move button up' }))
    expect((readAt(editor().card!, ['buttons']) as { id: string }[]).map((one) => one.id)).toEqual(['limit', 'pause'])
    expect(editor().text).toContain('# the buttons')
    expect(within(form(0)).getByRole('button', { name: 'Move button up' })).toBeDisabled()
  })

  it('karten8 ac1 offers a button on each row only for a card with rows', async () => {
    await buttons(VALUE + 'buttons:\n  - {id: go, label: Go, method: POST, path: /x}\n')
    expect(within(form(0)).getByRole('option', { name: 'On each row' })).toBeDisabled()
    expect(screen.getByText(/needs a card that shows a list or pictures/)).toBeInTheDocument()
  })
})

describe('the content of a button', () => {
  it('karten8 ec8 is written as lines of a name and a value, in the way the button sends it', async () => {
    await buttons()
    const group = within(form(0)).getByRole('group', { name: 'Content sent' })
    await userEvent.type(within(group).getByLabelText('Value of hashes'), '{{name}')
    expect(buttonAt(0).body).toEqual({ hashes: '{id}{name}' })
    await userEvent.click(within(group).getByRole('button', { name: 'Add a line' }))
    expect(buttonAt(0).body).toEqual({ hashes: '{id}{name}', field: '' })
    await userEvent.type(within(group).getByLabelText('Value of field'), 'true')
    // A form sends text; a JSON button sends the true it was given.
    expect(buttonAt(0).body).toMatchObject({ field: 'true' })
    await userEvent.selectOptions(within(form(0)).getByLabelText('Send as'), 'json')
    await userEvent.type(within(group).getByLabelText('Value of hashes'), '!')
    expect(buttonAt(0).body).toEqual({ hashes: '{id}{name}!', field: true })
  })

  it('karten8 ec8 renames a line when the field is left, and drops a line', async () => {
    await buttons()
    const group = within(form(0)).getByRole('group', { name: 'Content sent' })
    await userEvent.type(within(group).getAllByLabelText('Name')[0], '2{Enter}')
    expect(buttonAt(0).body).toEqual({ hashes2: '{id}' })
    await userEvent.click(within(group).getByRole('button', { name: 'Remove hashes2' }))
    expect(buttonAt(0).body).toBeUndefined()
  })

  it('karten8 ec8 leaves content with names inside names as it is and says where to change it', async () => {
    const nested = VALUE + 'buttons:\n  - id: go\n    label: Go\n    method: POST\n    path: /x\n    body: {outer: {inner: "{totalRecords}"}}\n'
    await buttons(nested)
    expect(screen.getByTestId('card-button-0-nested')).toHaveTextContent('Edit in YAML')
    await userEvent.type(within(form(0)).getByLabelText('Address of the request'), 'y')
    expect(buttonAt(0).body).toEqual({ outer: { inner: '{totalRecords}' } })
    await userEvent.click(screen.getByRole('button', { name: 'Edit in YAML' }))
    expect(editor().view).toBe('yaml')
  })
})

describe('asking and danger', () => {
  it('karten8 ac3 writes ask first and dangerous; dangerous includes the question', async () => {
    await buttons()
    const confirm = within(form(1)).getByLabelText('Ask first')
    await userEvent.click(confirm)
    expect(buttonAt(1).confirm).toBe(true)
    await userEvent.click(within(form(1)).getByLabelText('Dangerous'))
    expect(buttonAt(1)).toMatchObject({ confirm: true, danger: true })
    expect(confirm).toBeChecked()
    expect(confirm).toBeDisabled()
    await userEvent.click(within(form(1)).getByLabelText('Dangerous'))
    expect(buttonAt(1).danger).toBeUndefined()
    expect(confirm).toBeEnabled()
  })

  it('karten8 ac4 adds an input that takes a number with its range, and changes it into a choice', async () => {
    await buttons()
    await userEvent.click(within(form(1)).getByRole('button', { name: 'Add an input' }))
    expect((buttonAt(1).asks as unknown[])[0]).toEqual({ name: 'value', label: 'Value', type: 'number', min: 0, max: 100, step: 1 })
    const ask = within(form(1)).getByTestId('card-button-1-ask-0')
    const max = within(ask).getByLabelText('Highest')
    await userEvent.clear(max)
    await userEvent.type(max, '5000')
    expect((buttonAt(1).asks as Record<string, unknown>[])[0].max).toBe(5000)
    await userEvent.selectOptions(within(ask).getByLabelText('Kind'), 'choice')
    expect((buttonAt(1).asks as Record<string, unknown>[])[0]).toEqual({ name: 'value', label: 'Value', type: 'choice', options: [{ value: 'a', label: 'A' }] })
    // Back to text: what only a choice or a number has goes with it.
    await userEvent.selectOptions(within(ask).getByLabelText('Kind'), 'text')
    expect((buttonAt(1).asks as Record<string, unknown>[])[0]).toEqual({ name: 'value', label: 'Value', type: 'text' })
    await userEvent.click(within(ask).getByRole('button', { name: 'Remove input 1' }))
    expect(buttonAt(1).asks).toBeUndefined()
  })

  it('karten8 ac1 puts the words of a button in each language the card is written in', async () => {
    await buttons(LIST.replace('label: Pause', 'label: {en: Pause, de: Pausieren}'))
    await userEvent.type(within(form(0)).getByLabelText(/^Label, German|^Label, Deutsch/), '!')
    expect(buttonAt(0).label).toEqual({ en: 'Pause', de: 'Pausieren!' })
  })
})

describe('placing a field of the data in a button', () => {
  async function inTree(text: string, focus: () => Promise<void>) {
    stub(text, { 'POST /cards/probe': { status: 200, body: SONARR_QUEUE } })
    await openCard('Queue')
    await userEvent.click(screen.getByRole('button', { name: '4 Buttons' }))
    await focus()
    await userEvent.click(screen.getByRole('button', { name: '1 Source' }))
    await waitFor(() => expect(screen.getByLabelText('Probe with')).toHaveValue('7'))
    await userEvent.click(screen.getAllByRole('button', { name: 'Probe' })[0])
    await screen.findByRole('tree', { name: 'Answer of the probe' })
  }

  it('karten8 ac1 sets {field} at the end of the address last worked in', async () => {
    await inTree(VALUE + 'buttons:\n  - {id: go, label: Go, method: POST, path: /api/x/}\n', async () => {
      await userEvent.click(within(form(0)).getByLabelText('Address of the request'))
    })
    fireEvent.click(await screen.findByRole('treeitem', { name: /^totalRecords/ }))
    await userEvent.click(within(screen.getByRole('menu', { name: 'Use totalRecords as' })).getByRole('menuitem', { name: 'Use in button 1: {totalRecords}' }))
    expect(buttonAt(0).path).toBe('/api/x/{totalRecords}')
  })

  it('karten8 ac2 names a field of the row for a button on each row, and offers nothing outside a row', async () => {
    await inTree(LIST, async () => {
      await userEvent.click(within(form(0)).getByLabelText('Value of hashes'))
    })
    fireEvent.click((await screen.findAllByRole('treeitem', { name: /^title, text/ }))[0])
    await userEvent.click(within(screen.getByRole('menu', { name: 'Use title as' })).getByRole('menuitem', { name: 'Use in button 1: {title}' }))
    expect(buttonAt(0).body).toEqual({ hashes: '{id}{title}' })
    // totalRecords is not in a row, so it cannot go into a button on each row.
    fireEvent.click(screen.getByRole('treeitem', { name: /^totalRecords/ }))
    expect(within(screen.getByRole('menu', { name: 'Use totalRecords as' })).queryByRole('menuitem', { name: /Use in button/ })).toBeNull()
  })

  it('karten8 ac4 inserts an input of the button by its name', async () => {
    await buttons(LIST.replace('path: /api/limit', 'path: /api/limit\n    asks:\n      - {name: kib, label: KiB, type: number, min: 0, max: 9, step: 1}'))
    await userEvent.click(within(form(1)).getByLabelText('Address of the request'))
    await userEvent.click(within(form(1)).getByRole('button', { name: '{ask.kib}' }))
    expect(buttonAt(1).path).toBe('/api/limit{ask.kib}')
  })
})

describe('the guided way and the preview', () => {
  it('karten8 ac1 keeps a card with buttons in the guided way and names them in one line', async () => {
    stub(VALUE + 'buttons:\n  - {id: go, label: Go, method: POST, path: /x}\n  - {id: stop, label: Stop, method: POST, path: /y}\n', {})
    await openCard('Queue', 'guided')
    expect(editor().refusal).toBeNull()
    editor().setGuidedStep('finish')
    expect(await screen.findByTestId('card-guided-buttons')).toHaveTextContent('2 buttons · edit in All settings')
    await userEvent.click(within(screen.getByTestId('card-guided-buttons')).getByRole('button'))
    expect(editor().view).toBe('editor')
    expect(editor().step).toBe('buttons')
  })

  it('karten8 ac1 draws the buttons of the preview and says they do nothing', async () => {
    stub(VALUE + 'buttons:\n  - {id: go, label: Go, method: POST, path: /x}\n', {
      'POST /cards/preview': { status: 200, body: { status: 'ok', primary: { value: 1, text: '1', format: 'number' }, meta: { custom: true }, actions: [{ id: 'button:go', label: 'Go' }] } },
    })
    await openCard('Queue')
    const press = await screen.findByRole('button', { name: 'Go' }, { timeout: 3000 })
    expect(screen.queryByTestId('card-preview-buttons')).toBeNull()
    await userEvent.click(press)
    expect(screen.getByTestId('card-preview-buttons')).toHaveTextContent('Buttons do nothing in the preview.')
    // Nothing was sent to the service: no request other than the card's own reads.
    expect(fetchCalls().filter((one) => one.url.includes('/actions/'))).toHaveLength(0)
  })
})

function fetchCalls() {
  return (vi.mocked(globalThis.fetch).mock.calls as [RequestInfo | URL, RequestInit?][]).map(([url, init]) => ({ url: String(url), method: init?.method ?? 'GET' }))
}
