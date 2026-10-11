/**
 * "Delete all" on the notices (issue #36): it asks first, and only then empties the list, unread ones too.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useNotices } from '../stores/notices'
import { DeleteAllNotices } from './NoticeDrawer'

const NOTICES = [
  { id: 1, title: 'Nextcloud is down', level: 'error', read_at: null },
  { id: 2, title: 'Backup written', level: 'info', read_at: '2026-10-11T10:00:00Z' },
]

describe('DeleteAllNotices', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('asks, then deletes every notice, the unread one too', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push(`${(init?.method ?? 'GET').toUpperCase()} ${String(input)}`)
      return new Response(null, { status: 204 })
    })
    useNotices.setState({ notices: NOTICES as never, unread: 1 })
    render(<DeleteAllNotices />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /^(Delete all|Alle löschen)$/ }))
    expect(calls).toEqual([])
    const asked = screen.getByRole('dialog')
    expect(asked).toHaveTextContent('2')
    await user.click(screen.getAllByRole('button', { name: /^(Delete all|Alle löschen)$/ }).at(-1)!)
    await waitFor(() => expect(useNotices.getState().notices).toEqual([]))
    expect(calls).toEqual([expect.stringMatching(/^DELETE .*\/notices\?all=true$/)])
    expect(useNotices.getState().unread).toBe(0)
  })

  it('cannot be pressed with nothing to delete', () => {
    useNotices.setState({ notices: [], unread: 0 })
    render(<DeleteAllNotices />)
    expect(screen.getByRole('button', { name: /^(Delete all|Alle löschen)$/ })).toBeDisabled()
  })
})
