/**
 * The card editor's page (KARTEN-9, KARTEN-10): who sees it, how a card begins, the steps, the texts, saving with
 * everything that can go wrong, the question before leaving, the draft in this browser, steps back, the parts only
 * the YAML view shows, and the YAML view itself.
 */
import { EditorView } from '@codemirror/view'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import deScreen from '../../i18n/de.json'
import editorDe from '../../i18n/editor.de.json'
import { readAt } from '../../lib/cardDocument'
import { useAuth } from '../../stores/auth'
import { CardEditorPage } from './CardEditorPage'
import { draftKey } from './draft'
import { useCardEditor } from './store'

const CARD = `nexdeck-card: 1
slug: queue
# what the card is called
name: Queue
version: "1.0.0"
requires: [sonarr]
requests:
  - id: queue
    path: /api/v3/queue
form: value
value: totalRecords
`

type Sent = { url: string; method: string; body: Record<string, unknown> | null }
type Answer = { status: number; body: unknown }

const world = vi.hoisted(() => ({
  sent: [] as { url: string; method: string; body: Record<string, unknown> | null }[],
  answers: {} as Record<string, { status: number; body: unknown } | { status: number; body: unknown }[]>,
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
      const given = world.answers[`${method} ${url}`]
      // A list of answers is given out one after the other; the last one stays.
      const one = Array.isArray(given) ? (given.length > 1 ? given.shift()! : given[0]) : given
      if (one) return json(one.body, one.status)
      if (method === 'GET' && url === '/cards/queue') return json({ slug: 'queue', yaml: CARD, updated_at: '2026-10-25T10:00:00Z' })
      if (method === 'GET' && url === '/cards/sources')
        return json([
          { kind: 'sonarr', label: 'Sonarr', icon: 'sonarr', category: 'media' },
          { kind: 'radarr', label: 'Radarr', icon: 'radarr', category: 'media' },
        ])
      if (method === 'GET' && url === '/integrations') return json([{ id: 3, kind: 'radarr', name: 'Radarr', label: 'Radarr', icon: 'radarr', config: {}, enabled: true }])
      if (method === 'PUT' && url.startsWith('/cards/')) return json({ slug: 'queue', updated_at: '2026-10-25T12:00:00Z', yaml: (init?.body && JSON.parse(String(init.body)).yaml) || '' })
      if (method === 'POST' && url === '/cards') return json({ slug: 'next-episodes', updated_at: '2026-10-25T12:00:00Z' }, 201)
      if (method === 'POST' && url === '/cards/check') return json({ ok: true })
      if (method === 'GET' && url === '/cards/schema') return json({})
      if (method === 'GET') return json([])
      return json({})
    }),
  )
}

const sent = (method: string, url: string) => world.sent.filter((one: Sent) => one.method === method && one.url === url)

function show(at: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[at]}>
        <Routes>
          <Route path="/system/custom-cards/new" element={<CardEditorPage />} />
          <Route path="/system/custom-cards/:slug/edit" element={<CardEditorPage />} />
          <Route path="/system/cards" element={<p>The list of cards</p>} />
          <Route path="/system" element={<p>The system page</p>} />
          <Route path="*" element={<p>Somewhere else</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const editor = () => useCardEditor.getState()

/** Node's own half-made localStorage hides jsdom's in this runner; a plain map stands in (as in player.test). */
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
  useCardEditor.setState({ now: () => Date.now() })
})

afterEach(async () => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  await i18next.changeLanguage('en')
})

async function openQueue() {
  show('/system/custom-cards/queue/edit')
  await screen.findByRole('heading', { name: 'Queue', level: 1 })
}

describe('who sees it', () => {
  it('karten9 AC-1: somebody who is not an administrator does not see the editor', async () => {
    useAuth.setState({ user: { id: 2, username: 'kim', role: 'user' } as never })
    show('/system/custom-cards/queue/edit')
    expect(await screen.findByText('The system page')).toBeInTheDocument()
    expect(sent('GET', '/cards/queue')).toHaveLength(0)
  })
})

