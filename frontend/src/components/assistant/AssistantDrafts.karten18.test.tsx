/**
 * A card the chat drafted (KARTEN-18): one chip "Open in editor" and one small preview per draft, the sentence about
 * what went out and how long the draft stays, and the question before sample values go along. The server is
 * replaced; no provider is asked.
 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAssistant, type DraftRef, type Reply } from '../../lib/assistant'
import { useAuth } from '../../stores/auth'
import { AssistantPanel } from './AssistantPanel'

const sent: { method: string; path: string; body?: unknown }[] = []
const replies: Reply[] = []

const YAML = (name: string) => `nexdeck-card: 1
slug: ${name.toLowerCase().replace(/ /g, '-')}
name: ${name}
version: "1.0.0"
requires: [sonarr]
requests:
  - id: queue
    path: /api/v3/queue
form: value
value: totalRecords
`

vi.mock('../../api/client', async (original) => ({
  ...(await original<typeof import('../../api/client')>()),
  get: vi.fn(async (path: string) => {
    sent.push({ method: 'GET', path })
    if (path === '/assistant/drafts/12') return { id: 12, name: 'Next episodes', yaml: YAML('Next episodes'), conversation_id: 7 }
    if (path === '/assistant/drafts/13') return { id: 13, name: 'Downloads', yaml: YAML('Downloads'), conversation_id: 7 }
    return []
  }),
  post: vi.fn(async (path: string, body?: unknown) => {
    sent.push({ method: 'POST', path, body })
    if (path === '/assistant/chat') return { conversation_id: 7, ...(replies.shift() ?? reply('Done.')) }
    if (path === '/cards/preview') return { status: 'ok', primary: { value: 4, text: '4', format: 'number' }, secondary: [], items: [], meta: { custom: true } }
    return {}
  }),
  del: vi.fn(async () => undefined),
}))

function reply(text: string, extra: Partial<Reply> = {}): Reply {
  return { text, refused: false, citations: [], proposals: [], permissions: [], ...extra }
}

function draft(id: number, name: string, extra: Partial<DraftRef> = {}): DraftRef {
  return {
    id,
    name,
    form: 'value',
    summary: { connection_kind: 'sonarr', path: '/api/v3/queue', form: 'value', buttons: false },
    sent: { values: false },
    keep_days: 30,
    url: `/system/custom-cards/new?draft=${id}`,
    ...extra,
  }
}

const STATE = { ready: true, provider: 'anthropic' as const, model: 'claude-opus-5-5', leaves_the_house: true, keep_days: 30 }

function Where() {
  const here = useLocation()
  return <p data-testid="where">{here.pathname + here.search}</p>
}

function panel() {
  return render(
    <MemoryRouter>
      <AssistantPanel open />
      <Where />
    </MemoryRouter>,
  )
}

async function ask(text: string) {
  fireEvent.change(screen.getByLabelText('Question'), { target: { value: text } })
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
  })
}

beforeEach(() => {
  sent.length = 0
  replies.length = 0
  useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin' } as never })
  useAssistant.setState({ state: STATE, open: true, asking: '' })
})

describe('karten18 ac5: the draft in the chat', () => {
  it('shows a small preview, what went out and how long the draft stays', async () => {
    replies.push(reply('Here is a card.', { drafts: [draft(12, 'Next episodes')] }))
    panel()
    await ask('Build me a card for my queue')
    const box = await screen.findByTestId('assistant-draft')
    expect(within(box).getByText('Next episodes', { selector: 'div' })).toBeInTheDocument()
    await waitFor(() => expect(sent.some((one) => one.path === '/cards/preview' && (one.body as { demo?: boolean }).demo === true)).toBe(true))
    expect(await within(box).findByTestId('draft-preview')).toBeInTheDocument()
    expect(box.textContent).toContain('Only field names and types of the service went to the provider, no values.')
    expect(box.textContent).toContain('30 days at most')
    expect(box.textContent).toContain('sonarr')
  })

  it('says when sample values went along', async () => {
    replies.push(reply('Here is a card.', { drafts: [draft(12, 'Next episodes', { sent: { values: true } })] }))
    panel()
    await ask('Build me a card')
    const box = await screen.findByTestId('assistant-draft')
    expect(box.textContent).toContain('Sample values of the service went along, because you allowed it')
  })
})

describe('karten18 ac3, ec3: Open in editor', () => {
  it('has a chip of its own for every draft, each leading to its own draft', async () => {
    replies.push(reply('Two cards.', { drafts: [draft(12, 'Next episodes'), draft(13, 'Downloads')] }))
    panel()
    await ask('Build me two cards')
    const boxes = await screen.findAllByTestId('assistant-draft')
    expect(boxes).toHaveLength(2)
    const chips = screen.getAllByRole('button', { name: 'Open in editor' })
    expect(chips).toHaveLength(2)
    fireEvent.click(chips[1])
    expect(screen.getByTestId('where').textContent).toBe('/system/custom-cards/new?draft=13')
    fireEvent.click(chips[0])
    expect(screen.getByTestId('where').textContent).toBe('/system/custom-cards/new?draft=12')
  })

  it('shows no draft where there is none', async () => {
    replies.push(reply('Nothing to build.'))
    panel()
    await ask('Hello')
    expect(screen.queryByTestId('assistant-draft')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Open in editor' })).toBeNull()
  })
})

describe('karten18 ac4: sample values only after the administrator allowed them', () => {
  it('asks first, and goes on by itself after "Allow for this draft"', async () => {
    replies.push(
      reply('May I send sample values?', { permissions: [{ kind: 'values', integration_id: 2, integration: 'Sonarr (NAS)', path: '/api/v3/queue', grant: 'values:2:abc' }] }),
      reply('Here is the card.', { drafts: [draft(12, 'Next episodes', { sent: { values: true } })] }),
    )
    panel()
    await ask('Build me a card with real titles')
    const box = screen.getByTestId('assistant-permission')
    expect(box.textContent).toContain('May I send sample values of Sonarr (NAS) (/api/v3/queue) along for this one draft?')
    expect(box.textContent).toContain('They go to the provider')
    expect(sent.some((one) => one.path.endsWith('/allow'))).toBe(false)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Allow for this draft' }))
    })
    expect(sent.find((one) => one.path === '/assistant/conversations/7/allow')?.body).toEqual({ grant: 'values:2:abc' })
    expect(sent.filter((one) => one.path === '/assistant/chat').at(-1)?.body).toEqual({ text: 'Yes, you may send sample values of Sonarr (NAS) for this draft.', conversation_id: 7 })
    expect(await screen.findByTestId('assistant-draft')).toBeInTheDocument()
  })

  it('a "No" sends nothing', async () => {
    replies.push(reply('May I?', { permissions: [{ kind: 'values', integration_id: 2, integration: 'Sonarr', path: '/x', grant: 'values:2:abc' }] }))
    panel()
    await ask('Build')
    fireEvent.click(screen.getByRole('button', { name: 'No' }))
    expect(sent.some((one) => one.path.endsWith('/allow'))).toBe(false)
    expect(screen.getByTestId('assistant-permission').textContent).toContain('No values go along')
  })
})
