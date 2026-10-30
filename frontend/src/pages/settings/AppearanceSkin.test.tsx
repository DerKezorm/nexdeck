/**
 * The page of the look says, above each of its settings, what the skin chosen for everybody puts in their place, and
 * says nothing where the skin leaves a setting alone or no skin is chosen.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../styles/retro.css', () => ({}))

const LOOK = { preset: 'cyan', accent: '', css: '', colour: '#22d3ee', presets: { cyan: '#22d3ee' }, theme: null, themes: {}, card_style: 'glass', radius: 16, gap: 12, refraction: true, font: 'inter', skin: { key: 'bricks', options: {} } }
const SKINS = [
  { key: 'bricks', name: 'Bricks', description: '', author: 'someone', version: '1.0', origin: 'own', options: [], native: null, wearable: true, swatches: [], updated_at: null },
  { key: 'plain', name: 'Plain', description: '', author: '', version: '1.0', origin: 'own', options: [], native: null, wearable: true, swatches: [], updated_at: null },
]
const COMPILED: Record<string, unknown> = {
  bricks: { key: 'bricks', css: '', native: null, options: [], tokens: { dark: { bg: '#000000' }, radius: 4 }, fonts: [], sounds: {} },
  plain: { key: 'plain', css: '', native: null, options: [], tokens: {}, fonts: [], sounds: {} },
}

vi.mock('../../api/client', async (original) => ({
  ...(await original<typeof import('../../api/client')>()),
  get: vi.fn(async (path: string) => {
    if (path === '/settings/appearance') return LOOK
    if (path === '/skins') return { skins: SKINS, default: {} }
    const compiled = path.match(/^\/skins\/([^/]+)\/compiled$/)
    if (compiled) return COMPILED[compiled[1]]
    return { name: '', logo: null, favicon: 'nexdeck', app_icon: 'nexdeck', board_in_title: true, urls: { logo: null } }
  }),
}))

import { applyAppearance } from '../../lib/appearance'
import { AppearanceSettings } from './AppearanceSettings'

afterEach(() => applyAppearance(null))

function show() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <AppearanceSettings />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** The card of the page under the heading of that name. */
const card = (title: string) => screen.getByRole('heading', { name: title }).closest('section, div.glass, [class*="card"]') as HTMLElement

describe('what the skin chosen for everybody replaces', () => {
  it('is said above the colour theme, the corners and the accent, and not above the type', async () => {
    show()
    await waitFor(() => expect(screen.getAllByTestId('skin-replaces')).toHaveLength(3))
    const notes = screen.getAllByTestId('skin-replaces').map((note) => note.textContent)
    expect(notes).toEqual([
      'The default skin “Bricks” takes the place of: the colour theme. What is set here stays stored and comes back without the skin.',
      'The default skin “Bricks” takes the place of: the corners. What is set here stays stored and comes back without the skin.',
      'The default skin “Bricks” takes the place of: the accent colour. What is set here stays stored and comes back without the skin.',
    ])
    expect(within(card('Type')).queryByTestId('skin-replaces')).toBeNull()
  })

  it('goes when a skin is chosen that replaces nothing, or none', async () => {
    show()
    await waitFor(() => expect(screen.getAllByTestId('skin-replaces')).toHaveLength(3))
    const skins = screen.getByRole('list', { name: 'Skin' })
    await userEvent.click(within(skins).getByRole('button', { name: /Plain/ }))
    await waitFor(() => expect(screen.queryByTestId('skin-replaces')).toBeNull())
    await userEvent.click(within(skins).getByRole('button', { name: /Bricks/ }))
    await waitFor(() => expect(screen.getAllByTestId('skin-replaces')).toHaveLength(3))
    await userEvent.click(within(skins).getByRole('button', { name: 'nexdeck, no skin' }))
    await waitFor(() => expect(screen.queryByTestId('skin-replaces')).toBeNull())
  })
})

describe('the page wears what is chosen', () => {
  it('paints the skin chosen for everybody while it is open, and asks the app for this account’s look on leaving', async () => {
    const { usePaint } = await import('../../lib/skin/wear')
    const { unmount } = render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <AppearanceSettings />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    await waitFor(() => expect(document.documentElement.dataset.skin).toBe('bricks'))
    // A skin that names no author says where it comes from.
    expect(within(screen.getByRole('list', { name: 'Skin' })).getByRole('button', { name: /Plain/ })).toHaveTextContent('PlainYour own')
    await userEvent.click(within(screen.getByRole('list', { name: 'Skin' })).getByRole('button', { name: /Plain/ }))
    await waitFor(() => expect(document.documentElement.dataset.skin).toBe('plain'))
    const before = usePaint.getState().times
    unmount()
    expect(usePaint.getState().times).toBe(before + 1)
  })
})