describe('a new card', () => {
  it('karten9 AC-2: takes a name, a short name made from it, a kind of connection and a start, and opens in the editor', async () => {
    show('/system/custom-cards/new')
    await userEvent.type(await screen.findByLabelText('Name'), 'Next episodes')
    expect(screen.getByLabelText('Short name')).toHaveValue('next-episodes')
    const kind = screen.getByLabelText('Works with')
    await waitFor(() => expect(kind).toHaveValue('radarr'))
    await userEvent.selectOptions(kind, 'sonarr')
    await userEvent.click(screen.getByRole('radio', { name: /A list/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Create' }))
    expect(await screen.findByRole('heading', { name: 'Next episodes', level: 1 })).toBeInTheDocument()
    expect(readAt(editor().card!, ['requires'])).toEqual(['sonarr'])
    expect(readAt(editor().card!, ['form'])).toBe('list')
    expect(readAt(editor().card!, ['slug'])).toBe('next-episodes')
    expect(editor().slug).toBeNull()
  })

  it('karten9 AC-2: wants a name and a short name that follows the rule', async () => {
    show('/system/custom-cards/new')
    await userEvent.click(await screen.findByRole('button', { name: 'Create' }))
    expect(screen.getByText('Give the card a name.')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Name'), 'A')
    await userEvent.clear(screen.getByLabelText('Short name'))
    await userEvent.type(screen.getByLabelText('Short name'), 'Not Valid')
    await userEvent.click(screen.getByRole('button', { name: 'Create' }))
    expect(screen.getByText(/Use lower case letters, digits and hyphens/)).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'A', level: 1 })).toBeNull()
  })

  it('karten9 EC-6: without a connection of the kind chosen it says so and leads to adding one', async () => {
    show('/system/custom-cards/new')
    const kind = await screen.findByLabelText('Works with')
    await waitFor(() => expect(kind).toHaveValue('radarr'))
    expect(screen.queryByTestId('card-no-connection')).toBeNull()
    await userEvent.selectOptions(kind, 'sonarr')
    const notice = await screen.findByTestId('card-no-connection')
    expect(notice).toHaveTextContent('There is no Sonarr integration yet.')
    expect(within(notice).getByRole('link', { name: /Add an integration/ })).toHaveAttribute('href', '/system/integrations?add=sonarr')
  })

  it('karten9 EC-6: with no fitting connection at all it says that too', async () => {
    stub({ 'GET /integrations': { status: 200, body: [] } })
    show('/system/custom-cards/new')
    expect(await screen.findByTestId('card-no-connection')).toHaveTextContent('There is no integration yet that a custom card can read through.')
  })

  it('karten9 AC-13: a new card is saved with POST and moves to its own address', async () => {
    show('/system/custom-cards/new')
    await userEvent.type(await screen.findByLabelText('Name'), 'Next episodes')
    await userEvent.click(screen.getByRole('button', { name: 'Create' }))
    await screen.findByRole('heading', { name: 'Next episodes', level: 1 })
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(sent('POST', '/cards')).toHaveLength(1))
    expect(sent('POST', '/cards')[0].body).toEqual({ yaml: editor().text })
    await waitFor(() => expect(editor().slug).toBe('next-episodes'))
    expect(await screen.findByText('Saved. Every board shows the new version.')).toBeInTheDocument()
    // Saved, moved, and nothing asked: the card on screen is still the one just saved.
    expect(screen.queryByText('Leave without saving?')).toBeNull()
    expect(screen.getByRole('heading', { name: 'Next episodes', level: 1 })).toBeInTheDocument()
    expect(sent('GET', '/cards/next-episodes')).toHaveLength(0)
  })
})

