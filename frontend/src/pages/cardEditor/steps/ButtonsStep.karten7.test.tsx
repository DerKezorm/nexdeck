/**
 * The Buttons step for a card put together from blocks (KARTEN-7): a button on each row needs a list block.
 */
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { openCard, prepare, stub } from '../../../test/cardEditor'

const CARD = (blocks: string) => `nexdeck-card: 1
slug: queue
name: Queue
version: "1.0.0"
requires: [sonarr]
requests:
  - id: queue
    path: /api/v3/queue
form: builder
rows: {select: records}
blocks:
${blocks}
buttons:
  - {id: go, label: Go, where: card, method: POST, path: /x}
`

beforeEach(() => prepare())
afterEach(async () => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  await i18next.changeLanguage('en')
})

async function buttons(blocks: string) {
  stub(CARD(blocks), {})
  await openCard('Queue')
  await userEvent.click(screen.getByRole('button', { name: '4 Buttons' }))
  return within(await screen.findByTestId('card-button-0')).getByLabelText('Where')
}

describe('the Buttons step of a card of blocks', () => {
  it('karten7 ac1 offers a button on each row when the card has a list block', async () => {
    const where = await buttons('  - type: list\n    item:\n      - {type: text, text: a}')
    expect(within(where).getByRole('option', { name: 'On each row' })).toBeEnabled()
  })

  it('karten7 ac1 offers a button on each row only with a list block', async () => {
    const where = await buttons('  - {type: text, text: a}')
    expect(within(where).getByRole('option', { name: 'On each row' })).toBeDisabled()
  })
})
