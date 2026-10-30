/**
 * The page of the look says, above each of its settings, what the skin chosen for everybody puts in their place, and
 * says nothing where the skin leaves a setting alone or no skin is chosen.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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
      <AppearanceSettings />
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
      'The skin “Bricks” chosen for everybody takes the place of: the colour theme. What is set here stays stored and comes back without the skin.',
      'The skin “Bricks” chosen for everybody takes the place of: the corners. What is set here stays stored and comes back without the skin.',
      'The skin “Bricks” chosen for everybody takes the place of: the accent colour. What is set here stays stored and comes back without the skin.',
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
    await userEvent.click(within(skins).getByRole('button', { name: 'None' }))
    await waitFor(() => expect(screen.queryByTestId('skin-replaces')).toBeNull())
  })
})
