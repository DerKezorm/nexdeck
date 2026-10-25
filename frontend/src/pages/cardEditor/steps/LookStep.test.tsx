/**
 * Step 2, Look (KARTEN-9 AC-6, AC-7), and Step 3, Rules (AC-7): exactly the fields of the form, a change of form that
 * asks first, values, rows and rules set in forms or typed, and a placed field the probe's answer lacks.
 */
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { readAt } from '../../../lib/cardDocument'
import { editor, openCard, prepare, stub } from '../../../test/cardEditor'
import { SONARR_QUEUE } from '../../../test/probeAnswers'

const VALUE = `nexdeck-card: 1
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
`

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
  subtitle: series.title
`

beforeEach(() => {
  prepare()
  stub(VALUE, { 'POST /cards/probe': { status: 200, body: SONARR_QUEUE } })
})

afterEach(async () => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  await i18next.changeLanguage('en')
})

async function look(text = VALUE) {
  stub(text, { 'POST /cards/probe': { status: 200, body: SONARR_QUEUE } })
  await openCard('Queue')
  await userEvent.click(screen.getByRole('button', { name: '2 Look' }))
}

const fieldset = (name: string) => screen.getByRole('group', { name })

describe('karten9 AC-6: the fields of the form', () => {
  it('a number shows one value; numbers one per number; a list the cells of a row and which rows; pictures their cells', async () => {
    await look()
    expect(screen.getByRole('button', { name: /A number/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getAllByTestId(/^card-value-/).map((one) => one.dataset.testid)).toEqual(['card-value-value'])

    editor().setText(VALUE.replace('form: value\n# how many are waiting\nvalue: totalRecords\n', 'form: stats\nstats: [totalRecords, "records[0].sizeleft"]\n'))
    await waitFor(() => expect(screen.getAllByTestId(/^card-value-/).map((one) => one.dataset.testid)).toEqual(['card-value-stats[0]', 'card-value-stats[1]']))
    expect(screen.queryByRole('button', { name: /Remove number/ })).toBeNull()

    editor().setText(LIST)
    await waitFor(() => expect(screen.getAllByTestId(/^card-value-/).map((one) => one.dataset.testid)).toEqual(['card-value-item.title', 'card-value-item.subtitle', 'card-value-item.value', 'card-value-item.link', 'card-value-item.image']))
    expect(screen.getByRole('group', { name: 'Which rows' })).toBeInTheDocument()
    // A cell of a row has no label of its own and no total.
    expect(within(screen.getByTestId('card-value-item.title')).queryByText('Label')).toBeNull()
    expect(within(screen.getByTestId('card-value-item.title')).queryByRole('option', { name: 'A total over rows' })).toBeNull()

    editor().setText(LIST.replace('form: list', 'form: posters'))
    await waitFor(() => expect(screen.getAllByTestId(/^card-value-/).map((one) => one.dataset.testid)).toEqual(['card-value-item.image', 'card-value-item.title', 'card-value-item.subtitle', 'card-value-item.link']))
  })

  it('a change of form that takes something away asks first; one that takes nothing does not', async () => {
    await look()
    await userEvent.click(screen.getByRole('button', { name: /Numbers/ }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(readAt(editor().card!, ['stats'])).toEqual(['totalRecords'])
    expect(screen.getByText('A card of numbers shows at least 2.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Another number' }))
    expect(readAt(editor().card!, ['stats'])).toHaveLength(2)

    await userEvent.click(screen.getByRole('button', { name: /List/ }))
    const dialog = screen.getByRole('dialog', { name: 'Change the form?' })
    expect(dialog).toHaveTextContent('stats[0], stats[1]')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(readAt(editor().card!, ['form'])).toBe('stats')
    await userEvent.click(screen.getByRole('button', { name: /List/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Change form' }))
    expect(readAt(editor().card!, ['form'])).toBe('list')
    expect(readAt(editor().card!, ['stats'])).toBeUndefined()
  })
})

describe('karten9 AC-7: values and rows in forms, or typed', () => {
  it('a value: picked from the fields of the probe, its format, digits, unit and label; a short value is written out long', async () => {
    await openCard('Queue')
    await userEvent.click(screen.getAllByRole('button', { name: 'Probe' })[0])
    await screen.findByRole('tree')
    await userEvent.click(screen.getByRole('button', { name: '2 Look' }))
    const value = screen.getByTestId('card-value-value')
    const field = within(value).getByLabelText('Field')
    expect(field.getAttribute('list')).toBeTruthy()
    const offered = [...document.getElementById(field.getAttribute('list')!)!.querySelectorAll('option')].map((option) => option.getAttribute('value'))
    expect(offered).toContain('records[0].sizeleft')
    fireEvent.change(field, { target: { value: 'records[0].sizeleft' } })
    expect(editor().text).toContain('# how many are waiting\nvalue: records[0].sizeleft\n')
    await userEvent.selectOptions(within(value).getByLabelText('Format'), 'bytes')
    expect(readAt(editor().card!, ['value'])).toEqual({ path: 'records[0].sizeleft', format: 'bytes' })
    await userEvent.type(within(value).getByLabelText('Digits'), '1')
    await userEvent.type(within(value).getByLabelText('Unit'), 'left')
    await userEvent.type(within(value).getByLabelText('Label'), 'Still to load')
    expect(readAt(editor().card!, ['value'])).toEqual({ path: 'records[0].sizeleft', format: 'bytes', digits: 1, unit: 'left', label: 'Still to load' })
  })

  it('a value from a formula, a text with fields or a total, and the field it read goes along', async () => {
    await look()
    const value = screen.getByTestId('card-value-value')
    await userEvent.selectOptions(within(value).getByLabelText('Comes from'), 'formula')
    expect(readAt(editor().card!, ['value'])).toEqual({ formula: '{totalRecords}' })
    const formula = within(value).getByLabelText('Formula')
    fireEvent.change(formula, { target: { value: '{totalRecords} * 2' } })
    expect(readAt(editor().card!, ['value', 'formula'])).toBe('{totalRecords} * 2')
    await userEvent.selectOptions(within(value).getByLabelText('Comes from'), 'template')
    expect(readAt(editor().card!, ['value'])).toEqual({ template: '{totalRecords}' })
    await userEvent.selectOptions(within(value).getByLabelText('Comes from'), 'total')
    expect(readAt(editor().card!, ['value'])).toEqual({ total: { fn: 'count', rows: { select: 'totalRecords' } } })
    await userEvent.selectOptions(within(value).getByLabelText('Work out'), 'sum')
    fireEvent.change(within(value).getByLabelText('Of the field'), { target: { value: 'sizeleft' } })
    expect(readAt(editor().card!, ['value', 'total'])).toEqual({ fn: 'sum', rows: { select: 'totalRecords' }, field: 'sizeleft' })
    // A total has no one field to go back to: the whole answer, until a field is picked.
    await userEvent.selectOptions(within(value).getByLabelText('Comes from'), 'path')
    expect(readAt(editor().card!, ['value'])).toEqual({ path: '@' })
  })

  it('which rows: filters, order and how many, without typing an expression; an expression typed is taken as it is', async () => {
    await look(LIST)
    const rows = fieldset('Which rows')
    await userEvent.click(within(rows).getByRole('button', { name: 'Filter' }))
    const filter = within(rows).getByRole('group', { name: 'Filter 1' })
    fireEvent.change(within(filter).getByLabelText('Field of the row'), { target: { value: 'status' } })
    await userEvent.selectOptions(within(filter).getByLabelText('Comparison'), '!=')
    await userEvent.type(within(filter).getByLabelText('Value'), 'completed')
    expect(readAt(editor().card!, ['rows', 'filter'])).toEqual([{ field: 'status', op: '!=', value: 'completed' }])
    fireEvent.change(within(rows).getByLabelText('Field to sort by'), { target: { value: 'sizeleft' } })
    await userEvent.selectOptions(within(rows).getByLabelText('Order'), 'desc')
    await userEvent.type(within(rows).getByLabelText('How many rows'), '5')
    expect(readAt(editor().card!, ['rows'])).toEqual({ select: 'records', filter: [{ field: 'status', op: '!=', value: 'completed' }], sort: { field: 'sizeleft', desc: true }, limit: 5 })
    // A number typed as the value of a filter is a number.
    await userEvent.clear(within(filter).getByLabelText('Value'))
    await userEvent.type(within(filter).getByLabelText('Value'), '0')
    expect(readAt(editor().card!, ['rows', 'filter', 0, 'value'])).toBe(0)
    await userEvent.click(within(rows).getByRole('button', { name: 'Remove filter 1' }))
    expect(readAt(editor().card!, ['rows', 'filter'])).toBeUndefined()
    // An expression stays an expression, and nothing is left to the YAML view for it.
    fireEvent.change(within(rows).getByLabelText('Rows from'), { target: { value: 'records[?sizeleft > `0`]' } })
    expect(readAt(editor().card!, ['rows', 'select'])).toBe('records[?sizeleft > `0`]')
    expect(screen.queryByTestId('card-adjusted')).toBeNull()
  })

  it('a placed field the probe answer lacks is named, with the row', async () => {
    stub(LIST, { 'POST /cards/probe': { status: 200, body: SONARR_QUEUE } })
    await openCard('Queue')
    await userEvent.click(screen.getAllByRole('button', { name: 'Probe' })[0])
    await screen.findByRole('tree')
    await userEvent.click(screen.getByRole('button', { name: '2 Look' }))
    expect(screen.getByTestId('card-missing')).toHaveTextContent('Row 2 has no series.title; its Second line shows “–”.')
  })
})

describe('karten9 AC-7: rules in forms', () => {
  it('a rule of the card, of a value and of each row: what, how, with what, which colour', async () => {
    await look(LIST.replace('  subtitle: series.title\n', '  subtitle: series.title\n  value: sizeleft\n'))
    await userEvent.click(screen.getByRole('button', { name: '3 Rules' }))
    const whole = screen.getByTestId('card-rules-rules')
    expect(within(whole).getByText('No rules: the card stays green.')).toBeInTheDocument()
    await userEvent.click(within(whole).getByRole('button', { name: 'Rule' }))
    expect(readAt(editor().card!, ['rules'])).toEqual([{ value: '@', op: '>', than: 0, then: 'warn' }])
    const rule = within(whole).getByRole('group', { name: 'Rule 1' })
    fireEvent.change(within(rule).getByLabelText('a field'), { target: { value: 'length(records)' } })
    await userEvent.selectOptions(within(rule).getByLabelText('Comparison'), '>=')
    await userEvent.clear(within(rule).getByLabelText('Compared with'))
    await userEvent.type(within(rule).getByLabelText('Compared with'), '25')
    await userEvent.selectOptions(within(rule).getByLabelText('Colour'), 'bad')
    expect(readAt(editor().card!, ['rules'])).toEqual([{ value: 'length(records)', op: '>=', than: 25, then: 'bad' }])
    await userEvent.selectOptions(within(rule).getByLabelText('What is compared'), 'formula')
    expect(readAt(editor().card!, ['rules', 0])).toEqual({ formula: '{length(records)}', op: '>=', than: 25, then: 'bad' })

    // Each row: its own value by default, and a word compared as a word.
    const row = screen.getByTestId('card-rules-item.status')
    await userEvent.click(within(row).getByRole('button', { name: 'Rule' }))
    const first = within(row).getByRole('group', { name: 'Rule 1' })
    expect(within(first).getByLabelText('What is compared')).toHaveValue('own')
    await userEvent.selectOptions(within(first).getByLabelText('Comparison'), '==')
    await userEvent.clear(within(first).getByLabelText('Compared with'))
    await userEvent.type(within(first).getByLabelText('Compared with'), 'warning')
    expect(readAt(editor().card!, ['item', 'status'])).toEqual([{ op: '==', than: 'warning', then: 'warn' }])
    await userEvent.click(within(first).getByRole('button', { name: 'Remove rule 1' }))
    expect(readAt(editor().card!, ['item', 'status'])).toBeUndefined()
  })

  it('a rule on a value written short writes the value out long first', async () => {
    await look()
    await userEvent.click(screen.getByRole('button', { name: '3 Rules' }))
    await userEvent.click(within(screen.getByTestId('card-rules-value.rules')).getByRole('button', { name: 'Rule' }))
    expect(readAt(editor().card!, ['value'])).toEqual({ path: 'totalRecords', rules: [{ op: '>', than: 0, then: 'warn' }] })
    expect(editor().text).toContain('# how many are waiting\nvalue:\n')
  })
})