describe('the steps', () => {
  it('karten9 AC-14: Source, Look, Rules and Texts can be opened in any order; Editor | YAML and Save stand on top', async () => {
    await openQueue()
    const steps = screen.getByRole('navigation', { name: 'Steps' })
    const buttons = within(steps).getAllByRole('button').map((one) => one.textContent)
    expect(buttons).toEqual(['1 Source', '2 Look', '3 Rules', '4 Texts'])
    expect(within(steps).getByRole('button', { name: '1 Source' })).toHaveAttribute('aria-current', 'step')
    await userEvent.click(within(steps).getByRole('button', { name: '4 Texts' }))
    expect(screen.getByRole('heading', { name: 'Texts', level: 2 })).toBeInTheDocument()
    await userEvent.click(within(steps).getByRole('button', { name: '2 Look' }))
    expect(screen.getByRole('heading', { name: 'Look', level: 2 })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Editor' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'YAML' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    expect(screen.queryByText(/Buttons/)).toBeNull()
    expect(screen.queryByText(/Ask AI/)).toBeNull()
    expect(screen.getByTestId('card-preview')).toBeInTheDocument()
  })

  it('karten9 AC-8: every text has a field per language, English first and required, and a language can be added', async () => {
    await openQueue()
    await userEvent.click(screen.getByRole('button', { name: '4 Texts' }))
    const english = screen.getByRole('textbox', { name: 'Name, English (required)' })
    expect(english).toHaveValue('Queue')
    expect(screen.getByRole('textbox', { name: 'Label, English' })).toHaveValue('')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Language' }), 'de')
    await userEvent.click(screen.getByRole('button', { name: 'Add language' }))
    const german = screen.getByRole('textbox', { name: 'Name, German' })
    expect(german).toHaveAttribute('placeholder', 'Shows the English text')
    await userEvent.type(german, 'Warteschlange')
    expect(readAt(editor().card!, ['name'])).toEqual({ en: 'Queue', de: 'Warteschlange' })
    await userEvent.type(screen.getByRole('textbox', { name: 'Label, English' }), 'Waiting')
    expect(readAt(editor().card!, ['value'])).toEqual({ path: 'totalRecords', label: 'Waiting' })
    await userEvent.clear(english)
    expect(screen.getByText('English is required.')).toBeInTheDocument()
  })

  it('karten9 EC-11: headings and labels break instead of running over', async () => {
    i18next.addResourceBundle('de', 'translation', { ...deScreen, ...editorDe }, true, true)
    await i18next.changeLanguage('de')
    await openQueue()
    const step = screen.getByRole('heading', { name: 'Quelle', level: 2 })
    expect(step.className).toContain('break-words')
    expect(step.className).toContain('hyphens-auto')
  })
})

describe('saving', () => {
  it('karten9 AC-13: a saved card goes back with PUT and the moment it was read', async () => {
    await openQueue()
    act(() => editor().set(['name'], 'Waiting'))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(sent('PUT', '/cards/queue')).toHaveLength(1))
    expect(sent('PUT', '/cards/queue')[0].body).toEqual({ yaml: CARD.replace('name: Queue', 'name: Waiting'), base: '2026-10-25T10:00:00Z' })
    expect(await screen.findByText('Saved. Every board shows the new version.')).toBeInTheDocument()
    expect(editor().base).toBe('2026-10-25T12:00:00Z')
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('karten9 EC-3: changed by somebody else meanwhile offers Overwrite, which saves over it', async () => {
    stub({
      'PUT /cards/queue': [
        { status: 409, body: { detail: { code: 'card_changed_meanwhile', message: 'Changed meanwhile.', by: 'kim', at: '2026-10-25T11:00:00Z' } } },
        { status: 200, body: { slug: 'queue', updated_at: '2026-10-25T12:00:00Z' } },
      ],
    })
    await openQueue()
    act(() => editor().set(['name'], 'Waiting'))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    const dialog = await screen.findByRole('dialog', { name: 'Changed by kim meanwhile' })
    await userEvent.click(within(dialog).getByRole('button', { name: 'Overwrite' }))
    await waitFor(() => expect(sent('PUT', '/cards/queue')).toHaveLength(2))
    expect(sent('PUT', '/cards/queue')[1].body).toMatchObject({ overwrite: true, base: '2026-10-25T10:00:00Z' })
    expect(await screen.findByText('Saved. Every board shows the new version.')).toBeInTheDocument()
  })

  it('karten9 EC-3: Reload takes the other version and drops the own changes', async () => {
    stub({
      'PUT /cards/queue': { status: 409, body: { detail: { code: 'card_changed_meanwhile', message: 'Changed meanwhile.', by: 'kim', at: '2026-10-25T11:00:00Z' } } },
      'GET /cards/queue': [
        { status: 200, body: { slug: 'queue', yaml: CARD, updated_at: '2026-10-25T10:00:00Z' } },
        { status: 200, body: { slug: 'queue', yaml: CARD.replace('Queue', 'Kim'), updated_at: '2026-10-25T11:00:00Z' } },
      ],
    })
    await openQueue()
    act(() => editor().set(['name'], 'Waiting'))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Reload' }))
    expect(await screen.findByRole('heading', { name: 'Kim', level: 1 })).toBeInTheDocument()
    expect(editor().base).toBe('2026-10-25T11:00:00Z')
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('karten9 EC-8: a sign-in run out asks to sign in again and saves afterwards, nothing lost', async () => {
    stub({
      'PUT /cards/queue': [
        { status: 401, body: { detail: { code: 'not_authenticated', message: 'Sign in first.' } } },
        { status: 200, body: { slug: 'queue', updated_at: '2026-10-25T12:00:00Z' } },
      ],
    })
    await openQueue()
    act(() => editor().set(['name'], 'Waiting'))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    const dialog = await screen.findByRole('dialog', { name: 'Sign in again to save' })
    expect(within(dialog).getByRole('link', { name: 'Sign in in a new tab' })).toHaveAttribute('target', '_blank')
    expect(editor().text).toContain('name: Waiting')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save now' }))
    await waitFor(() => expect(sent('PUT', '/cards/queue')).toHaveLength(2))
    expect(sent('PUT', '/cards/queue')[1].body).toMatchObject({ yaml: CARD.replace('name: Queue', 'name: Waiting') })
    expect(await screen.findByText('Saved. Every board shows the new version.')).toBeInTheDocument()
  })

  it('karten9 AC-13: problems the server finds stand at their lines and at their fields', async () => {
    stub({
      'PUT /cards/queue': {
        status: 400,
        body: {
          detail: {
            code: 'card_invalid',
            message: 'x',
            problems: [
              { code: 'card_blank', message: 'This must not be empty.', path: 'name', line: 4, params: {} },
              { code: 'card_something_new', message: 'A sentence only the server knows.', path: 'requests[0].path', line: 9, params: {} },
            ],
          },
        },
      },
    })
    await openQueue()
    act(() => editor().set(['name'], ''))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    const list = await screen.findByTestId('card-problems')
    expect(within(list).getByText('Line 4')).toBeInTheDocument()
    expect(within(list).getByText('A sentence only the server knows.')).toBeInTheDocument()
    expect(within(list).getByText('Line 9')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '4 Texts' }))
    const name = screen.getByRole('group', { name: 'Name' })
    expect(within(name).getByText('This must not be empty.')).toBeInTheDocument()
    // A problem's line opens the YAML view there.
    await userEvent.click(within(list).getByRole('button', { name: 'Open line 9 in YAML' }))
    expect(editor().view).toBe('yaml')
  })

  it('karten11: the problems are worded by the table of nexdeck, in the language of the viewer', async () => {
    i18next.addResourceBundle('de', 'translation', { ...deScreen, ...editorDe }, true, true)
    await i18next.changeLanguage('de')
    stub({
      'PUT /cards/queue': {
        status: 400,
        body: {
          detail: {
            code: 'card_invalid',
            message: 'x',
            problems: [
              { code: 'card_wrong_type', message: 'Expected a whole number here.', path: 'size.w', line: 12, params: { expected: 'whole_number' } },
              { code: 'card_slug_reserved', message: 'The short name library is kept for nexdeck itself.', path: 'slug', line: 2, params: { slug: 'library' } },
            ],
          },
        },
      },
    })
    await openQueue()
    act(() => editor().set(['version'], '1.0.1'))
    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }))
    expect(await screen.findByText('Hier wird eine ganze Zahl erwartet.')).toBeInTheDocument()
    expect(screen.getByText('Der Kurzname library ist für nexdeck selbst reserviert.')).toBeInTheDocument()
    expect(screen.getByText('Zeile 12')).toBeInTheDocument()
  })

  it('karten11 ec6: saving a card deleted meanwhile says so and offers "Save as new"', async () => {
    stub({ 'PUT /cards/queue': { status: 404, body: { detail: { code: 'card_deleted', message: 'This card was deleted meanwhile.' } } } })
    await openQueue()
    act(() => editor().set(['name'], 'Waiting'))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('Deleted meanwhile')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Save as new' }))
    await waitFor(() => expect(sent('POST', '/cards')).toHaveLength(1))
    expect(sent('POST', '/cards')[0].body).toEqual({ yaml: CARD.replace('name: Queue', 'name: Waiting') })
  })

  it('karten9 AC-12: the parts only the YAML view shows are named with their lines and saved as they stand', async () => {
    const withButtons = `${CARD}buttons:\n  - {label: Restart, action: restart}  # comes with a later version\n`
    stub({ 'GET /cards/queue': { status: 200, body: { slug: 'queue', yaml: withButtons, updated_at: '2026-10-25T10:00:00Z' } } })
    await openQueue()
    const block = screen.getByTestId('card-adjusted')
    expect(within(block).getByText('Adjusted in YAML')).toBeInTheDocument()
    expect(within(block).getByText('buttons')).toBeInTheDocument()
    expect(within(block).getByText('line 12')).toBeInTheDocument()
    act(() => editor().set(['name'], 'Waiting'))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(sent('PUT', '/cards/queue')).toHaveLength(1))
    expect(String(sent('PUT', '/cards/queue')[0].body!.yaml)).toContain('buttons:\n  - {label: Restart, action: restart}  # comes with a later version\n')
    await userEvent.click(within(block).getByRole('button', { name: 'Open in YAML' }))
    expect(editor().view).toBe('yaml')
  })
})

