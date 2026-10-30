/**
 * The skin workshop says of each skin where it comes from and whether everybody or this account wears it, and
 * "Wear for everybody" makes a skin the installation's and has the app put the look on again.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

const SKINS = [
  { key: '1984', name: '1984', description: '', author: 'nexdeck', version: '1.0', origin: 'builtin', options: [], native: 'retro', wearable: true, swatches: [], updated_at: null },
  { key: 'bricks', name: 'Bricks', description: 'Bricks behind the cards.', author: '', version: '1.0', origin: 'own', options: [], native: null, wearable: true, swatches: [], updated_at: null },
  { key: 'pixel', name: 'Pixel', description: '', author: '', version: '1.0', origin: 'shop', options: [], native: null, wearable: true, swatches: [], updated_at: null },
]
let look: Record<string, unknown> = { card_style: 'window', skin: { key: '1984', options: {} } }
const posted: string[] = []

vi.mock('../../api/client', async (original) => ({
  ...(await original<typeof import('../../api/client')>()),
  get: vi.fn(async (path: string) => {
    if (path === '/skins') return { skins: SKINS, default: {} }
    if (path === '/settings/appearance') return look
    if (path === '/workshop/updates') return { enabled: false, catalog_known: false, updates: [], removed: [] }
    if (path === '/workshop/state') return { enabled: false, repo: 'DerKezorm/nexdeck-workshop', token_set: false, risk_acknowledged: false, nexdeck_version: '1.1.1', catalog: null }
    return {}
  }),
  put: vi.fn(async (path: string, body: { key: string }) => {
    posted.push(`${path} ${body.key || '(none)'}`)
    look = { card_style: 'glass', skin: body.key ? { key: body.key, options: {} } : {} }
    return look
  }),
}))

import { usePaint } from '../../lib/skin/wear'
import { useAuth } from '../../stores/auth'
import { SkinsPage } from './SkinsPage'

const row = (name: string) => within(screen.getByTestId('skins-list')).getByText(name, { selector: 'span.font-medium' }).closest('li') as HTMLElement

describe('the skin workshop', () => {
  it('says who wears which skin and where each comes from, and makes one worn by everybody', async () => {
    useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin', skin: { key: 'bricks' } } as never, loading: false })
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <SkinsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(await screen.findByRole('heading', { name: 'Skin workshop' })).toBeInTheDocument()
    await waitFor(() => expect(within(row('1984')).getByTestId('worn-by-all')).toBeInTheDocument())
    expect(within(row('1984')).queryByRole('button', { name: 'Make default' })).toBeNull()
    expect(within(row('Bricks')).getByTestId('worn-by-you')).toBeInTheDocument()
    expect(within(row('Bricks')).getByText('Your own · Bricks behind the cards.')).toBeInTheDocument()
    expect(within(row('Pixel')).getByText('From the Card shop · pixel')).toBeInTheDocument()
    expect(within(row('1984')).getByText('Comes with nexdeck')).toBeInTheDocument()
    const before = usePaint.getState().times
    await userEvent.click(within(row('Pixel')).getByRole('button', { name: 'Make default' }))
    await waitFor(() => expect(posted).toEqual(['/settings/appearance/skin pixel']))
    expect(usePaint.getState().times).toBe(before + 1)
    expect(await screen.findByText('Pixel is the default now.')).toBeInTheDocument()
    await waitFor(() => expect(within(row('Pixel')).getByTestId('worn-by-all')).toBeInTheDocument())
    expect(within(row('1984')).queryByTestId('worn-by-all')).toBeNull()
    // Back to nexdeck as it is, from its own row; and the shop of skins is on this page too.
    await userEvent.click(within(row('nexdeck, no skin')).getByRole('button', { name: 'Make default' }))
    await waitFor(() => expect(posted).toEqual(['/settings/appearance/skin pixel', '/settings/appearance/skin (none)']))
    await waitFor(() => expect(within(row('nexdeck, no skin')).getByTestId('worn-by-all')).toBeInTheDocument())
    expect(screen.getByRole('heading', { name: 'Skins from the Card shop' })).toBeInTheDocument()
    expect(await screen.findByTestId('shop-off')).toBeInTheDocument()
  })

  it('marks no skin as this account’s own when it chose to wear none', async () => {
    useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin', skin: { plain: true } } as never, loading: false })
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <SkinsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    await waitFor(() => expect(within(row('nexdeck, no skin')).getByTestId('worn-by-you')).toBeInTheDocument())
    expect(screen.getAllByTestId('worn-by-you')).toHaveLength(1)
  })
})
