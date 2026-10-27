/**
 * The integration editor's page (KARTEN-3): who sees it, how a new one begins, the form for fields, the four kinds
 * of sign-in and the test address, saving with everything that can go wrong, the draft in this browser, and the
 * YAML view.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import deScreen from '../../i18n/de.json'
import editorDe from '../../i18n/editor.de.json'
import { useAuth } from '../../stores/auth'
import { readAt, setAt } from '../../lib/cardDocument'
import { draftKey } from './draft'
import { IntegrationEditorPage } from './IntegrationEditorPage'
import { useIntegrationEditor } from './store'

const TEMPLATE = `nexdeck: integration
short: example
name: Example
description: Notes you keep for yourself.
fields:
  - name: token
    type: secret
    label: Access token
    required: true
auth:
  type: header
  header: Authorization
  value: "Bearer {token}"
test: /api/status
`

type Answer = { status: number; body: unknown }

const world = vi.hoisted(() => ({
  sent: [] as { url: string; method: string; body: Record<string, unknown> | null }[],
  answers: {} as Record<string, unknown>,
}))

function stub(answers: Record<string, Answer | Answer[]> = {}) {
  world.sent = []
  world.answers = answers
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input).replace(/^.*\/api\/v1/, '')
      const method = init?.method ?? 'GET'
      world.sent.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null })
      const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } })
      const given = (answers as Record<string, Answer | Answer[]>)[`${method} ${url}`]
      // A list of answers is given out one after the other; the last one stays.
      const one = Array.isArray(given) ? (given.length > 1 ? given.shift()! : given[0]) : given
      if (one) return json(one.body, one.status)
      if (method === 'GET' && url === '/own-integrations/template') return json({ yaml: TEMPLATE })
      if (method === 'GET' && url === '/own-integrations/example') return json({ short: 'example', kind: 'custom:example', name: 'Example', yaml: TEMPLATE, updated_at: '2026-10-26T10:00:00Z', connections: 0 })
      if (method === 'GET' && url === '/own-integrations/nothing') return json({ detail: { code: 'integration_not_found', message: 'No such integration.' } }, 404)
      if (method === 'POST' && url === '/own-integrations/check') return json({ ok: true })
      if (method === 'POST' && url === '/own-integrations') return json({ short: 'example', kind: 'custom:example', name: 'Example', yaml: '', updated_at: '2026-10-26T12:00:00Z' }, 201)
      if (method === 'PUT' && url === '/own-integrations/example') return json({ short: 'example', kind: 'custom:example', name: 'Example', yaml: '', updated_at: '2026-10-26T12:00:00Z' })
      if (method === 'GET') return json([])
      return json({})
    }),
  )
}

const sent = (method: string, url: string) => world.sent.filter((one) => one.method === method && one.url === url)

function show(at: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[at]}>
        <Routes>
          <Route path="/system/custom-cards/integrations/new" element={<IntegrationEditorPage />} />
          <Route path="/system/custom-cards/integrations/:short/edit" element={<IntegrationEditorPage />} />
          <Route path="/system/cards" element={<p>The list of cards</p>} />
          <Route path="/system" element={<p>The system page</p>} />
          <Route path="*" element={<p>Somewhere else</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const editor = () => useIntegrationEditor.getState()

/** The text of the definition as data, to say what a field wrote. */
const at = (path: (string | number)[]) => readAt(editor().card!, path)

function memoryStorage(): Storage {
  const items = new Map<string, string>()
  return {
    get length() {
      return items.size
    },
    clear: () => items.clear(),
    getItem: (key) => items.get(key) ?? null,
    key: (index) => [...items.keys()][index] ?? null,
    removeItem: (key) => void items.delete(key),
    setItem: (key, value) => void items.set(key, String(value)),
  }
}

beforeAll(() => {
  // jsdom measures nothing; the code editor asks for rectangles all the same.
  const rect = { x: 0, y: 0, top: 0, left: 0, bottom: 0, right: 0, width: 0, height: 0, toJSON: () => ({}) }
  Range.prototype.getClientRects = () => ({ length: 0, item: () => null, [Symbol.iterator]: [][Symbol.iterator] }) as unknown as DOMRectList
  Range.prototype.getBoundingClientRect = () => rect as DOMRect
})

beforeEach(() => {
  stub()
  vi.stubGlobal('localStorage', memoryStorage())
  useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin' } as never, loading: false })
})