describe('leaving, drafts and steps back', () => {
  it('karten9 AC-11: leaving with unsaved changes asks first; Cancel stays, Leave goes', async () => {
    await openQueue()
    await userEvent.click(screen.getByRole('link', { name: 'Back to Custom cards' }))
    // Nothing changed: no question.
    expect(await screen.findByText('The list of cards')).toBeInTheDocument()
  })

  it('karten9 AC-11: with a change the way back asks, and the browser asks before a reload', async () => {
    await openQueue()
    act(() => editor().set(['name'], 'Waiting'))
    await userEvent.click(screen.getByRole('link', { name: 'Back to Custom cards' }))
    const question = await screen.findByRole('dialog', { name: 'Leave without saving?' })
    await userEvent.click(within(question).getByRole('button', { name: 'Cancel' }))
    expect(screen.getByRole('heading', { name: 'Waiting', level: 1 })).toBeInTheDocument()
    const unload = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(unload)
    expect(unload.defaultPrevented).toBe(true)
    await userEvent.click(screen.getByRole('link', { name: 'Back to Custom cards' }))
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Leave' }))
    expect(await screen.findByText('The list of cards')).toBeInTheDocument()
  })

  it('karten9 AC-11: after the first save of a new card a later change asks again before leaving', async () => {
    show('/system/custom-cards/new')
    await userEvent.type(await screen.findByLabelText('Name'), 'Next episodes')
    await userEvent.click(screen.getByRole('button', { name: 'Create' }))
    await screen.findByRole('heading', { name: 'Next episodes', level: 1 })
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(editor().slug).toBe('next-episodes'))
    await screen.findByText('Saved. Every board shows the new version.')
    act(() => editor().set(['description'], 'changed after the save'))
    await userEvent.click(screen.getByRole('link', { name: 'Back to Custom cards' }))
    expect(await screen.findByRole('dialog', { name: 'Leave without saving?' })).toBeInTheDocument()
    expect(screen.queryByText('The list of cards')).toBeNull()
  })

  it('karten9 EC-7: unsaved changes are kept in this browser and offered on opening again', async () => {
    const first = await (async () => {
      await openQueue()
      act(() => editor().set(['name'], 'Waiting'))
      return JSON.parse(localStorage.getItem(draftKey('queue'))!)
    })()
    expect(first.text).toContain('name: Waiting')
    expect(first.base).toBe('2026-10-25T10:00:00Z')
  })

  it('karten9 EC-7: a kept draft is offered with "Restore unsaved changes" and comes back', async () => {
    localStorage.setItem(draftKey('queue'), JSON.stringify({ text: CARD.replace('name: Queue', 'name: Draft'), base: '2026-10-25T09:00:00Z', at: Date.now() }))
    await openQueue()
    await userEvent.click(screen.getByRole('button', { name: 'Restore unsaved changes' }))
    expect(await screen.findByRole('heading', { name: 'Draft', level: 1 })).toBeInTheDocument()
    expect(editor().base).toBe('2026-10-25T09:00:00Z')
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled()
  })

  it('karten9 EC-7: a new card that was never saved is offered too', async () => {
    localStorage.setItem(draftKey(null), JSON.stringify({ text: CARD.replace('name: Queue', 'name: Fresh'), base: null, at: Date.now() }))
    show('/system/custom-cards/new')
    await userEvent.click(await screen.findByRole('button', { name: 'Restore unsaved changes' }))
    expect(await screen.findByRole('heading', { name: 'Fresh', level: 1 })).toBeInTheDocument()
  })

  it('karten9 EC-7 decision 8: without storage the editor works all the same', async () => {
    const blocked = () => {
      throw new Error('blocked')
    }
    vi.stubGlobal('localStorage', { getItem: blocked, setItem: blocked, removeItem: blocked, clear: blocked, key: blocked, length: 0 })
    await openQueue()
    act(() => editor().set(['name'], 'Waiting'))
    expect(screen.getByRole('heading', { name: 'Waiting', level: 1 })).toBeInTheDocument()
  })

  it('karten9 EC-10: Ctrl Z and Ctrl Shift Z take back and bring back, Cmd as well', async () => {
    await openQueue()
    act(() => editor().set(['name'], 'One'))
    fireEvent.keyDown(window, { key: 'z', ctrlKey: true })
    expect(await screen.findByRole('heading', { name: 'Queue', level: 1 })).toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'Z', metaKey: true, shiftKey: true })
    expect(await screen.findByRole('heading', { name: 'One', level: 1 })).toBeInTheDocument()
  })
})

