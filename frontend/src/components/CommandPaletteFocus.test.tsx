/**
 * The command bar keeps the keyboard inside for as long as it is open.
 *
 * ⚠️ It says ``aria-modal="true"``, which promises exactly that, and it only
 * put the focus on its field. Tab and Shift+Tab walked out of it into the board
 * behind, where a screen reader went on reading a page the person could not
 * see. Sheet and Dialog got a focus trap on 07.09.2026; the bar has markup of
 * its own and was left out. Found on 12.09.2026.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { CommandPalette } from './CommandPalette'

vi.mock('../api/client', () => ({
  get: vi.fn(async () => ({ enabled: false, targets: [] })),
  mediaUrl: () => '',
}))

describe('CommandPalette focus', () => {
  it('does not let Tab or Shift+Tab leave it', async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <button type="button">Behind the bar</button>
          <CommandPalette open onClose={vi.fn()} boards={[]} widgets={[]} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const bar = screen.getByRole('dialog')
    await waitFor(() => expect(bar.contains(document.activeElement)).toBe(true))

    await userEvent.tab({ shift: true })
    expect(bar.contains(document.activeElement)).toBe(true)
    for (let press = 0; press < 10; press++) await userEvent.tab()
    expect(bar.contains(document.activeElement)).toBe(true)
  })
})
