/**
 * 1984 is chosen like any look: one tile among the looks puts theme, cards
 * and corners together, its four choices show while the window style is on,
 * and saving sends them to the server.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../styles/retro.css', () => ({}))

const THEME_1984 = { name: '1984', dark: { bg: '#0c0c0c', text: '#f2f2f2' }, light: { bg: '#ffffff', text: '#000000' } }
const sent: { path: string; body: unknown }[] = []
vi.mock('../../api/client', async (original) => ({
  ...(await original<typeof import('../../api/client')>()),
  get: vi.fn(async (path: string) =>
    path === '/settings/appearance'
      ? { preset: 'cyan', accent: '', css: '', colour: '#22d3ee', presets: { cyan: '#22d3ee' }, theme: null, themes: { '1984': THEME_1984 }, card_style: 'glass', radius: 16, gap: 12, refraction: true, font: 'inter', retro: { status: 'symbol', icons: 'colour', desk: 'dither', type: 'titles' } }
      : { name: '', logo: null, favicon: 'nexdeck', app_icon: 'nexdeck', board_in_title: true, urls: { logo: null } },
  ),
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
  it('puts the look together from one tile and saves it with its choices', async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <AppearanceSettings />
      </QueryClientProvider>,
    )
    const looks = await screen.findByRole('list', { name: 'Looks' })
    expect(screen.queryByTestId('retro-fields')).toBeNull()
    await userEvent.click(within(looks).getByRole('button', { name: /1984/ }))
    const fields = await screen.findByTestId('retro-fields')
    await userEvent.click(within(within(fields).getByRole('group', { name: 'How a yellow or red window shows it' })).getByRole('button', { name: 'Pattern only' }))
    await userEvent.click(within(within(fields).getByRole('group', { name: 'Logos' })).getByRole('button', { name: 'Black and white' }))
    // While it is chosen the page is 1984 already, before anything is saved.
    expect(document.documentElement.dataset.cards).toBe('window')
    expect(document.documentElement.dataset.rStatus).toBe('pattern')
    await userEvent.click(within(looks.parentElement!).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(sent.find((one) => one.path === '/settings/appearance')).toBeTruthy())
    const body = sent.find((one) => one.path === '/settings/appearance')!.body as Record<string, unknown>
    expect(body).toMatchObject({ card_style: 'window', radius: 0, theme: THEME_1984, retro: { status: 'pattern', icons: 'mono', desk: 'dither', type: 'titles' } })
  })
})
