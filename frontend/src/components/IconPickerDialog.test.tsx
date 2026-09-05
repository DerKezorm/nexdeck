/**
 * The overview lists symbols and every logo name, filters as you type, and a
 * click hands the chosen name back and closes. The name index is fetched
 * once; the filtering never waits for the network.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'

import { IconPickerDialog } from './IconPickerDialog'

vi.mock('../api/client', () => ({
  get: vi.fn(async (path: string) => {
    if (path === '/icons/names') {
      return [
        { name: 'nexview', source: 'bundled' },
        { name: 'radarr', source: 'dashboard-icons' },
        { name: 'radarr-4k', source: 'dashboard-icons' },
        { name: 'sonarr', source: 'selfhst' },
      ]
    }
    throw new Error(`unexpected request ${path}`)
  }),
}))

function wrap(children: ReactNode) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>
}

describe('IconPickerDialog', () => {
  it('lists every logo and symbol, filters by name and hands the pick back', async () => {
    const picked: string[] = []
    let closed = 0
    render(wrap(<IconPickerDialog open value="" onPick={(name) => picked.push(name)} onClose={() => (closed += 1)} />))
    const overview = await screen.findByTestId('icon-overview')
    await waitFor(() => expect(overview.querySelectorAll('button')).toHaveLength(4))
    expect(screen.getByRole('button', { name: 'nexview' })).toBeInTheDocument()
    // Symbols come from the curated lucide set.
    expect(screen.getByRole('button', { name: 'rss' })).toBeInTheDocument()

    await userEvent.type(screen.getByPlaceholderText('Filter by name…'), 'rad')
    expect(overview.querySelectorAll('button')).toHaveLength(2)
    expect(screen.queryByRole('button', { name: 'sonarr' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'rss' })).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: 'radarr-4k' }))
    expect(picked).toEqual(['radarr-4k'])
    expect(closed).toBe(1)
  })

  it('says so when nothing matches', async () => {
    render(wrap(<IconPickerDialog open value="" onPick={() => undefined} onClose={() => undefined} />))
    await screen.findByRole('button', { name: 'radarr' })
    await userEvent.type(screen.getByPlaceholderText('Filter by name…'), 'zzqq')
    expect(screen.getByRole('status')).toHaveTextContent('No logo matches "zzqq".')
  })
})
