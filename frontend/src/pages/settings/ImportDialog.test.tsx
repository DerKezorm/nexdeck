/**
 * Import of cards and integrations from a file or pasted text (KARTEN-12 AC-2 to AC-4, EC-1, EC-2, EC-7): the check
 * names every document, the preview draws the card with its example data, the conflict is decided by the person, and
 * nothing is sent to make anything before that.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ImportDialog } from './ImportDialog'

const CARD = `nexdeck-card: 1
slug: queue
name: Queue
requires: [custom:memos]
form: value
value: {path: total, label: Waiting}
demo:
  main: {total: 3}
`
const INTEGRATION = `nexdeck: integration
short: memos
name: Memos
`
const FILE = `${CARD}---\n${INTEGRATION}`

const DOCUMENT = (extra: Record<string, unknown> = {}) => ({
  type: 'card',
  id: 'card:queue',
  slug: 'queue',
  name: 'Queue',
  requires: ['custom:memos'],
  buttons: [{ label: 'Pause', method: 'POST', path: '/api/pause' }],
  form: 'value',
  problems: [],
  exists: false,
  same: false,
  ...extra,
})
const INTEGRATION_DOCUMENT = (extra: Record<string, unknown> = {}) => ({ type: 'integration', id: 'integration:memos', short: 'memos', name: 'Memos', requires: [], buttons: [], form: null, problems: [], exists: false, same: false, ...extra })

const SHOWN = { status: 'ok', primary: { value: 3, text: '3', format: 'number', label: 'Waiting' }, secondary: [], items: [], meta: { custom: true } }

type Sent = { url: string; method: string; body: Record<string, unknown> | null }
const world = vi.hoisted(() => ({ sent: [] as { url: string; method: string; body: Record<string, unknown> | null }[], answers: {} as Record<string, { status: number; body: unknown }> }))

function stub(answers: Record<string, { status: number; body: unknown }>) {
  world.sent = []
  world.answers = { 'POST /cards/preview': { status: 200, body: SHOWN }, 'POST /cards/import': { status: 200, body: {} }, ...answers }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input).replace(/^.*\/api\/v1/, '')
      const method = init?.method ?? 'GET'
      world.sent.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null })
      if (method === 'GET' && url === '/cards/sources') return new Response(JSON.stringify([{ kind: 'custom:memos', label: 'Memos', icon: 'memos' }]), { status: 200, headers: { 'content-type': 'application/json' } })
      const given = world.answers[`${method} ${url}`]
      return new Response(JSON.stringify(given?.body ?? {}), { status: given?.status ?? 200, headers: { 'content-type': 'application/json' } })
    }),
  )
}

const sent = (method: string, url: string) => world.sent.filter((one: Sent) => one.method === method && one.url === url)

function show() {
  const onClose = vi.fn()
  const onDone = vi.fn()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <ImportDialog open onClose={onClose} onDone={onDone} />
    </QueryClientProvider>,
  )
  return { onClose, onDone }
}

/** Pastes the text and presses Check. */
async function check(text = FILE) {
  const field = screen.getByRole('textbox', { name: 'Or paste the text' })
  await userEvent.click(field)
  await userEvent.paste(text)
  await userEvent.click(screen.getByRole('button', { name: 'Check' }))
}

afterEach(() => vi.unstubAllGlobals())

describe('looking at a file before anything is made', () => {
  beforeEach(() => stub({ 'POST /cards/import/check': { status: 200, body: { documents: [DOCUMENT(), INTEGRATION_DOCUMENT()], missing_integrations: [] } } }))

  it('karten12 ac2: shows name, source with its name, buttons and the card with its example data', async () => {
    show()
    await check()
    expect(sent('POST', '/cards/import/check')[0].body).toEqual({ text: FILE })
    const card = await screen.findByTestId('import-doc-card:queue')
    expect(within(card).getByText('Queue')).toBeInTheDocument()
    expect(within(card).getByText('Memos')).toBeInTheDocument()
    expect(within(card).getByText('Pause')).toBeInTheDocument()
    expect(within(card).getByText('POST /api/pause')).toBeInTheDocument()
    // The renderer of the cards is a chunk of its own, loaded when the first card is drawn: on a busy machine that takes longer than a second.
    const drawn = await within(card).findByRole('region', { name: 'Queue' }, { timeout: 15_000 })
    expect(drawn).toHaveTextContent('Waiting')
    // The example data of the card, not a connection: and only the text of the card's own document goes.
    expect(sent('POST', '/cards/preview')[0].body).toEqual({ yaml: CARD, demo: true })
    expect(sent('POST', '/cards/import')).toHaveLength(0)
  })

  it('karten12 ac4: an integration that is in the file comes along, and the card says so', async () => {
    show()
    await check()
    const card = await screen.findByTestId('import-doc-card:queue')
    expect(within(card).getByText('(comes along in this file)')).toBeInTheDocument()
    expect(screen.getByTestId('import-doc-integration:memos')).toBeInTheDocument()
    expect(screen.queryByTestId('import-missing')).toBeNull()
  })

  it('karten12 ec7: a picked file goes the same way as pasted text', async () => {
    show()
    const file = new File([FILE], 'queue.nexdeck.yaml', { type: 'text/yaml' })
    await userEvent.upload(screen.getByLabelText('Choose a file'), file)
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Or paste the text' })).toHaveValue(FILE))
    await userEvent.click(screen.getByRole('button', { name: 'Check' }))
    await screen.findByTestId('import-doc-card:queue')
    expect(sent('POST', '/cards/import/check')[0].body).toEqual({ text: FILE })
  })

  it('karten12 ac2: a new file imports with no choices', async () => {
    const { onDone, onClose } = show()
    await check()
    await screen.findByTestId('import-doc-card:queue')
    await userEvent.click(screen.getByRole('button', { name: 'Import' }))
    await waitFor(() => expect(sent('POST', '/cards/import')).toHaveLength(1))
    expect(sent('POST', '/cards/import')[0].body).toEqual({ text: FILE, choices: {} })
    await waitFor(() => expect(onDone).toHaveBeenCalled())
    expect(onClose).toHaveBeenCalled()
  })
})

