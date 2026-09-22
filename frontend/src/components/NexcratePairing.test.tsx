/**
 * Pair with nexcrate: the button asks nexdeck's server, the code is shown big,
 * nexdeck asks again until the owner confirmed, and the key lands in the field.
 * A refusal says so and offers to start again.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { NexcratePairing } from './NexcratePairing'

const calls: { path: string; body: unknown }[] = []
let answers: { state: string; key?: string }[] = []

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  post: vi.fn(async (path: string, body?: unknown) => {
    calls.push({ path, body })
    if (path === '/nexcrate/pairing') return { id: 'ours', code: 'K7Q-4ZP', expires_at: new Date(Date.now() + 600_000).toISOString(), poll_seconds: 2 }
    if (path === '/nexcrate/pairing/ours') return answers.shift() ?? { state: 'pending' }
    throw new Error(`unexpected ${path}`)
  }),
}))

describe('NexcratePairing', () => {
  beforeEach(() => {
    calls.length = 0
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows the code, asks until confirmed and hands the key to the form', async () => {
    answers = [{ state: 'pending' }, { state: 'confirmed', key: 'nxc_new' }]
    const keys: string[] = []
    render(<NexcratePairing url=" https://nexcrate.example.com " insecure={false} onKey={(key) => keys.push(key)} />)
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    await user.click(screen.getByRole('button', { name: 'Pair with nexcrate' }))
    expect(await screen.findByText('K7Q-4ZP')).toBeInTheDocument()
    expect(calls[0]).toEqual({ path: '/nexcrate/pairing', body: { url: 'https://nexcrate.example.com', insecure: false } })
    await vi.advanceTimersByTimeAsync(2000)
    expect(keys).toEqual([])
    await vi.advanceTimersByTimeAsync(2000)
    await waitFor(() => expect(keys).toEqual(['nxc_new']))
    expect(screen.getByRole('status')).toHaveTextContent('Paired')
    expect(screen.getByRole('button', { name: 'Pair again' })).toBeInTheDocument()
  })

  it('says when the owner declined', async () => {
    answers = [{ state: 'denied' }]
    render(<NexcratePairing url="https://nexcrate.example.com" insecure onKey={() => {}} />)
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    await user.click(screen.getByRole('button', { name: 'Pair with nexcrate' }))
    await vi.advanceTimersByTimeAsync(2000)
    expect(await screen.findByRole('alert')).toHaveTextContent('Declined in nexcrate')
  })

  it('waits for an address before it can start', () => {
    render(<NexcratePairing url="" insecure={false} onKey={() => {}} />)
    expect(screen.getByRole('button', { name: 'Pair with nexcrate' })).toBeDisabled()
    expect(screen.getByText("Enter nexcrate's address above first.")).toBeInTheDocument()
  })
})
