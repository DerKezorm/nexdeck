/**
 * The preview (KARTEN-9 AC-9, EC-2, EC-5): the card from `POST /cards/preview` in the frame of the board, live data
 * or demo data, light or dark, card style, the sizes of its form and a phone, failures as the card shows them.
 */
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { editor, openCard, prepare, sent, stub } from '../../test/cardEditor'
import { pixelsOf, PREVIEW_MS, sizesOf } from './Preview'

const CARD = `nexdeck-card: 1
slug: queue
name: Queue
version: "1.0.0"
requires: [sonarr]
requests:
  - id: queue
    path: /api/v3/queue
form: value
value: {path: totalRecords, label: Waiting}
demo:
  queue: {totalRecords: 3}
`

const SHOWN = { status: 'ok', primary: { value: 1236, text: '1236', format: 'number', label: 'Waiting' }, secondary: [], items: [], meta: { custom: true } }

beforeEach(() => {
  prepare()
  stub(CARD, { 'POST /cards/preview': { status: 200, body: SHOWN } })
})

afterEach(async () => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  delete document.documentElement.dataset.cards
  await i18next.changeLanguage('en')
})

const previews = () => sent('POST', '/cards/preview')
const stage = () => screen.getByTestId('card-preview-stage')
const preview = () => screen.getByTestId('card-preview')

describe('karten9 AC-9: the card as the board shows it', () => {
  it('asks with the live data of the chosen connection and draws the card in the frame of the board', async () => {
    await openCard('Queue')
    await waitFor(() => expect(previews().some((one) => one.body?.integration_id === 7)).toBe(true))
    expect(previews().find((one) => one.body?.integration_id === 7)?.body).toEqual({ yaml: CARD, integration_id: 7 })
    const card = await within(preview()).findByRole('region', { name: 'Queue' })
    expect(card).toHaveTextContent('1,236')
    expect(card).toHaveTextContent('Waiting')
    expect(within(preview()).getByRole('button', { name: 'Live data' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('switches to the demo data of the card, and without a connection has only those', async () => {
    await openCard('Queue')
    await userEvent.click(within(preview()).getByRole('button', { name: 'Demo data' }))
    await waitFor(() => expect(previews().at(-1)?.body).toEqual({ yaml: CARD, demo: true }))

    stub(CARD.replace('[sonarr]', '[homeassistant]'), { 'POST /cards/preview': { status: 200, body: SHOWN } })
    editor().set(['requires'], ['homeassistant'])
    await waitFor(() => expect(within(preview()).queryByRole('button', { name: 'Live data' })).toBeNull())
    await waitFor(() => expect(previews().at(-1)?.body?.demo).toBe(true))
    expect(previews().at(-1)?.body?.integration_id).toBeUndefined()
  })

  it('waits until the typing stops before it asks again', async () => {
    await openCard('Queue')
    await waitFor(() => expect(previews().length).toBeGreaterThan(0))
    const before = previews().length
    const pause = () => new Promise((resolve) => setTimeout(resolve, PREVIEW_MS / 4))
    act(() => editor().set(['value', 'label'], 'W', 'typing'))
    await pause()
    act(() => editor().set(['value', 'label'], 'Wa', 'typing'))
    await pause()
    act(() => editor().set(['value', 'label'], 'Wait', 'typing'))
    await new Promise((resolve) => setTimeout(resolve, PREVIEW_MS + 300))
    await waitFor(() => expect(previews().length).toBe(before + 1))
    expect(String(previews().at(-1)?.body?.yaml)).toContain('label: Wait}')
  })

  it('light or dark, whatever the page is in', async () => {
    await openCard('Queue')
    expect(stage()).not.toHaveAttribute('data-theme')
    await userEvent.click(within(preview()).getByRole('button', { name: 'Light' }))
    expect(stage()).toHaveAttribute('data-theme', 'light')
    await userEvent.click(within(preview()).getByRole('button', { name: 'Dark' }))
    expect(stage()).not.toHaveAttribute('data-theme')
  })

  it('in every card style, handed back when the editor goes', async () => {
    const view = await openCard('Queue')
    await userEvent.click(within(preview()).getByRole('button', { name: 'Neon' }))
    expect(document.documentElement.dataset.cards).toBe('neon')
    await userEvent.click(within(preview()).getByRole('button', { name: 'Glass' }))
    expect(document.documentElement.dataset.cards).toBeUndefined()
    await userEvent.click(within(preview()).getByRole('button', { name: 'Outline' }))
    view.unmount()
    expect(document.documentElement.dataset.cards).toBeUndefined()
  })

  it('in the sizes of its form, and on a phone', async () => {
    await openCard('Queue')
    const sizes = within(screen.getByRole('group', { name: 'Size' })).getAllByRole('button').map((button) => button.textContent)
    expect(sizes).toEqual(['1 × 1', '2 × 2', '4 × 3', 'Phone'])
    expect(stage()).toHaveAttribute('data-size', '2x2')
    await userEvent.click(within(preview()).getByRole('button', { name: '4 × 3' }))
    expect(stage()).toHaveAttribute('data-size', '4x3')
    await waitFor(() => expect(screen.getByTestId('card-preview-card')).toHaveStyle({ width: '404px', height: '228px' }))
    await userEvent.click(within(preview()).getByRole('button', { name: 'Phone' }))
    expect(stage()).toHaveAttribute('data-size', 'phone 4x3')
    expect(screen.getByTestId('card-preview-card')).toHaveStyle({ width: '358px' })
  })

  it('karten9 EC-2: a failure of the service shows on the card as it would on the board', async () => {
    stub(CARD, { 'POST /cards/preview': { status: 502, body: { detail: { code: 'unreachable', message: 'Sonarr could not be reached.', hint: 'Check the address.' } } } })
    await openCard('Queue')
    expect(await within(preview()).findByTestId('card-error')).toHaveTextContent('Sonarr could not be reached.')
  })

  it('a card that cannot be shown yet names its problems instead', async () => {
    const problems = [{ code: 'card_blank', message: 'This must not be empty.', path: 'value.label', line: 10, params: {} }]
    stub(CARD, { 'POST /cards/preview': { status: 400, body: { detail: { code: 'card_invalid', message: 'This card cannot be saved.', problems } } } })
    await openCard('Queue')
    const invalid = await within(preview()).findByTestId('card-preview-invalid')
    expect(invalid).toHaveTextContent('The card cannot be shown yet:')
    expect(invalid).toHaveTextContent('value.label:')
  })
})

describe('karten9 AC-9: the sizes', () => {
  it('a form offers its smallest size, the one it is made at and a larger one; the card can ask for its own', () => {
    expect(sizesOf({ form: 'value' })).toEqual([[1, 1], [2, 2], [4, 3]])
    expect(sizesOf({ form: 'posters' })).toEqual([[2, 2], [4, 3], [6, 4]])
    expect(sizesOf({ form: 'list', size: { w: 4, h: 4 }, min_size: { w: 3, h: 2 } })).toEqual([[3, 2], [4, 4], [6, 5]])
  })

  it('a size in pixels as the board lays it out, half or the whole width on a phone', () => {
    expect(pixelsOf([2, 2], false)).toEqual({ width: 196, height: 148 })
    expect(pixelsOf([2, 2], true)).toEqual({ width: 173, height: 148 })
    expect(pixelsOf([3, 3], true)).toEqual({ width: 358, height: 228 })
  })
})
