/**
 * "Ask nexdeck" (roadmap M3): the chat sends the question, shows where the
 * answer looked, draws a proposed button with what it hits, asks twice for a
 * dangerous one and reads a log only after "Allow". The server is replaced;
 * no provider is asked.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { StrictMode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAssistant, type Reply } from '../../lib/assistant'
import { useAuth } from '../../stores/auth'
import { HeaderTools } from '../HeaderTools'
import { AssistantPanel } from './AssistantPanel'

const sent: { method: string; path: string; body?: unknown }[] = []
const replies: Reply[] = []
let actionAnswer: () => Promise<unknown> = async () => ({ message: 'Restarted.' })

vi.mock('../../api/client', async (original) => ({
  ...(await original<typeof import('../../api/client')>()),
  get: vi.fn(async (path: string) => {
    sent.push({ method: 'GET', path })
    if (path === '/assistant') return { ready: true, provider: 'anthropic', model: 'claude-opus-5-5', leaves_the_house: true, keep_days: 30 }
    if (path === '/assistant/conversations') return [{ id: 7, title: 'What happened last night?', updated_at: new Date().toISOString() }]
    if (path === '/assistant/conversations/7')
      return { id: 7, title: 'What happened last night?', updated_at: new Date().toISOString(), turns: [{ me: true, text: 'What happened last night?' }, { me: false, text: 'Paperless went down at 03:12.', refused: false, citations: [], proposals: [], permissions: [] }] }
    return []
  }),
  post: vi.fn(async (path: string, body?: unknown) => {
    sent.push({ method: 'POST', path, body })
    if (path === '/assistant/chat') return { conversation_id: 7, ...(replies.shift() ?? reply('Done.')) }
    if (path.startsWith('/widgets/')) return actionAnswer()
    return {}
  }),
  del: vi.fn(async (path: string) => {
    sent.push({ method: 'DELETE', path })
  }),
}))

function reply(text: string, extra: Partial<Reply> = {}): Reply {
  return { text, refused: false, citations: [], proposals: [], permissions: [], ...extra }
}

const STATE = { ready: true, provider: 'anthropic' as const, model: 'claude-opus-5-5', leaves_the_house: true, keep_days: 30 }

function panel() {
  return render(
    <MemoryRouter>
      <AssistantPanel open />
    </MemoryRouter>,
  )
}

async function ask(text: string) {
  fireEvent.change(screen.getByLabelText('Question'), { target: { value: text } })
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
  })
}

describe('the chat', () => {
  beforeEach(() => {
    sent.length = 0
    replies.length = 0
    actionAnswer = async () => ({ message: 'Restarted.' })
    useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin' } as never })
    useAssistant.setState({ state: STATE, open: true, asking: '' })
  })

  it('sends the question, shows the answer with bold and a list, and its chips', async () => {
    replies.push(reply('Two things:\n- **Paperless** is down\n- Sonarr runs 4.0.16', {
      citations: [{ label: 'Paperless', target: { board: 'lab', page: 'main', widget: 3 } }, { label: 'chronicle', chronicle: true }],
    }))
    panel()
    await ask('What happened last night?')
    expect(sent.find((one) => one.path === '/assistant/chat')?.body).toEqual({ text: 'What happened last night?', conversation_id: null })
    const answer = screen.getByTestId('assistant-answer')
    expect(answer.querySelector('strong')?.textContent).toBe('Paperless')
    expect(answer.querySelectorAll('li')).toHaveLength(2)
    expect(screen.getByRole('button', { name: 'Paperless' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Chronicle' })).toBeTruthy()
  })

  it('leads from a chip to the card on the page and lights it up', async () => {
    const card = document.createElement('div')
    card.dataset.widget = '3'
    card.scrollIntoView = () => undefined
    document.body.appendChild(card)
    replies.push(reply('**Paperless** is down.', { citations: [{ label: 'Paperless', target: { board: 'lab', page: 'main', widget: 3 } }] }))
    panel()
    await ask('Anything?')
    fireEvent.click(screen.getByRole('button', { name: 'Paperless' }))
    expect(card.classList.contains('nd-focus')).toBe(true)
    card.remove()
  })

  it('never draws what the model wrote as markup', async () => {
    replies.push(reply('<img src=x onerror=alert(1)> **ok**'))
    panel()
    await ask('Anything?')
    const answer = screen.getByTestId('assistant-answer')
    expect(answer.querySelector('img')).toBeNull()
    expect(answer.textContent).toContain('<img src=x onerror=alert(1)>')
  })

  it('continues the same conversation with the next question', async () => {
    replies.push(reply('All green.'), reply('Still green.'))
    panel()
    await ask('Anything wrong?')
    await ask('And now?')
    const asked = sent.filter((one) => one.path === '/assistant/chat').map((one) => one.body)
    expect(asked[1]).toEqual({ text: 'And now?', conversation_id: 7 })
  })

  it('says where the questions go', () => {
    panel()
    expect(screen.getByTestId('assistant-privacy').textContent).toContain('go to Anthropic')
    act(() => useAssistant.setState({ state: { ...STATE, provider: 'openai', model: 'qwen3', leaves_the_house: false } }))
    expect(screen.getByTestId('assistant-privacy').textContent).toContain('Stays on the home network')
  })

  it('runs a proposed button only on a press, says what it hits and logs it as from the chat', async () => {
    replies.push(reply('The button restarts **plex**.', {
      proposals: [{ card_id: 4, card: 'Host', row: 'plex', action: 'restart', label: 'Restart', danger: false, params: { id: 'c1' },
        impact: [{ fact: 'streams', count: 2, names: ['Dune · Anna', 'Severance · Ben'] }] }],
    }))
    panel()
    await ask('Restart plex')
    const box = screen.getByTestId('assistant-proposal')
    expect(box.textContent).toContain('2 streams end: Dune · Anna, Severance · Ben')
    expect(sent.some((one) => one.path.startsWith('/widgets/'))).toBe(false)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Restart' }))
    })
    expect(sent.find((one) => one.path === '/widgets/4/actions/restart')?.body).toEqual({ params: { id: 'c1' }, via: 'assistant' })
    expect(screen.getByTestId('assistant-proposal').textContent).toContain('pressed in the chat')
  })

  it('asks a second time before a dangerous button', async () => {
    replies.push(reply('This removes **tdarr**.', {
      proposals: [{ card_id: 4, card: 'Host', row: 'tdarr', action: 'remove', label: 'Remove', danger: true, params: { id: 'c9' }, impact: [] }],
    }))
    panel()
    await ask('Remove tdarr')
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Remove' }))
    })
    expect(sent.some((one) => one.path.startsWith('/widgets/'))).toBe(false)
    expect(screen.getByTestId('assistant-proposal').textContent).toContain('cannot be undone')
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Yes, Remove' }))
    })
    expect(sent.filter((one) => one.path === '/widgets/4/actions/remove')).toHaveLength(1)
  })

  it('shows what the service said when a button fails, and cancelling does nothing', async () => {
    actionAnswer = async () => {
      const { ApiError } = await import('../../api/client')
      throw new ApiError(400, 'action_failed', 'The engine said no.')
    }
    replies.push(reply('Two buttons.', {
      proposals: [
        { card_id: 4, card: 'Host', row: 'plex', action: 'restart', label: 'Restart', danger: false, params: { id: 'c1' }, impact: [] },
        { card_id: 4, card: 'Host', row: 'nginx', action: 'stop', label: 'Stop', danger: false, params: { id: 'c2' }, impact: [] },
      ],
    }))
    panel()
    await ask('Two')
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Restart' }))
    })
    const [first, second] = screen.getAllByTestId('assistant-proposal')
    expect(first.textContent).toContain('The engine said no.')
    fireEvent.click(second.querySelector('button:last-child') as HTMLButtonElement)
    expect(second.textContent).toContain('nothing happened')
    expect(sent.filter((one) => one.path.startsWith('/widgets/'))).toHaveLength(1)
  })

  it('reads a log only after "Allow", then asks on by itself', async () => {
    replies.push(reply('May I read the log of **nginx**?', { permissions: [{ kind: 'log', card_id: 4, container: 'nginx', grant: 'log:2:nginx' }] }), reply('It runs out of memory.'))
    panel()
    await ask('Why does nginx restart?')
    expect(screen.getByTestId('assistant-permission').textContent).toContain('Log lines can hold addresses')
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Allow reading' }))
    })
    expect(sent.find((one) => one.path === '/assistant/conversations/7/allow')?.body).toEqual({ grant: 'log:2:nginx' })
    expect(sent.filter((one) => one.path === '/assistant/chat').at(-1)?.body).toEqual({ text: 'Yes, read the log of nginx.', conversation_id: 7 })
    expect(screen.getByText('It runs out of memory.')).toBeTruthy()
  })

  it('a "No" sends nothing', async () => {
    replies.push(reply('May I?', { permissions: [{ kind: 'log', card_id: 4, container: 'nginx', grant: 'log:2:nginx' }] }))
    panel()
    await ask('Why?')
    fireEvent.click(screen.getByRole('button', { name: 'No' }))
    expect(sent.some((one) => one.path.endsWith('/allow'))).toBe(false)
    expect(sent.filter((one) => one.path === '/assistant/chat')).toHaveLength(1)
  })

  it('names a provider that failed in the reader’s words', async () => {
    const { post } = await import('../../api/client')
    const { ApiError } = await import('../../api/client')
    vi.mocked(post).mockImplementationOnce(async () => {
      throw new ApiError(502, 'auth', 'Anthropic refused the key.')
    })
    panel()
    await ask('Anything?')
    expect(screen.getByRole('alert').textContent).toContain('refused the key. Check it under System')
  })

  it('opens an earlier conversation from the history and deletes one', async () => {
    panel()
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'History' }))
    })
    expect(screen.getByText('Today')).toBeTruthy()
    expect(screen.getByTestId('assistant-history').textContent).toContain('kept for 30 days')
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'What happened last night?' }))
    })
    expect(screen.getByText('Paperless went down at 03:12.')).toBeTruthy()
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'History' }))
    })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Delete What happened last night?' }))
    })
    expect(sent.some((one) => one.method === 'DELETE' && one.path === '/assistant/conversations/7')).toBe(true)
  })

  it('sends a question handed over from Ctrl K once, in a conversation of its own', async () => {
    // ⚠️ Under StrictMode, as in development: the effect runs twice, and the
    // question went out twice until 25.10.2026.
    replies.push(reply('All green.'))
    useAssistant.setState({ asking: 'Is plex fine?' })
    render(
      <StrictMode>
        <MemoryRouter>
          <AssistantPanel open />
        </MemoryRouter>
      </StrictMode>,
    )
    await waitFor(() => expect(sent.find((one) => one.path === '/assistant/chat')?.body).toEqual({ text: 'Is plex fine?', conversation_id: null }))
    await act(async () => undefined)
    expect(sent.filter((one) => one.path === '/assistant/chat')).toHaveLength(1)
    expect(useAssistant.getState().asking).toBe('')
  })

  it('says so when nothing is set up, and leads to the setting', () => {
    useAssistant.setState({ state: { ...STATE, ready: false, provider: 'off' } })
    panel()
    expect(screen.getByText('No provider set up yet')).toBeTruthy()
    expect(screen.queryByLabelText('Question')).toBeNull()
  })
})

describe('the button next to the bell', () => {
  beforeEach(() => {
    sent.length = 0
    useAssistant.setState({ state: null, open: false, asking: '' })
  })

  const tools = () => render(<MemoryRouter><HeaderTools user={{ username: 'admin', display_name: '', role: 'admin', avatar_url: '' }} unread={0} onNotices={() => undefined} /></MemoryRouter>)

  it('is there for an administrator once a provider is set up', async () => {
    useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin' } as never })
    tools()
    const button = await screen.findByTestId('assistant-button')
    fireEvent.click(button)
    expect(useAssistant.getState().open).toBe(true)
  })

  it('is not there for a member, who never even asks', () => {
    useAuth.setState({ user: { id: 2, username: 'kim', role: 'user' } as never })
    // Ready as far as this browser knows: the role alone keeps it away.
    useAssistant.setState({ state: STATE })
    tools()
    expect(screen.queryByTestId('assistant-button')).toBeNull()
    expect(sent.some((one) => one.path === '/assistant')).toBe(false)
  })

  it('is not there while the assistant is off', async () => {
    useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin' } as never })
    useAssistant.setState({ state: { ...STATE, ready: false, provider: 'off' } })
    tools()
    await act(async () => undefined)
    expect(screen.queryByTestId('assistant-button')).toBeNull()
  })
})
