/**
 * The foot of the bell (Abnahme 6): "Alle Hinweise", "Alle löschen" and "Alle
 * als gelesen markieren" do not fit one row of the drawer, and each label
 * wrapped inside its button, which is one line high, and ran out of it. The row
 * wraps instead, the two buttons that act on the list together.
 */
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useNotices } from '../stores/notices'
import { NoticeDrawer } from './NoticeDrawer'

describe('the foot of the bell', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    useNotices.setState({ open: false, notices: [], unread: 0 })
  })

  it('wraps the row rather than the labels, and keeps the two actions together', () => {
    vi.stubGlobal('fetch', async () => new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } }))
    useNotices.setState({ open: true, notices: [], unread: 0 })
    render(
      <MemoryRouter>
        <NoticeDrawer />
      </MemoryRouter>,
    )
    const footer = screen.getByRole('link', { name: 'All notices' }).closest('footer')!
    expect(footer).toHaveClass('flex-wrap')
    const actions = within(footer).getByTestId('notice-actions')
    expect(actions).toHaveClass('flex-wrap')
    const buttons = [screen.getByRole('link', { name: 'All notices' }), ...within(actions).getAllByRole('button')]
    expect(buttons.map((button) => button.textContent)).toEqual(['All notices', 'Delete all', 'Mark all as read'])
    for (const button of buttons) expect(button).toHaveClass('whitespace-nowrap')
  })
})
