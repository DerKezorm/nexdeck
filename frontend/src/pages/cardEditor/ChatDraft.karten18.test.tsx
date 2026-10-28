/**
 * The draft of the chat opens in the editor (KARTEN-18 AC-3): `?draft=<id>` loads it as a new card, nothing is saved
 * before the administrator saves it there, and a draft that is gone says so. The server is replaced.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { editor, prepare, sent, stub } from '../../test/cardEditor'
import { CardEditorPage } from './CardEditorPage'
import { NEW_CARD } from './templates'

const DRAFT = `nexdeck-card: 1
slug: next-episodes
name: Next episodes
version: "1.0.0"
requires: [sonarr]
requests:
  - id: queue
    path: /api/v3/queue
form: value
value: totalRecords
`

function show(at = '/system/custom-cards/new?draft=12') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[at]}>
        <Routes>
          <Route path="/system/custom-cards/new" element={<CardEditorPage />} />
          <Route path="/system/cards" element={<p>The list of cards</p>} />
          <Route path="*" element={<p>Somewhere else</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  prepare()
})

afterEach(async () => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  await i18next.changeLanguage('en')
})

describe('karten18 ac3: open in editor', () => {
  it('opens a new card with the text of the draft, and saves nothing', async () => {
    stub(DRAFT, { 'GET /assistant/drafts/12': { status: 200, body: { id: 12, name: 'Next episodes', yaml: DRAFT, conversation_id: 3 } } })
    show()
    await waitFor(() => expect(editor().text).toBe(DRAFT))
    expect(sent('GET', '/assistant/drafts/12')).toHaveLength(1)
    expect(editor().slug).toBeNull()
    expect(editor().savedText).toBeNull()
    expect(sent('POST', '/cards')).toHaveLength(0)
    expect(sent('PUT', '/cards/next-episodes')).toHaveLength(0)
    expect(await screen.findByRole('heading', { name: 'Next episodes', level: 1 })).toBeInTheDocument()
  })

  it('asks before it is left, since the draft is not saved', async () => {
    stub(DRAFT, { 'GET /assistant/drafts/12': { status: 200, body: { id: 12, name: 'Next episodes', yaml: DRAFT, conversation_id: 3 } } })
    show()
    await screen.findByRole('heading', { name: 'Next episodes', level: 1 })
    await userEvent.click(screen.getByRole('link', { name: 'Back to Custom cards' }))
    expect(await screen.findByText('Leave without saving?')).toBeInTheDocument()
  })

  it('says so when the draft is gone, and begins with a new card', async () => {
    stub(DRAFT, { 'GET /assistant/drafts/99': { status: 404, body: { detail: { code: 'not_found', message: 'No such draft.' } } } })
    show('/system/custom-cards/new?draft=99')
    expect(await screen.findByTestId('card-chat-draft-trouble')).toHaveTextContent('This draft of the chat is gone')
    expect(editor().text).toBe(NEW_CARD)
  })

  it('a new card without a draft asks the chat for nothing', async () => {
    stub(DRAFT)
    show('/system/custom-cards/new')
    await waitFor(() => expect(editor().text).toBe(NEW_CARD))
    expect(sent('GET', '/assistant/drafts/12')).toHaveLength(0)
    expect(screen.queryByTestId('card-chat-draft-trouble')).toBeNull()
  })
})