afterEach(async () => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  await i18next.changeLanguage('en')
})

async function openNew() {
  show('/system/custom-cards/integrations/new')
  await screen.findByTestId('integration-form')
}

async function openExample() {
  show('/system/custom-cards/integrations/example/edit')
  await screen.findByTestId('integration-form')
}

const section = (name: string) => within(screen.getByTestId(`integration-section-${name}`))

describe('who sees the editor and how it begins', () => {
  it('karten3 ac1: a user who is no administrator is sent back to System', async () => {
    useAuth.setState({ user: { id: 2, username: 'kim', role: 'user' } as never, loading: false })
    show('/system/custom-cards/integrations/new')
    expect(await screen.findByText('The system page')).toBeInTheDocument()
    expect(sent('GET', '/own-integrations/template')).toHaveLength(0)
  })

  it('karten3 ac1: a new integration begins with the example the server hands out, in the form', async () => {
    await openNew()
    expect(sent('GET', '/own-integrations/template')).toHaveLength(1)
    expect(screen.getByLabelText('Name')).toHaveValue('Example')
    expect(screen.getByLabelText('Short name')).toHaveValue('example')
    expect(screen.getByLabelText('Short name')).not.toBeDisabled()
    for (const name of ['basics', 'fields', 'auth', 'test', 'reads']) expect(screen.getByTestId(`integration-section-${name}`)).toBeInTheDocument()
    // The new integration is not dirty yet and saves as it is.
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled()
  })

  it('karten3 ac1: a saved one opens with its text; its short name cannot change', async () => {
    await openExample()
    expect(sent('GET', '/own-integrations/example')).toHaveLength(1)
    expect(screen.getByLabelText('Short name')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('an integration that is not there says so', async () => {
    show('/system/custom-cards/integrations/nothing/edit')
    expect(await screen.findByText('There is no integration called nothing.')).toBeInTheDocument()
  })

  it('karten3 ac1: the name of a new one makes its short name until somebody writes their own', async () => {
    await openNew()
    await userEvent.clear(screen.getByLabelText('Name'))
    await userEvent.type(screen.getByLabelText('Name'), 'Wiki Äpfel')
    expect(at(['short'])).toBe('wiki-apfel')
    await userEvent.clear(screen.getByLabelText('Short name'))
    await userEvent.type(screen.getByLabelText('Short name'), 'mine')
    await userEvent.type(screen.getByLabelText('Name'), 's')
    expect(at(['short'])).toBe('mine')
  })
})

describe('the fields to set up', () => {
  it('karten3 ac2: the address is always there and cannot be removed', async () => {
    await openNew()
    const address = screen.getByTestId('integration-address-field')
    expect(within(address).getByText('url')).toBeInTheDocument()
    expect(within(address).queryByRole('button')).toBeNull()
  })

  it('karten3 ac2: a field is added with a name, a type, a label and a help text, and the text follows', async () => {
    await openNew()
    await userEvent.click(screen.getByRole('button', { name: 'Add a field' }))
    const rows = screen.getAllByTestId('integration-field')
    expect(rows).toHaveLength(2)
    const second = within(rows[1])
    await userEvent.clear(second.getByLabelText('Name in the definition'))
    await userEvent.type(second.getByLabelText('Name in the definition'), 'user')
    await userEvent.selectOptions(second.getByRole('combobox'), 'switch')
    await userEvent.type(second.getByLabelText('Help text'), 'Who signs in.')
    await userEvent.click(second.getByRole('checkbox', { name: 'Required' }))
    expect(at(['fields', 1])).toMatchObject({ name: 'user', type: 'switch', help: 'Who signs in.', required: true })
  })

  it('karten3 ac2: all four types are offered', async () => {
    await openNew()
    const options = within(within(screen.getAllByTestId('integration-field')[0]).getByRole('combobox')).getAllByRole('option')
    expect(options.map((one) => one.textContent)).toEqual(['Text', 'Secret', 'Number', 'Switch'])
  })

  it('karten3 ac2: a field moves down and goes away, and the last one removes the whole list', async () => {
    await openNew()
    await userEvent.click(screen.getByRole('button', { name: 'Add a field' }))
    await userEvent.click(within(screen.getAllByTestId('integration-field')[0]).getByRole('button', { name: 'Move down' }))
    expect((at(['fields']) as { name: string }[]).map((one) => one.name)).toEqual(['field', 'token'])
    await userEvent.click(within(screen.getAllByTestId('integration-field')[0]).getByRole('button', { name: 'Remove field' }))
    await userEvent.click(within(screen.getAllByTestId('integration-field')[0]).getByRole('button', { name: 'Remove field' }))
    expect(at(['fields'])).toBeUndefined()
  })

  it('karten3: no more than 12 fields can be added', async () => {
    await openNew()
    for (let n = 0; n < 11; n++) await userEvent.click(screen.getByRole('button', { name: 'Add a field' }))
    expect(screen.getAllByTestId('integration-field')).toHaveLength(12)
    expect(screen.getByRole('button', { name: 'Add a field' })).toBeDisabled()
    expect(screen.getByText('At most 12 fields.')).toBeInTheDocument()
  })

  it('karten3 ac2: the form for whoever sets it up shows the address, the fields and the TLS switch', async () => {
    await openNew()
    const preview = within(screen.getByTestId('integration-preview'))
    expect(preview.getByText('Address')).toBeInTheDocument()
    expect(preview.getByText('Access token')).toBeInTheDocument()
    expect(preview.getByText('Ignore TLS errors')).toBeInTheDocument()
  })
})

describe('the sign-in', () => {
  it('karten3 ac3: key in a header names the header and the value, with the fields to choose from', async () => {
    await openNew()
    expect(screen.getByTestId('integration-auth-explained')).toHaveTextContent('Every request carries a header with the key')
    await userEvent.clear(screen.getByLabelText('Header name'))
    await userEvent.type(screen.getByLabelText('Header name'), 'X-Api-Key')
    expect(at(['auth', 'header'])).toBe('X-Api-Key')
    const value = screen.getAllByLabelText('Header value')[0]
    await userEvent.clear(value)
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Insert a field into Header value' }), 'token')
    expect(at(['auth', 'value'])).toBe('{token}')
    expect(value).toHaveValue('{token}')
  })

  it('karten3 ac3: a field that does not exist is said at once', async () => {
    await openNew()
    const value = screen.getAllByLabelText('Header value')[0]
    await userEvent.clear(value)
    // A brace typed with userEvent is written twice.
    await userEvent.type(value, 'Bearer {{tokn}')
    expect(await screen.findByText('There is no field called {tokn}.')).toBeInTheDocument()
  })

  it('karten3 ac4: user and password go as two placeholders', async () => {
    await openNew()
    await userEvent.selectOptions(screen.getByLabelText('Kind of sign-in'), 'basic')
    expect(at(['auth'])).toMatchObject({ type: 'basic', user: '{token}', password: '{token}' })
    expect(screen.getByTestId('integration-auth-explained')).toHaveTextContent('plain basic sign-in')
    expect(screen.getAllByLabelText('User').length).toBeGreaterThan(0)
    expect(screen.getAllByLabelText('Password').length).toBeGreaterThan(0)
  })

  it('karten3 ac5: key in the address names the parameter', async () => {
    await openNew()
    await userEvent.selectOptions(screen.getByLabelText('Kind of sign-in'), 'query')
    expect(screen.getByTestId('integration-auth-explained')).toHaveTextContent('appears in no log')
    await userEvent.clear(screen.getByLabelText('Parameter name'))
    await userEvent.type(screen.getByLabelText('Parameter name'), 'openapi')
    expect(at(['auth'])).toMatchObject({ type: 'query', param: 'openapi', value: '{token}' })
    expect(editor().text).not.toContain('Bearer')
  })

  it('karten3 ac6: login with a session asks for the login address, the fields sent, the ticket and how it goes along', async () => {
    await openNew()
    await userEvent.selectOptions(screen.getByLabelText('Kind of sign-in'), 'session')
    const auth = section('auth')
    expect(auth.getByLabelText('Login address')).toHaveValue('/api/login')
    await userEvent.clear(auth.getByLabelText('Login address'))
    await userEvent.type(auth.getByLabelText('Login address'), '/api/v1/auth/signin')
    await userEvent.selectOptions(auth.getByLabelText('Send as'), 'form')
    // The ticket is in a field of the JSON, or in a cookie.
    expect(auth.getByLabelText('Field of the answer')).toBeInTheDocument()
    await userEvent.selectOptions(auth.getByLabelText('The ticket is in'), 'cookie')
    await userEvent.type(auth.getByLabelText('Cookie name'), 'memos.access-token')
    await userEvent.selectOptions(auth.getByLabelText('Send the ticket as'), 'query')
    await userEvent.clear(auth.getByLabelText('Parameter name'))
    await userEvent.type(auth.getByLabelText('Parameter name'), 'token')
    expect(at(['auth'])).toMatchObject({
      type: 'session',
      login: '/api/v1/auth/signin',
      send: 'form',
      ticket: { from: 'cookie', name: 'memos.access-token' },
      pass: { as: 'query', param: 'token' },
    })
  })

  it('karten3 ac6: the fields sent are rows that are added and removed; {ticket} is offered only after the login', async () => {
    await openNew()
    await userEvent.selectOptions(screen.getByLabelText('Kind of sign-in'), 'session')
    expect(at(['auth', 'body'])).toEqual({ username: '{token}', password: '{token}' })
    await userEvent.click(screen.getByRole('button', { name: 'Add a field to send' }))
    expect(Object.keys(at(['auth', 'body']) as object)).toHaveLength(3)
    await userEvent.click(screen.getAllByRole('button', { name: 'Remove this field' })[0])
    expect(Object.keys(at(['auth', 'body']) as object)).toEqual(['password', 'field'])
    const inLogin = within(screen.getByRole('group', { name: 'Fields sent' })).getAllByRole('combobox', { name: /Insert a field/ })[0]
    expect(within(inLogin).queryByRole('option', { name: '{ticket}' })).toBeNull()
    const inPass = screen.getByRole('combobox', { name: 'Insert a field into Value sent' })
    expect(within(inPass).getByRole('option', { name: '{ticket}' })).toBeInTheDocument()
  })

  it('karten3 ac6: a body with names inside names is not shown as rows and survives a change in the form and a round trip through the YAML', async () => {
    await openNew()
    await userEvent.selectOptions(screen.getByLabelText('Kind of sign-in'), 'session')
    const nested = { passwordCredentials: { username: '{token}', password: '{token}' } }
    act(() => editor().change((doc) => setAt(doc, ['auth', 'body'], nested)))
    expect(screen.getByText(/names inside names/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add a field to send' })).toBeNull()
    await userEvent.type(screen.getByLabelText('Description'), '!')
    expect(at(['auth', 'body'])).toEqual(nested)
    await userEvent.click(screen.getByRole('button', { name: 'Edit in the YAML' }))
    expect(await screen.findByTestId('integration-yaml')).toBeInTheDocument()
    expect(editor().text).toContain('passwordCredentials')
    await userEvent.click(screen.getByRole('button', { name: 'Form' }))
    expect(at(['auth', 'body'])).toEqual(nested)
  })

  it('karten3 ac1: each kind is explained in a sentence of its own', async () => {
    await openNew()
    const seen = new Set<string>()
    for (const type of ['none', 'header', 'basic', 'query', 'session']) {
      await userEvent.selectOptions(screen.getByLabelText('Kind of sign-in'), type)
      seen.add(screen.getByTestId('integration-auth-explained').textContent ?? '')
    }
    expect(seen.size).toBe(5)
  })
})

describe('the test address and what nexdeck can ask', () => {
  it('karten3 ac9: the test address and what counts as good', async () => {
    await openNew()
    const test = section('test')
    await userEvent.clear(test.getByLabelText('Path'))
    await userEvent.type(test.getByLabelText('Path'), '/api/v1/auth/status')
    await userEvent.selectOptions(test.getByLabelText('Counts as good'), 'json')
    expect(at(['test'])).toBe('/api/v1/auth/status')
    expect(at(['test_expects'])).toBe('json')
    await userEvent.selectOptions(test.getByLabelText('Counts as good'), 'any')
    expect(at(['test_expects'])).toBeUndefined()
  })

  it('karten3: addresses nexdeck may ask are added with a name and removed again', async () => {
    await openNew()
    await userEvent.click(screen.getByRole('button', { name: 'Add an address' }))
    const row = within(screen.getByTestId('integration-read'))
    await userEvent.clear(row.getByLabelText('Path'))
    await userEvent.type(row.getByLabelText('Path'), '/api/v1/memos?pageSize=10')
    await userEvent.type(row.getByLabelText('Name'), 'Latest notes')
    expect(at(['reads'])).toEqual([{ path: '/api/v1/memos?pageSize=10', label: 'Latest notes' }])
    await userEvent.click(row.getByRole('button', { name: 'Remove this entry' }))
    expect(at(['reads'])).toBeUndefined()
  })
})

describe('the extras', () => {
  it('karten4 ac1: the check address is written under check and leaves with an empty field', async () => {
    await openNew()
    const extras = section('extras')
    await userEvent.type(extras.getByLabelText('Check address'), '/healthz')
    expect(at(['check'])).toBe('/healthz')
    await userEvent.clear(extras.getByLabelText('Check address'))
    expect(at(['check'])).toBeUndefined()
  })

  it('karten4 ac2: the version is a path and a place in the answer, written together and removed together', async () => {
    await openNew()
    const extras = section('extras')
    await userEvent.type(extras.getByLabelText('Version: path'), '/api/v1/status')
    await userEvent.type(extras.getByLabelText('Version: place in the answer'), 'release.version')
    expect(at(['version'])).toEqual({ path: '/api/v1/status', at: 'release.version' })
    await userEvent.clear(extras.getByLabelText('Version: path'))
    await userEvent.clear(extras.getByLabelText('Version: place in the answer'))
    expect(at(['version'])).toBeUndefined()
  })

  it('karten4 ac3: the project on GitHub is written as typed, and the server says when it is none', async () => {
    await openNew()
    await userEvent.type(section('extras').getByLabelText('Project on GitHub'), 'usememos/memos')
    expect(at(['github'])).toBe('usememos/memos')
  })

  it('karten4 ec3: a project the server refuses is said at its field', async () => {
    stub({
      'POST /own-integrations/check': {
        status: 200,
        body: { ok: false, problems: [{ line: 14, path: 'github', message: 'Write the project as owner/name or as https://github.com/owner/name.', code: 'card_integration_github' }] },
      },
    })
    await openNew()
    await userEvent.type(section('extras').getByLabelText('Project on GitHub'), 'https://gitlab.com/a/b')
    expect(await within(screen.getByTestId('integration-section-extras')).findByRole('alert')).toBeTruthy()
  })
})

describe('saving', () => {
  it('karten3 ac1: a new integration is saved with POST and the page moves to its own address', async () => {
    await openNew()
    await userEvent.type(screen.getByLabelText('Description'), '!')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(sent('POST', '/own-integrations')).toHaveLength(1))
    expect(sent('POST', '/own-integrations')[0].body?.yaml).toContain('description: Notes you keep for yourself.!')
    await waitFor(() => expect(editor().short).toBe('example'))
    expect(await screen.findByText('Saved. Every connection of it follows at once.')).toBeInTheDocument()
    // On its own address now: the short name is fixed.
    await waitFor(() => expect(screen.getByLabelText('Short name')).toBeDisabled())
  })

  it('karten3 ac11: a saved one goes back with PUT and the moment it was read', async () => {
    await openExample()
    await userEvent.type(screen.getByLabelText('Description'), '!')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(sent('PUT', '/own-integrations/example')).toHaveLength(1))
    expect(sent('PUT', '/own-integrations/example')[0].body).toMatchObject({ base: '2026-10-26T10:00:00Z' })
    expect(sent('PUT', '/own-integrations/example')[0].body).not.toHaveProperty('overwrite')
  })

  it('karten3 ac1: problems the server finds stand at their field and at their line', async () => {
    stub({
      'POST /own-integrations/check': {
        status: 200,
        body: { ok: false, problems: [{ code: 'x', message: 'This name is a built-in kind.', path: 'short', line: 2, params: {} }] },
      },
    })
    await openNew()
    await userEvent.type(screen.getByLabelText('Description'), '!')
    const problem = await within(screen.getByTestId('integration-section-basics')).findByText(/This name is a built-in kind\./)
    expect(problem).toBeInTheDocument()
    expect(within(screen.getByTestId('integration-section-fields')).queryByTestId('integration-section-problems')).toBeNull()
  })

  it('karten3 ac1: a save the server refuses with problems shows them and saves nothing', async () => {
    stub({
      'POST /own-integrations': {
        status: 400,
        body: { detail: { code: 'integration_invalid', message: 'Not valid.', problems: [{ code: 'x', message: 'The sign-in names {tokn}, which is no field.', path: 'auth.value', line: 11, params: {} }] } },
      },
    })
    await openNew()
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await within(screen.getByTestId('integration-section-auth')).findByText(/names \{tokn\}/)).toBeInTheDocument()
    expect(editor().short).toBeNull()
  })

  it('karten3 ac12: the 51st says why it is refused', async () => {
    stub({ 'POST /own-integrations': { status: 400, body: { detail: { code: 'integration_limit', message: 'Too many.' } } } })
    await openNew()
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('There are 50 integrations of your own already, which is the most nexdeck keeps. Delete one first.')).toBeInTheDocument()
  })

  it('karten3: a short name that exists says so', async () => {
    stub({ 'POST /own-integrations': { status: 409, body: { detail: { code: 'integration_exists', message: 'Exists.' } } } })
    await openNew()
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('An integration with this short name exists already.')).toBeInTheDocument()
  })

  it('karten3 ac11: changed by somebody else meanwhile offers Overwrite, which saves over it', async () => {
    stub({
      'PUT /own-integrations/example': [
        { status: 409, body: { detail: { code: 'integration_changed_meanwhile', message: 'Changed meanwhile.', by: 'kim', at: '2026-10-26T11:00:00Z' } } },
        { status: 200, body: { short: 'example', updated_at: '2026-10-26T12:00:00Z' } },
      ],
    })
    await openExample()
    await userEvent.type(screen.getByLabelText('Description'), '!')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    const dialog = await screen.findByRole('dialog', { name: 'Changed by kim meanwhile' })
    await userEvent.click(within(dialog).getByRole('button', { name: 'Overwrite' }))
    await waitFor(() => expect(sent('PUT', '/own-integrations/example')).toHaveLength(2))
    expect(sent('PUT', '/own-integrations/example')[1].body).toMatchObject({ overwrite: true, base: '2026-10-26T10:00:00Z' })
  })

  it('karten3: a sign-in that ran out is told apart, and nothing typed is lost', async () => {
    stub({ 'PUT /own-integrations/example': { status: 401, body: { detail: { code: 'not_signed_in', message: 'Sign in.' } } } })
    await openExample()
    await userEvent.type(screen.getByLabelText('Description'), '!')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('dialog', { name: 'Sign in again to save' })).toBeInTheDocument()
    expect(editor().text).toContain('keep for yourself.!')
  })
})

