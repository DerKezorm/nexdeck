/**
 * 1984 is chosen with the skins: its tile puts theme, cards and corners
 * together as its look did, its four choices show under it, and saving sends
 * them to the server as the card style window (what 1.0 reads) and the skin.
 * It is no longer one of the card styles.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../styles/retro.css', () => ({}))

const THEME_1984 = { name: '1984', dark: { bg: '#0c0c0c', text: '#f2f2f2' }, light: { bg: '#ffffff', text: '#000000' } }
const OPTIONS = [
  { key: 'status', label: 'How a card says it is unwell', default: 'symbol', choices: [{ key: 'symbol', label: 'A coloured symbol' }, { key: 'tint', label: 'Colour on the window too' }, { key: 'pattern', label: 'The shape alone' }] },
  { key: 'icons', label: 'Logos', default: 'colour', choices: [{ key: 'colour', label: 'In their colours' }, { key: 'mono', label: 'Black and white' }] },
  { key: 'desk', label: 'The desk', default: 'dither', choices: [{ key: 'dither', label: 'Fine dots' }, { key: 'weave', label: 'Woven' }, { key: 'grey', label: 'Plain grey' }] },
  { key: 'type', label: 'Pixel type', default: 'titles', choices: [{ key: 'titles', label: 'Titles and menus' }, { key: 'all', label: 'Everything' }] },
]
const SKIN_1984 = { key: '1984', name: '1984', description: '', author: 'nexdeck', version: '1.0', origin: 'builtin', options: OPTIONS, native: 'retro', wearable: true, swatches: [], updated_at: null }
const sent: { path: string; body: unknown }[] = []
vi.mock('../../api/client', async (original) => ({
  ...(await original<typeof import('../../api/client')>()),
  get: vi.fn(async (path: string) => {
    if (path === '/settings/appearance')
      return { preset: 'cyan', accent: '', css: '', colour: '#22d3ee', presets: { cyan: '#22d3ee' }, theme: null, themes: { '1984': THEME_1984 }, card_style: 'glass', radius: 16, gap: 12, refraction: true, font: 'inter', retro: { status: 'symbol', icons: 'colour', desk: 'dither', type: 'titles' }, skin: {} }
    if (path === '/skins') return { skins: [SKIN_1984], default: {} }
    return { name: '', logo: null, favicon: 'nexdeck', app_icon: 'nexdeck', board_in_title: true, urls: { logo: null } }
  }),
  put: vi.fn(async (path: string, body: Record<string, unknown>) => {
    sent.push({ path, body })
    return { ...body, colour: '#22d3ee', presets: { cyan: '#22d3ee' }, themes: { '1984': THEME_1984 } }
  }),
}))

import { applyAppearance } from '../../lib/appearance'
import { AppearanceSettings } from './AppearanceSettings'

afterEach(() => {
  sent.length = 0
  applyAppearance(null)
})

describe('choosing 1984', () => {
  it('puts the look together from its tile among the skins and saves it with its choices', async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <AppearanceSettings />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const skins = await screen.findByRole('list', { name: 'Skin' })
    expect(within(screen.getByRole('list', { name: 'Cards' })).getAllByRole('button').map((one) => one.textContent)).toEqual(['Glass', 'Liquid glass', 'Flat', 'Outline', 'Neon edge', 'Calm'])
    await userEvent.click(await within(skins).findByRole('button', { name: /1984/ }))
    await userEvent.selectOptions(screen.getByLabelText('How a yellow or red window shows it'), 'pattern')
    await userEvent.selectOptions(screen.getByLabelText('Logos'), 'mono')
    // While it is chosen the page is 1984 already, before anything is saved.
    expect(document.documentElement.dataset.cards).toBe('window')
    expect(document.documentElement.dataset.rStatus).toBe('pattern')
    await userEvent.click(within(skins.parentElement!.parentElement!).getAllByRole('button', { name: 'Save' })[0])
    await waitFor(() => expect(sent.find((one) => one.path === '/settings/appearance')).toBeTruthy())
    const body = sent.find((one) => one.path === '/settings/appearance')!.body as Record<string, unknown>
    expect(body).toMatchObject({ card_style: 'window', radius: 0, gap: 14, theme: THEME_1984, retro: { status: 'pattern', icons: 'mono', desk: 'dither', type: 'titles' } })
    expect(body.skin).toEqual({ key: '1984', options: { status: 'pattern', icons: 'mono', desk: 'dither', type: 'titles' } })
  })
})
