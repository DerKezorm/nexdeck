/**
 * Sign in with Plex: the click opens a window at once, the PIN is polled until
 * plex.tv hands out a token, the token and the account's own server land in
 * the form, and the popup link is offered in case the window was blocked.
 */
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { PlexSignIn } from './PlexSignIn'

const calls: string[] = []
let pollAnswers: { token: string | null; username: string | null }[] = []

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  post: vi.fn(async (path: string, body?: unknown) => {
    calls.push(`POST ${path}`)
    if (path === '/plex/pin') return { id: '7', code: 'QWER', url: 'https://app.plex.tv/auth#?code=QWER' }
    if (path === '/plex/servers') {
      expect(body).toEqual({ token: 'tok-1' })
      return [
        { name: 'Friend', owned: false, machine_id: 'm2', urls: ['https://friend.plex.direct:32400'], access_token: 'shared' },
        { name: 'Home', owned: true, machine_id: 'm1', urls: ['http://192.168.1.10:32400', 'https://home.plex.direct:32400'], access_token: 'tok-1' },
      ]
    }
    throw new Error(`unexpected ${path}`)
  }),
  get: vi.fn(async (path: string) => {
    calls.push(`GET ${path}`)
    return pollAnswers.shift() ?? { token: null, username: null }
  }),
}))

describe('PlexSignIn', () => {
  beforeEach(() => {
    calls.length = 0
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('opens a window on the click, polls the PIN and fills token and server', async () => {
    const popup = { location: { href: '' }, close: vi.fn() }
    const open = vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window)
    pollAnswers = [{ token: null, username: null }, { token: 'tok-1', username: 'plex-user' }]
    const filled: Record<string, unknown>[] = []
    render(<PlexSignIn onFill={(values) => filled.push(values)} />)
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    await user.click(screen.getByRole('button', { name: 'Sign in with Plex' }))
    expect(open).toHaveBeenCalledWith('', '_blank')
    await waitFor(() => expect(popup.location.href).toBe('https://app.plex.tv/auth#?code=QWER'))
    expect(screen.getByRole('status')).toHaveTextContent('Waiting for the sign-in at plex.tv')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100)
    })
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Signed in as plex-user'))
    expect(calls.filter((c) => c.startsWith('GET /plex/pin/7?code=QWER'))).toHaveLength(2)
    expect(filled).toEqual([{ token: 'tok-1' }, { url: 'http://192.168.1.10:32400', token: 'tok-1' }])
    const select = screen.getByLabelText('Server') as HTMLSelectElement
    expect(select.value).toBe('http://192.168.1.10:32400')
    expect(Array.from(select.options).map((o) => o.textContent)).toEqual(['Friend (shared) · https://friend.plex.direct:32400', 'Home · http://192.168.1.10:32400', 'Home · https://home.plex.direct:32400'])
    open.mockRestore()
  })
})
