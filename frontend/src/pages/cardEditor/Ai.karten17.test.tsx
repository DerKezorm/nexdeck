/**
 * "Ask AI" in the card editor (KARTEN-17): the button only with a provider, what goes out, the proposal beside the
 * editor's own text, change and translate, one request at a time with Cancel, failures as sentences, the question
 * before leaving. The server is replaced; no provider is asked.
 */
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAssistant } from '../../lib/assistant'
import { editor, openCard, openNew, prepare, sent, stub, world } from '../../test/cardEditor'
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

const PROPOSED = `nexdeck-card: 1
slug: queue
name: {en: Queue, de: Warteschlange}
version: "1.0.0"
requires: [sonarr]
requests:
  - id: queue
    path: /api/v3/queue
form: value
value: {path: totalRecords, label: Waiting}
`

const ANSWER = {
  ok: true,
  yaml: PROPOSED,
  summary: { connection_kind: 'sonarr', path: '/api/v3/queue', form: 'value', buttons: false },
  sent: { values: false },
}

const PROVIDER = { ready: true, provider: 'anthropic', model: 'claude-sonnet-5-5', leaves_the_house: true, keep_days: 30 }

function offer(answers: Parameters<typeof stub>[1] = {}, text = CARD) {
  stub(text, { 'GET /assistant': { status: 200, body: PROVIDER }, 'POST /cards/ai': { status: 200, body: ANSWER }, ...answers })
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

const askButton = () => screen.queryByRole('button', { name: 'Ask AI' })
const panel = () => screen.getByTestId('card-ai')

async function openPanel() {
  await userEvent.click(await screen.findByRole('button', { name: 'Ask AI' }))
  return within(await screen.findByTestId('card-ai'))
}

async function typeDescription(text: string) {
  await userEvent.type(within(panel()).getByRole('textbox'), text)
}

describe('karten17 ac1: without a provider there are no AI buttons', () => {
  it('shows no button while no provider is set up', async () => {
    offer({ 'GET /assistant': { status: 200, body: { ...PROVIDER, ready: false, provider: 'off' } } })
    await openCard('Queue')
    await waitFor(() => expect(sent('GET', '/assistant').length).toBeGreaterThan(0))
    expect(askButton()).toBeNull()
  })

  it('shows the button once there is one', async () => {
    offer()
    await openCard('Queue')
    expect(await screen.findByRole('button', { name: 'Ask AI' })).toBeInTheDocument()
  })

  it('karten17 ec6: the button goes when the provider was removed while a request ran', async () => {
    let gone = false
    offer({
      'GET /assistant': () => ({ status: 200, body: gone ? { ...PROVIDER, ready: false, provider: 'off' } : PROVIDER }),
      'POST /cards/ai': () => {
        gone = true
        return { status: 409, body: { detail: { code: 'assistant_off', message: 'Off.' } } }
      },
    })
    await openCard('Queue')
    const inside = await openPanel()
    await typeDescription('make it bigger')
    await userEvent.click(inside.getByRole('button', { name: 'Change the card' }))
    await waitFor(() => expect(askButton()).toBeNull())
    expect(screen.queryByTestId('card-ai')).toBeNull()
  })
})

describe('karten17 ac2, ac9: what goes out', () => {
  it('names the provider, the model and what goes along, and sends the description without values', async () => {
    offer()
    await openCard('Queue')
    const inside = await openPanel()
    expect(inside.getByTestId('card-ai-hint')).toHaveTextContent('Anthropic')
    expect(inside.getByTestId('card-ai-hint')).toHaveTextContent('claude-sonnet-5-5')
    expect(inside.getByTestId('card-ai-hint')).toHaveTextContent('names and types of the fields')
    await typeDescription('show the waiting episodes')
    await userEvent.click(inside.getByRole('button', { name: 'Change the card' }))
    await screen.findByTestId('card-ai-proposal')
    expect(sent('POST', '/cards/ai')).toHaveLength(1)
    expect(sent('POST', '/cards/ai')[0].body).toMatchObject({ mode: 'change', description: 'show the waiting episodes', include_values: false, kind: 'sonarr', connection_id: 7, path: '/api/v3/queue', yaml: CARD })
  })

  it('says that the model runs in the own network when it does', async () => {
    offer({ 'GET /assistant': { status: 200, body: { ...PROVIDER, provider: 'openai', model: 'qwen3', leaves_the_house: false } } })
    await openCard('Queue')
    const inside = await openPanel()
    expect(inside.getByTestId('card-ai-hint')).toHaveTextContent('runs in your own network')
  })
})

describe('karten17 ac3: sample values', () => {
  it('goes along with one request only, then the box is empty again', async () => {
    offer()
    await openCard('Queue')
    const inside = await openPanel()
    expect(inside.getByRole('checkbox', { name: 'Include sample values' })).not.toBeChecked()
    await userEvent.click(inside.getByRole('checkbox', { name: 'Include sample values' }))
    await typeDescription('x')
    await userEvent.click(inside.getByRole('button', { name: 'Change the card' }))
    await screen.findByTestId('card-ai-proposal')
    expect(sent('POST', '/cards/ai')[0].body?.include_values).toBe(true)
    expect(inside.getByRole('checkbox', { name: 'Include sample values' })).not.toBeChecked()
  })
})

describe('karten17 ac5, ac10: a proposal beside the text', () => {
  it('changes nothing until it is accepted, then it is one step of the editor that can be undone', async () => {
    offer()
    await openCard('Queue')
    const inside = await openPanel()
    await typeDescription('label it')
    await userEvent.click(inside.getByRole('button', { name: 'Change the card' }))
    const proposal = within(await screen.findByTestId('card-ai-proposal'))
    expect(editor().text).toBe(CARD)
    const summary = within(proposal.getByTestId('card-ai-summary'))
    expect(summary.getByText('sonarr')).toBeInTheDocument()
    expect(summary.getByText('/api/v3/queue')).toBeInTheDocument()
    expect(summary.getByText('One value')).toBeInTheDocument()
    expect(summary.getByText('Read only')).toBeInTheDocument()
    await waitFor(() => expect(sent('POST', '/cards/preview').some((one) => one.body?.demo === true && one.body?.yaml === PROPOSED)).toBe(true))
    expect(editor().text).toBe(CARD)

    await userEvent.click(proposal.getByRole('button', { name: 'Accept' }))
    expect(editor().text).toBe(PROPOSED)
    expect(screen.queryByTestId('card-ai-proposal')).toBeNull()
    act(() => editor().undo())
    expect(editor().text).toBe(CARD)
  })

  it('throws it away on Discard', async () => {
    offer()
    await openCard('Queue')
    const inside = await openPanel()
    await typeDescription('label it')
    await userEvent.click(inside.getByRole('button', { name: 'Change the card' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Discard' }))
    expect(screen.queryByTestId('card-ai-proposal')).toBeNull()
    expect(editor().text).toBe(CARD)
  })

  it('shows the buttons the draft has', async () => {
    offer({ 'POST /cards/ai': { status: 200, body: { ...ANSWER, summary: { ...ANSWER.summary, buttons: true } } } })
    await openCard('Queue')
    const inside = await openPanel()
    await typeDescription('add a pause button')
    await userEvent.click(inside.getByRole('button', { name: 'Change the card' }))
    expect(await within(await screen.findByTestId('card-ai-summary')).findByText('With buttons')).toBeInTheDocument()
  })
})

describe('karten17 ac6: a card there is already', () => {
  it('sends its text for a change, and a new card for a new one', async () => {
    offer()
    await openCard('Queue')
    expect(editor().slug).toBe('queue')
    const inside = await openPanel()
    expect(inside.getByText('Describe what should change')).toBeInTheDocument()
    expect(inside.getByRole('button', { name: 'Change the card' })).toBeDisabled()
  })

  it('a card never saved is a new one: the description alone goes, no text', async () => {
    offer()
    await openNew()
    const inside = await openPanel()
    expect(inside.getByText('Describe the card you want')).toBeInTheDocument()
    await typeDescription('episodes waiting')
    await userEvent.click(inside.getByRole('button', { name: 'Create a card' }))
    await screen.findByTestId('card-ai-proposal')
    const body = sent('POST', '/cards/ai')[0].body!
    expect(body.mode).toBe('new')
    expect(body.yaml).toBeUndefined()
  })
})

describe('karten17 ac7: Translate', () => {
  it('asks for the missing languages of the card on screen', async () => {
    offer()
    await openCard('Queue')
    const inside = await openPanel()
    await userEvent.click(inside.getByRole('button', { name: 'Translate' }))
    await screen.findByTestId('card-ai-proposal')
    expect(sent('POST', '/cards/ai')[0].body).toMatchObject({ mode: 'translate', yaml: CARD })
    await userEvent.click(screen.getByRole('button', { name: 'Accept' }))
    expect(editor().text).toBe(PROPOSED)
  })
})

describe('karten17 ac8: one request at a time, and Cancel', () => {
  it('locks the buttons while it runs, and Cancel stops it for good', async () => {
    offer()
    const original = globalThis.fetch
    let release: (response: Response) => void = () => undefined
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input).endsWith('/cards/ai') && init?.method === 'POST') {
          world.sent.push({ url: '/cards/ai', method: 'POST', body: JSON.parse(String(init.body)) })
          return new Promise<Response>((resolve) => {
            release = resolve
          })
        }
        return original(input, init)
      }),
    )
    await openCard('Queue')
    const inside = await openPanel()
    await typeDescription('label it')
    await userEvent.click(inside.getByRole('button', { name: /Change the card/ }))
    expect(inside.getByRole('button', { name: /Change the card/ })).toBeDisabled()
    expect(inside.getByRole('button', { name: 'Translate' })).toBeDisabled()
    await userEvent.click(inside.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(sent('DELETE', '/cards/ai')).toHaveLength(1))
    expect(inside.getByRole('button', { name: /Change the card/ })).toBeEnabled()
    // The answer that still arrives is not shown.
    await act(async () => {
      release(new Response(JSON.stringify(ANSWER), { status: 200, headers: { 'content-type': 'application/json' } }))
    })
    expect(screen.queryByTestId('card-ai-proposal')).toBeNull()
    expect(sent('POST', '/cards/ai')).toHaveLength(1)
  })
})

