/**
 * The ways into the assistant besides the button: Ctrl K hands a typed
 * question over, the setting under System never shows a stored key, and the
 * ordinary question before a button says what it would hit.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAssistant } from '../../lib/assistant'
import { AssistantSettings } from '../../pages/settings/AssistantSettings'
import { ActionSheet } from '../ActionSheet'
import { CommandPalette } from '../CommandPalette'

const sent: { method: string; path: string; body?: unknown }[] = []
const stored = vi.hoisted(() => ({ value: { provider: 'anthropic', base_url: '', model: 'claude-opus-5-5', has_key: true, ready: true, leaves_the_house: true } as Record<string, unknown> }))

vi.mock('../../api/client', async (original) => ({
  ...(await original<typeof import('../../api/client')>()),
  get: vi.fn(async (path: string) => {
    sent.push({ method: 'GET', path })
    if (path === '/settings/assistant') return stored.value
    if (path === '/assistant') return { ready: true, provider: 'anthropic', model: 'claude-opus-5-5', leaves_the_house: true, keep_days: 30 }
    return { enabled: false, targets: [] }
  }),
  put: vi.fn(async (path: string, body?: unknown) => {
    sent.push({ method: 'PUT', path, body })
    return { ...stored.value, ...(body as object), has_key: true }
  }),
  post: vi.fn(async (path: string, body?: unknown) => {
    sent.push({ method: 'POST', path, body })
    if (path.endsWith('/impact')) return { impact: [{ fact: 'streams', count: 3, names: ['Dune', 'Severance', 'Alien'] }] }
    if (path === '/settings/assistant/test') return { model: 'claude-opus-5-5', answer: 'OK' }
    if (path === '/settings/assistant/models') return [{ id: 'claude-opus-5-5', name: 'Claude Opus 5.5' }, { id: 'claude-sonnet-5-5', name: 'Claude Sonnet 5.5' }]
    return {}
  }),
}))

function wrap(node: React.ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  sent.length = 0
  stored.value = { provider: 'anthropic', base_url: '', model: 'claude-opus-5-5', has_key: true, ready: true, leaves_the_house: true }
  useAssistant.setState({ state: null, open: false, asking: '' })
})

describe('Ctrl K', () => {
  it('hands what was typed to the chat once the assistant is set up', async () => {
    useAssistant.setState({ state: { ready: true, provider: 'anthropic', model: 'claude-opus-5-5', leaves_the_house: true, keep_days: 30 } })
    wrap(<CommandPalette open onClose={vi.fn()} boards={[]} widgets={[]} />)
    await userEvent.type(screen.getByRole('textbox'), 'why is plex slow')
    await userEvent.keyboard('{Enter}')
    expect(useAssistant.getState()).toMatchObject({ open: true, asking: 'why is plex slow' })
  })

  it('offers nothing of the kind while it is off', async () => {
    wrap(<CommandPalette open onClose={vi.fn()} boards={[]} widgets={[]} />)
    await userEvent.type(screen.getByRole('textbox'), 'why is plex slow')
    expect(screen.queryByText('Ask nexdeck')).toBeNull()
  })
})

describe('the question before a button', () => {
  it('says what the button would hit', async () => {
    wrap(<ActionSheet pending={{ widgetId: 4, action: { id: 'restart', label: 'Restart', params: { id: 'c1' }, confirm: true }, values: {} }} onChange={vi.fn()} onCancel={vi.fn()} onRun={vi.fn()} />)
    await waitFor(() => expect(screen.getByTestId('action-impact').textContent).toBe('3 streams end: Dune, Severance, Alien'))
    expect(sent.find((one) => one.path === '/widgets/4/actions/restart/impact')?.body).toEqual({ params: { id: 'c1' } })
  })
})

describe('the setting under System', () => {
  it('keeps a stored key unless a new one is typed, and never shows it', async () => {
    wrap(<AssistantSettings />)
    const key = await screen.findByPlaceholderText(/A key is stored/)
    expect((key as HTMLInputElement).value).toBe('')
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    })
    expect(sent.find((one) => one.method === 'PUT')?.body).toEqual({ provider: 'anthropic', base_url: '', model: 'claude-opus-5-5' })
    fireEvent.change(key, { target: { value: 'sk-ant-new' } })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    })
    expect(sent.filter((one) => one.method === 'PUT').at(-1)?.body).toMatchObject({ key: 'sk-ant-new' })
    expect(screen.getByTestId('assistant-where').textContent).toContain('leave the house')
  })

  it('lists the models of Claude right away when a key is stored, and saves the one picked', async () => {
    stored.value = { provider: 'anthropic', base_url: '', model: 'claude-opus-5-5', has_key: true, ready: true, leaves_the_house: true }
    wrap(<AssistantSettings />)
    const picker = (await screen.findByRole('option', { name: 'Claude Sonnet 5.5 (claude-sonnet-5-5)' })).closest('select') as HTMLSelectElement
    expect(sent.find((one) => one.path === '/settings/assistant/models')?.body).toEqual({ provider: 'anthropic' })
    fireEvent.change(picker, { target: { value: 'claude-sonnet-5-5' } })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    })
    expect(sent.filter((one) => one.method === 'PUT').at(-1)?.body).toMatchObject({ model: 'claude-sonnet-5-5' })
  })

  it('asks a local runner for its models with the address and key typed', async () => {
    stored.value = { provider: 'off', base_url: '', model: '', has_key: false, ready: false, leaves_the_house: false }
    wrap(<AssistantSettings />)
    await waitFor(() => expect(sent.some((one) => one.path === '/settings/assistant')).toBe(true))
    // Let the stored setting arrive before anything is typed over it.
    await act(async () => undefined)
    expect(sent.some((one) => one.path === '/settings/assistant/models')).toBe(false)
    fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'openai' } })
    fireEvent.change(screen.getByPlaceholderText('http://ollama:11434/v1'), { target: { value: 'http://llm.home.arpa/v1' } })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Load models' }))
    })
    expect(sent.find((one) => one.path === '/settings/assistant/models')?.body).toEqual({ provider: 'openai', base_url: 'http://llm.home.arpa/v1' })
    expect(screen.getByRole('option', { name: 'Claude Sonnet 5.5 (claude-sonnet-5-5)' })).toBeTruthy()
  })

  it('tests after saving and says who answered', async () => {
    wrap(<AssistantSettings />)
    await screen.findByPlaceholderText(/A key is stored/)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Save and test' }))
    })
    const order = sent.filter((one) => one.method !== 'GET' && one.path !== '/settings/assistant/models').map((one) => `${one.method} ${one.path}`)
    expect(order).toEqual(['PUT /settings/assistant', 'POST /settings/assistant/test'])
    expect(screen.getByText('claude-opus-5-5 answers.')).toBeTruthy()
  })

  it('asks for an address for a local runner and says whether it stays home once saved', async () => {
    stored.value = { provider: 'openai', base_url: 'http://ollama:11434/v1', model: 'qwen3', has_key: false, ready: true, leaves_the_house: false }
    wrap(<AssistantSettings />)
    await waitFor(() => expect(screen.getByTestId('assistant-where').textContent).toContain('home network'))
    fireEvent.change(screen.getByDisplayValue('http://ollama:11434/v1'), { target: { value: 'https://api.example.com/v1' } })
    expect(screen.getByTestId('assistant-where').textContent).toContain('Once saved')
  })
})