describe('the draft and the YAML view', () => {
  it('a change is kept in this browser and offered again after a reload', async () => {
    await openExample()
    await userEvent.type(screen.getByLabelText('Description'), '!')
    expect(localStorage.getItem(draftKey('example'))).toContain('keep for yourself.!')
    // Opened again: the kept text is offered, not put in silently.
    act(() => useIntegrationEditor.setState({ short: null }))
    show('/system/custom-cards/integrations/example/edit')
    expect((await screen.findAllByText('Unsaved changes in this browser')).length).toBeGreaterThan(0)
  })

  it('a draft that is the saved text is no draft', async () => {
    localStorage.setItem(draftKey('example'), JSON.stringify({ text: TEMPLATE, base: null, at: 1 }))
    await openExample()
    expect(screen.queryByText('Unsaved changes in this browser')).toBeNull()
    expect(localStorage.getItem(draftKey('example'))).toBeNull()
  })

  it('the YAML view shows the text, and text that is no YAML closes the form until it is fixed', async () => {
    await openNew()
    await userEvent.click(screen.getByRole('button', { name: 'YAML' }))
    expect(await screen.findByTestId('integration-yaml')).toBeInTheDocument()
    act(() => editor().setText('name: [unclosed'))
    expect(screen.getByRole('button', { name: 'Form' })).toBeDisabled()
    expect(await screen.findByTestId('integration-problems')).toBeInTheDocument()
    act(() => editor().setText(TEMPLATE))
    expect(screen.getByRole('button', { name: 'Form' })).toBeEnabled()
  })

  it('a comment in the text survives a change made in the form', async () => {
    await openNew()
    act(() => editor().setText(TEMPLATE.replace('name: Example', '# what it is called\nname: Example')))
    await userEvent.type(screen.getByLabelText('Description'), '!')
    expect(editor().text).toContain('# what it is called')
  })

  it('the words come in German too', async () => {
    i18next.addResourceBundle('de', 'translation', { ...deScreen, ...editorDe }, true, true)
    await i18next.changeLanguage('de')
    show('/system/custom-cards/integrations/new')
    expect(await screen.findByRole('heading', { name: 'Anmeldung' })).toBeInTheDocument()
    expect(screen.getByText('immer dabei')).toBeInTheDocument()
  })
})