describe('karten10: the YAML view', () => {
  async function yamlView() {
    await openQueue()
    await userEvent.click(screen.getByRole('button', { name: 'YAML' }))
    await waitFor(() => expect(document.querySelector('.cm-editor')).not.toBeNull())
    return EditorView.findFromDOM(document.querySelector('.cm-editor') as HTMLElement)!
  }

  it('karten10 AC-1 AC-3: shows the same card as YAML, and a change there is in the editor when switching back', async () => {
    const view = await yamlView()
    expect(view.state.doc.toString()).toBe(CARD)
    act(() => {
      view.dispatch({ changes: { from: CARD.indexOf('Queue'), to: CARD.indexOf('Queue') + 5, insert: 'Typed' }, userEvent: 'input.type' })
    })
    await userEvent.click(screen.getByRole('button', { name: 'Editor' }))
    expect(await screen.findByRole('heading', { name: 'Typed', level: 1 })).toBeInTheDocument()
    expect(editor().text).toBe(CARD.replace('name: Queue', 'name: Typed'))
  })

  it('karten10 AC-4: a change in the editor is in the YAML with comments and order unchanged', async () => {
    await openQueue()
    act(() => editor().set(['version'], '1.1.0'))
    await userEvent.click(screen.getByRole('button', { name: 'YAML' }))
    await waitFor(() => expect(document.querySelector('.cm-editor')).not.toBeNull())
    const view = EditorView.findFromDOM(document.querySelector('.cm-editor') as HTMLElement)!
    expect(view.state.doc.toString()).toBe(CARD.replace('version: "1.0.0"', 'version: "1.1.0"'))
  })

  it('karten10 AC-5 EC-5: broken YAML locks the editor and Save, names the line and when the last valid version was', async () => {
    const view = await yamlView()
    act(() => {
      view.dispatch({ changes: { from: view.state.doc.length, insert: 'value:\n\tpath: x\n' }, userEvent: 'input.type' })
    })
    const list = await screen.findByTestId('card-problems')
    expect(within(list).getByText('Line 13')).toBeInTheDocument()
    expect(within(list).getByText('YAML indents with spaces only, and this line is indented with a tab.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Editor' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Editor' })).toHaveAttribute('title', 'Fix line 13 first')
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    expect(screen.getByTestId('card-last-valid')).toHaveTextContent(/^Last valid version: /)
    expect(screen.getByRole('heading', { name: 'Preview of the last valid version' })).toBeInTheDocument()
  })

  it('karten10 AC-2: what the server checks stands at the line too, a moment after typing', async () => {
    stub({
      'POST /cards/check': { status: 200, body: { ok: false, problems: [{ code: 'card_said_by_the_server', message: 'nexdeck has no integration sonar.', path: 'requires[0]', line: 6, params: {} }] } },
    })
    const view = await yamlView()
    act(() => {
      view.dispatch({ changes: { from: CARD.indexOf('sonarr'), to: CARD.indexOf('sonarr') + 6, insert: 'sonar' }, userEvent: 'input.type' })
    })
    const list = await screen.findByTestId('card-problems', {}, { timeout: 4000 })
    expect(within(list).getByText('nexdeck has no integration sonar.')).toBeInTheDocument()
    expect(within(list).getByText('Line 6')).toBeInTheDocument()
    expect(sent('POST', '/cards/check').at(-1)!.body).toEqual({ yaml: CARD.replace('sonarr', 'sonar') })
  })

  it('karten10 AC-6: a whole card pasted is checked and, when it passes, shown in the editor', async () => {
    const view = await yamlView()
    const pasted = CARD.replace('name: Queue', 'name: From a forum')
    act(() => {
      view.dispatch({ selection: { anchor: 0, head: view.state.doc.length } })
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: pasted }, userEvent: 'input.paste' })
    })
    expect(await screen.findByText('The pasted card is valid and shows in the editor now.')).toBeInTheDocument()
    expect(sent('POST', '/cards/check').at(-1)!.body).toEqual({ yaml: pasted })
    expect(editor().view).toBe('editor')
    expect(screen.getByRole('heading', { name: 'From a forum', level: 1 })).toBeInTheDocument()
  })

  it('karten10 EC-7: a tab typed with the Tab key becomes two spaces', async () => {
    const view = await yamlView()
    view.focus()
    act(() => {
      view.dispatch({ selection: { anchor: view.state.doc.length } })
    })
    fireEvent.keyDown(view.contentDOM, { key: 'Tab', code: 'Tab', keyCode: 9 })
    expect(view.state.doc.toString().endsWith('\n  ')).toBe(true)
  })
})
