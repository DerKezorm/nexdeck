/**
 * A theme of one's own with colour pickers: opened from the chooser, every
 * change handed on at once as a whole theme, a colour hard to read named
 * where it is picked, and the page shown in the brightness being edited.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { OWN_PALETTES, THEME_TOKENS, type Theme } from '../../lib/appearance'
import { ThemeChooser } from './ThemeChooser'
import ThemeEditor, { fullTheme } from './ThemeEditor'

const NORD: Theme = { name: 'Nord', dark: { bg: '#242933', accent: '#88c0d0' }, light: { bg: '#e5e9f0' } }

afterEach(() => {
  document.documentElement.dataset.theme = 'dark'
})

describe('the theme editor', () => {
  it('fills a theme to all fifteen colours of both brightnesses, from nexdeck where it is silent', () => {
    const full = fullTheme(NORD, 'Mine')
    expect(full.name).toBe('Nord')
    for (const mode of ['dark', 'light'] as const) expect(Object.keys(full[mode]!).sort()).toEqual([...THEME_TOKENS].sort())
    expect(full.dark!.bg).toBe('#242933')
    expect(full.dark!.text).toBe(OWN_PALETTES.dark.text)
    expect(fullTheme(null, 'Mine').name).toBe('Mine')
  })

  it('opens from the chooser when asked, and not before', async () => {
    render(<ThemeChooser value={NORD} themes={{ nord: NORD }} onChange={() => undefined} />)
    expect(screen.queryByTestId('theme-editor')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Make your own colours' }))
    expect(await screen.findByTestId('theme-editor')).toBeInTheDocument()
  })

  it('hands on the whole theme with every colour picked or typed', () => {
    const changed = vi.fn()
    render(<ThemeEditor value={NORD} onChange={changed} onClose={() => undefined} />)
    fireEvent.change(screen.getByLabelText('Accent'), { target: { value: '#FF8800' } })
    const theme = changed.mock.lastCall![0] as Theme
    expect(theme.dark!.accent).toBe('#ff8800')
    expect(Object.keys(theme.light!)).toHaveLength(15)
    fireEvent.change(screen.getByLabelText('Page as #rrggbb'), { target: { value: '10101' } })
    expect((changed.mock.lastCall![0] as Theme).dark!.bg).toBe('#242933')
    fireEvent.change(screen.getByLabelText('Page as #rrggbb'), { target: { value: '101010' } })
    expect((changed.mock.lastCall![0] as Theme).dark!.bg).toBe('#101010')
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Night watch' } })
    expect((changed.mock.lastCall![0] as Theme).name).toBe('Night watch')
  })

  it('names a colour hard to read where it is picked, by the rule of the server', () => {
    render(<ThemeEditor value={null} onChange={() => undefined} onClose={() => undefined} />)
    expect(screen.queryByTestId('weak-text-faint')).toBeNull()
    expect(screen.getByText('Every text colour is easy to read on its grounds.')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Faint text'), { target: { value: '#333a44' } })
    expect(screen.getByTestId('weak-text-faint')).toHaveTextContent(/1[.,]\d+/)
  })

  it('shows the page in the brightness being edited, and puts it back on closing', async () => {
    document.documentElement.dataset.theme = 'dark'
    const closed = vi.fn()
    const { unmount } = render(<ThemeEditor value={null} onChange={() => undefined} onClose={closed} />)
    await userEvent.click(screen.getByRole('button', { name: 'Light' }))
    expect(document.documentElement.dataset.theme).toBe('light')
    fireEvent.change(screen.getByLabelText('Accent'), { target: { value: '#123456' } })
    await userEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(closed).toHaveBeenCalled()
    unmount()
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe('dark'))
  })
})
