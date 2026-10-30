/**
 * B1 of the second security review: when nexdeck checked a proposal through a connection other than the chosen one (the
 * card names another kind), the proposal says which one it asked. The server is replaced; no provider is asked.
 */
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import de from '../../i18n/editor.de.json'
import es from '../../i18n/editor.es.json'
import fr from '../../i18n/editor.fr.json'
import it_ from '../../i18n/editor.it.json'

import { useAssistant } from '../../lib/assistant'
import { openCard, prepare, stub } from '../../test/cardEditor'
import { useCardAi } from './ai'

const CARD = `nexdeck-card: 1
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

const PROVIDER = { ready: true, provider: 'anthropic', model: 'claude-sonnet-5-5', leaves_the_house: true, keep_days: 30 }
const SUMMARY = { connection_kind: 'radarr', path: '/api/v3/movie', form: 'value', buttons: false }

function offer(asked: { name: string; kind: string } | null) {
  const answer = { ok: true, yaml: CARD.replace('sonarr', 'radarr'), summary: { ...SUMMARY, asked }, sent: { values: true } }
  stub(CARD, { 'GET /assistant': { status: 200, body: PROVIDER }, 'POST /cards/ai': { status: 200, body: answer } })
}

async function propose() {
  await openCard('Queue')
  await userEvent.click(await screen.findByRole('button', { name: 'Ask AI' }))
  const inside = within(await screen.findByTestId('card-ai'))
  await userEvent.type(inside.getByRole('textbox'), 'show my films')
  await userEvent.click(inside.getByRole('button', { name: 'Change the card' }))
  return within(await screen.findByTestId('card-ai-proposal'))
}

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

describe('karten8t b1: the proposal names a connection asked in place of the chosen one', () => {
  it('says which connection was asked and that no values of it went out', async () => {
    offer({ name: 'Film shelf', kind: 'radarr' })
    const proposal = await propose()
    const sentence = proposal.getByTestId('card-ai-asked').textContent ?? ''
    expect(sentence).toContain('Film shelf (radarr)')
    expect(sentence).toContain('no values')
  })

  it('says nothing when the chosen connection was asked', async () => {
    offer(null)
    const proposal = await propose()
    expect(proposal.getByTestId('card-ai-summary')).toBeInTheDocument()
    expect(proposal.queryByTestId('card-ai-asked')).toBeNull()
  })

  it('has the sentence in the other four languages, with the name and the kind', () => {
    for (const words of [de, es, fr, it_]) {
      const sentence = (words as { editor: { ai: { summary: { asked: string } } } }).editor.ai.summary.asked
      expect(sentence).toContain('{{name}} ({{kind}})')
    }
  })

})
