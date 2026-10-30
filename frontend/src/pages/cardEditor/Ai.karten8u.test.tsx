/**
 * B1 of a review of 1.0.2: the card help asks on its own only paths the administrator named or that nexdeck's own cards of
 * the kind read. A proposal with another path says which one was not asked and when it will be. The server is replaced;
 * no provider is asked.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAssistant } from '../../lib/assistant'
import { openCard, prepare, stub } from '../../test/cardEditor'
import { useCardAi } from './ai'
import { DraftSummary } from './DraftPreview'

const CARD = `nexdeck-card: 1
slug: queue
name: Queue
version: "1.0.0"
requires: [watchtower]
requests:
  - id: state
    path: /v1/status
form: value
value: state
`

const PROVIDER = { ready: true, provider: 'anthropic', model: 'claude-sonnet-5-5', leaves_the_house: true, keep_days: 30 }
const SUMMARY = { connection_kind: 'watchtower', path: '/v1/metrics', form: 'value', buttons: false, asked: null }

beforeEach(() => {
  prepare()
  useAssistant.setState({ state: null })
  useCardAi.getState().reset()
})

afterEach(async () => {
  useCardAi.getState().reset()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  await i18next.changeLanguage('en')
})

describe('a path the card help did not ask', () => {
  it('karten8u b1: the proposal names it and says it is asked with the preview of real data', async () => {
    const answer = { ok: true, yaml: CARD.replace('/v1/status', '/v1/metrics'), summary: { ...SUMMARY, unasked: ['/v1/metrics'] }, sent: { values: false } }
    stub(CARD, { 'GET /assistant': { status: 200, body: PROVIDER }, 'POST /cards/ai': { status: 200, body: answer } })
    await openCard('Queue')
    await userEvent.click(await screen.findByRole('button', { name: 'Ask AI' }))
    const inside = within(await screen.findByTestId('card-ai'))
    await userEvent.type(inside.getByRole('textbox'), 'show the metrics')
    await userEvent.click(inside.getByRole('button', { name: 'Change the card' }))
    const proposal = within(await screen.findByTestId('card-ai-proposal'))
    const said = proposal.getByTestId('card-ai-unasked')
    expect(said).toHaveTextContent('/v1/metrics')
    expect(said).toHaveTextContent('open the preview with real data')
  })

  it('karten8u b1: nothing is said when every path was asked', () => {
    render(<DraftSummary summary={{ ...SUMMARY, unasked: [] }} />)
    expect(screen.queryByTestId('card-ai-unasked')).toBeNull()
  })
})