describe('a short name that is taken', () => {
  beforeEach(() => stub({ 'POST /cards/import/check': { status: 200, body: { documents: [DOCUMENT({ exists: true }), INTEGRATION_DOCUMENT()], missing_integrations: [] } } }))

  it('karten12 ac3: offers Replace, Import as copy and Cancel, and does not import before one is chosen', async () => {
    show()
    await check()
    const conflict = await screen.findByTestId('import-conflict-card:queue')
    expect(within(conflict).getByRole('radio', { name: 'Replace' })).not.toBeChecked()
    expect(within(conflict).getByRole('radio', { name: 'Import as copy' })).toBeInTheDocument()
    expect(within(conflict).getByRole('radio', { name: 'Cancel' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Import' })).toBeDisabled()
    expect(screen.getByText('Choose what happens to each item that exists already.')).toBeInTheDocument()
    expect(sent('POST', '/cards/import')).toHaveLength(0)
  })

  it('karten12 ac3: the choice goes with the import, keyed by type and short name', async () => {
    show()
    await check()
    await userEvent.click(within(await screen.findByTestId('import-conflict-card:queue')).getByRole('radio', { name: 'Import as copy' }))
    await userEvent.click(screen.getByRole('button', { name: 'Import' }))
    await waitFor(() => expect(sent('POST', '/cards/import')).toHaveLength(1))
    expect(sent('POST', '/cards/import')[0].body).toEqual({ text: FILE, choices: { 'card:queue': 'copy' } })
  })

  it('karten12 ac3: Replace is sent as replace', async () => {
    show()
    await check()
    await userEvent.click(within(await screen.findByTestId('import-conflict-card:queue')).getByRole('radio', { name: 'Replace' }))
    await userEvent.click(screen.getByRole('button', { name: 'Import' }))
    await waitFor(() => expect(sent('POST', '/cards/import')[0]?.body).toEqual({ text: FILE, choices: { 'card:queue': 'replace' } }))
  })

  it('karten12 ac3: the choice can be made with the keyboard alone', async () => {
    show()
    await check()
    const conflict = await screen.findByTestId('import-conflict-card:queue')
    within(conflict).getByRole('radio', { name: 'Replace' }).focus()
    await userEvent.keyboard('[Space]')
    expect(within(conflict).getByRole('radio', { name: 'Replace' })).toBeChecked()
    await userEvent.keyboard('[ArrowRight]')
    expect(within(conflict).getByRole('radio', { name: 'Import as copy' })).toBeChecked()
    expect(screen.getByRole('button', { name: 'Import' })).toBeEnabled()
  })

  it('karten12 ac3: Cancel stops the whole import: nothing is sent and the button stays closed', async () => {
    show()
    await check()
    await userEvent.click(within(await screen.findByTestId('import-conflict-card:queue')).getByRole('radio', { name: 'Cancel' }))
    expect(screen.getByRole('button', { name: 'Import' })).toBeDisabled()
    expect(screen.getByText('You chose Cancel, so nothing will be imported.')).toBeInTheDocument()
    expect(sent('POST', '/cards/import')).toHaveLength(0)
  })

  it('karten12 ac3: when the server still wants a choice, it says so in a sentence', async () => {
    stub({
      'POST /cards/import/check': { status: 200, body: { documents: [DOCUMENT({ exists: true })], missing_integrations: [] } },
      'POST /cards/import': { status: 400, body: { detail: { code: 'import_choice_missing', message: 'A choice is missing for card:queue.' } } },
    })
    show()
    await check()
    await userEvent.click(within(await screen.findByTestId('import-conflict-card:queue')).getByRole('radio', { name: 'Replace' }))
    await userEvent.click(screen.getByRole('button', { name: 'Import' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose Replace, Import as copy or Cancel for every item that exists already.')
  })
})

describe('an integration that is not there', () => {
  it('karten12 ac4: names the kinds that are neither in the file nor here', async () => {
    stub({ 'POST /cards/import/check': { status: 200, body: { documents: [DOCUMENT()], missing_integrations: ['custom:memos', 'custom:wiki'] } } })
    show()
    await check(CARD)
    expect(await screen.findByTestId('import-missing')).toHaveTextContent('Missing: memos, wiki.')
    // The card is not held back: it may be imported and works once the integration exists.
    expect(screen.getByRole('button', { name: 'Import' })).toBeEnabled()
  })
})

describe('a file that is not right', () => {
  it('karten12 ec1: shows each problem with its line in the file and does not allow the import', async () => {
    stub({ 'POST /cards/import/check': { status: 200, body: { documents: [DOCUMENT({ problems: [{ code: 'field_required', line: 14, path: 'value.path', message: 'value.path is required.', params: {} }] })], missing_integrations: [] } } })
    show()
    await check(CARD)
    const problems = await screen.findByTestId('import-problems')
    expect(problems).toHaveTextContent('Line 14: value.path is required.')
    expect(screen.getByRole('button', { name: 'Import' })).toBeDisabled()
    expect(screen.getByText('Fix the problems in the file first.')).toBeInTheDocument()
    // A card with a problem has no preview to ask for.
    expect(sent('POST', '/cards/preview')).toHaveLength(0)
  })

  it('karten12 ec1: a file over 512 KB is not read and not sent', async () => {
    stub({})
    show()
    const big = new File([new Uint8Array(512 * 1024 + 1)], 'big.nexdeck.yaml')
    await userEvent.upload(screen.getByLabelText('Choose a file'), big)
    expect(await screen.findByRole('alert')).toHaveTextContent('This file is larger than 512 KB.')
    expect(screen.getByRole('textbox', { name: 'Or paste the text' })).toHaveValue('')
    expect(world.sent.filter((one: Sent) => one.method === 'POST')).toHaveLength(0)
  })

  it('karten12 ec1: a document that is neither a card nor an integration shows its problem and holds the import back', async () => {
    stub({ 'POST /cards/import/check': { status: 200, body: { ok: false, documents: [{ type: 'unknown', id: 'unknown:null', name: null, requires: [], buttons: [], form: '', problems: [{ code: 'import_unknown_document', line: 3, path: '', message: 'This is neither a card nor an own connection.', params: {} }], exists: false, same: false, line: 3 }], missing_integrations: [] } } })
    show()
    await check('slug: x')
    expect(await screen.findByTestId('import-problems')).toHaveTextContent('Line 3: This is neither a card (nexdeck-card: 1) nor an integration (nexdeck: integration).')
    expect(screen.getByRole('button', { name: 'Import' })).toBeDisabled()
  })

  it('karten12 ec1: a refusal of the check is shown as the sentence the server gave', async () => {
    stub({ 'POST /cards/import/check': { status: 400, body: { detail: { code: 'import_too_large', message: 'The file is larger than 512 KB.' } } } })
    show()
    await check('x')
    expect(await screen.findByRole('alert')).toHaveTextContent('The file is larger than 512 KB.')
  })

  it('karten12 ec2: a file for a newer version of nexdeck is refused with the words of the server', async () => {
    stub({ 'POST /cards/import/check': { status: 400, body: { detail: { code: 'card_newer_format', message: 'This card needs a newer version of nexdeck (format 2).' } } } })
    show()
    await check('nexdeck-card: 2\n')
    expect(await screen.findByRole('alert')).toHaveTextContent('This card needs a newer version of nexdeck (format 2).')
    expect(screen.queryByRole('button', { name: 'Import' })).toBeNull()
  })

  it('karten12 ec7: a text that is changed after the check must be checked again', async () => {
    stub({ 'POST /cards/import/check': { status: 200, body: { documents: [DOCUMENT()], missing_integrations: [] } } })
    show()
    await check(CARD)
    await screen.findByTestId('import-doc-card:queue')
    await userEvent.type(screen.getByRole('textbox', { name: 'Or paste the text' }), ' ')
    expect(screen.queryByTestId('import-doc-card:queue')).toBeNull()
    expect(screen.getByRole('button', { name: 'Check' })).toBeEnabled()
  })
})
