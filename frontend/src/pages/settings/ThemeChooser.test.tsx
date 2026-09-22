/** Choosing, pasting and warning about a colour theme. */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { Theme } from '../../lib/appearance'
import { ThemeChooser } from './ThemeChooser'

const SHIPPED: Record<string, Theme> = {
  ember: { name: 'Ember', dark: { bg: '#141110', accent: '#fb923c' }, light: { bg: '#faf5f1', accent: '#c2410c' } },
}

describe('the theme chooser', () => {
  it('offers nexdecks own look and every shipped theme, and says which is chosen', async () => {
    const chosen = vi.fn()
    render(<ThemeChooser value={SHIPPED.ember} themes={SHIPPED} onChange={chosen} />)
    expect(screen.getByRole('button', { name: /Ember/ }).getAttribute('aria-pressed')).toBe('true')
    await userEvent.click(screen.getByRole('button', { name: /nexdeck/ }))
    expect(chosen).toHaveBeenLastCalledWith(null)
  })

  it('takes a pasted theme and says in words what is wrong with a broken one', async () => {
    const chosen = vi.fn()
    render(<ThemeChooser value={null} themes={SHIPPED} onChange={chosen} />)
    await userEvent.click(screen.getByText('Paste a theme or take this one along'))
    const field = screen.getByLabelText('Theme as JSON')
    await userEvent.click(field)
    await userEvent.paste('not json')
    await userEvent.click(screen.getByRole('button', { name: 'Use this theme' }))
    expect(screen.getByRole('alert').textContent).toBe('This is not JSON.')
    expect(chosen).not.toHaveBeenCalled()
    await userEvent.clear(field)
    await userEvent.paste('{"name": "Mine", "dark": {"bg": "#000000"}}')
    await userEvent.click(screen.getByRole('button', { name: 'Use this theme' }))
    expect(chosen).toHaveBeenLastCalledWith({ name: 'Mine', dark: { bg: '#000000' }, light: undefined })
  })

  it('names what is hard to read before anything is saved', () => {
    const faint: Theme = { name: 'Faint', dark: { bg: '#111111', 'bg-elev': '#111111', surface: '#111111', text: '#444444' } }
    render(<ThemeChooser value={faint} themes={SHIPPED} onChange={() => undefined} />)
    const warning = screen.getByRole('status')
    expect(warning.textContent).toContain('Dark: Text')
    expect(warning.textContent).toContain('1.94')
  })
})