describe('karten17 ec1, ec4: a failure is a sentence and the card stays as it was', () => {
  it('says the provider could not be reached, with the reason', async () => {
    offer({ 'POST /cards/ai': { status: 502, body: { detail: { code: 'ai_unreachable', message: 'Connection refused.' } } } })
    await openCard('Queue')
    const inside = await openPanel()
    await typeDescription('label it')
    await userEvent.click(inside.getByRole('button', { name: 'Change the card' }))
    expect(await screen.findByTestId('card-ai-error')).toHaveTextContent('The AI service could not be reached: Connection refused.')
    expect(editor().text).toBe(CARD)
    expect(screen.queryByTestId('card-ai-proposal')).toBeNull()
  })

  it('gives a limit in the words of the provider', async () => {
    offer({ 'POST /cards/ai': { status: 429, body: { detail: { code: 'ai_limit', message: 'Your credit balance is too low.' } } } })
    await openCard('Queue')
    const inside = await openPanel()
    await typeDescription('label it')
    await userEvent.click(inside.getByRole('button', { name: 'Change the card' }))
    expect(await screen.findByTestId('card-ai-error')).toHaveTextContent('Your credit balance is too low.')
    expect(editor().text).toBe(CARD)
  })
})

describe('karten17 ec2: an answer that stays invalid', () => {
  it('shows what came back with its problems and takes over nothing unasked', async () => {
    const bad = { ...ANSWER, ok: false, yaml: 'nexdeck-card: 1\nform: nope\n', problems: [{ code: 'card_bad', message: 'The form is not known.', path: 'form', line: 2, params: {} }] }
    offer({ 'POST /cards/ai': { status: 200, body: bad } })
    await openCard('Queue')
    const inside = await openPanel()
    await typeDescription('label it')
    await userEvent.click(inside.getByRole('button', { name: 'Change the card' }))
    const proposal = within(await screen.findByTestId('card-ai-proposal'))
    expect(proposal.getByText('The answer is not a valid card')).toBeInTheDocument()
    expect(proposal.getByTestId('card-ai-problems')).toHaveTextContent('The form is not known.')
    expect(proposal.getByText(/form: nope/)).toBeInTheDocument()
    expect(editor().text).toBe(CARD)
    expect(sent('POST', '/cards/preview').some((one) => String(one.body?.yaml).includes('form: nope'))).toBe(false)
  })
})

describe('karten17 ec5: an answer nobody took', () => {
  it('asks before the editor is left, as for unsaved changes', async () => {
    offer()
    await openCard('Queue')
    const inside = await openPanel()
    await typeDescription('label it')
    await userEvent.click(inside.getByRole('button', { name: 'Change the card' }))
    await screen.findByTestId('card-ai-proposal')
    await userEvent.click(screen.getByRole('link', { name: 'Back to Custom cards' }))
    expect(await screen.findByText('An answer of the AI is waiting and has not been taken or discarded. It is lost when you leave.')).toBeInTheDocument()
  })

  it('does not ask once the answer is taken or thrown away', async () => {
    offer()
    await openCard('Queue')
    const inside = await openPanel()
    await typeDescription('label it')
    await userEvent.click(inside.getByRole('button', { name: 'Change the card' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Discard' }))
    await userEvent.click(screen.getByRole('link', { name: 'Back to Custom cards' }))
    expect(await screen.findByText('Somewhere else')).toBeInTheDocument()
  })
})
