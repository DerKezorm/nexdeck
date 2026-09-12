/**
 * The "what is new" window closes when asked, also when the server does not take the note.
 *
 * ⚠️ Every way out of the window waited for ``PATCH /auth/me``, and only its
 * answer took the window away. With the server gone or the session expired,
 * the X, Escape, the backdrop and the button all did nothing, the refusal went
 * unhandled, and the board behind it stayed out of reach until the page was
 * loaded again. Found on 06.09.2026, still there on 12.09.2026.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { latestVersion } from '../lib/whatsnew'
import { useAuth } from '../stores/auth'
import { WhatsNewDialog } from './WhatsNewDialog'

describe('WhatsNewDialog', () => {
  beforeEach(() => {
    useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin', seen_version: '0.0.1' } as never })
  })

  it('goes away when the server refuses to remember it', async () => {
    const asked: unknown[] = []
    // ⚠️ A plain function, not vi.fn: a spy handles the promise it hands back
    // itself, so a refusal nobody catches stayed invisible to this test. A
    // mutation probe on 12.09.2026 took the catch out and the test stayed green.
    const update = async (fields: unknown) => {
      asked.push(fields)
      throw new Error('The server could not be reached.')
    }
    useAuth.setState({ update } as never)
    render(<WhatsNewDialog />)
    expect(screen.getByRole('dialog')).toBeTruthy()

    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(asked).toEqual([{ seen_version: latestVersion() }])
  })

  it('still tells the server when it can', async () => {
    const update = vi.fn(async () => undefined)
    useAuth.setState({ update } as never)
    render(<WhatsNewDialog />)
    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(update).toHaveBeenCalledTimes(1)
  })
})
