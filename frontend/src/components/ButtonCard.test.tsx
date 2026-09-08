/**
 * The button card: one card, one button, and where it is allowed to lead.
 *
 * ⚠️ The target decides the element. A board stays inside nexdeck and has to
 * be a router link, or a press reloads the whole app to go one board over and
 * a wall display drops its stream. An address leaves and has to be an anchor.
 * A target that is neither leads nowhere at all: the address is typed in by
 * hand, and it must not be able to talk the app into running something.
 */
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { ButtonCard, readableOn, targetOf } from './ButtonCard'
import type { WidgetData, WidgetView } from '../lib/types'

function widget(title = 'Network', icon = 'lucide:network'): WidgetView {
  return { id: 1, title, icon, renderer: 'button' } as unknown as WidgetView
}

function show(meta: Record<string, unknown>, editing = false, one = widget()) {
  return render(
    <MemoryRouter>
      <ButtonCard widget={one} data={{ meta } as unknown as WidgetData} editing={editing} />
    </MemoryRouter>,
  )
}

describe('targetOf', () => {
  it('reads a board and one page of it', () => {
    expect(targetOf('board', 'home')).toEqual({ inside: '/b/home' })
    expect(targetOf('board', 'home/media')).toEqual({ inside: '/b/home/media' })
    expect(targetOf('board', ' /home/ ')).toEqual({ inside: '/b/home' })
  })

  it('reads an address', () => {
    expect(targetOf('link', 'https://nas.example.com')).toEqual({ outside: 'https://nas.example.com' })
  })

  it('refuses an address that would run as part of nexdeck', () => {
    expect(targetOf('link', 'javascript:alert(1)')).toBeNull()
    expect(targetOf('link', 'data:text/html,<script>alert(1)</script>')).toBeNull()
  })

  it('refuses a board name that is not one', () => {
    expect(targetOf('board', '../settings')).toBeNull()
    expect(targetOf('board', 'home/media/extra')).toBeNull()
    expect(targetOf('board', '')).toBeNull()
  })
})

describe('ButtonCard', () => {
  it('keeps a board inside the app', () => {
    show({ kind: 'board', where: 'network' })
    const link = screen.getByRole('link', { name: 'Network' })
    expect(link).toHaveAttribute('href', '/b/network')
    expect(link).not.toHaveAttribute('target')
  })

  it('sends an address out, in a new tab unless told otherwise', () => {
    const { rerender } = show({ kind: 'link', where: 'https://nas.example.com' })
    const away = screen.getByRole('link', { name: 'Network' })
    expect(away).toHaveAttribute('href', 'https://nas.example.com')
    expect(away).toHaveAttribute('target', '_blank')
    expect(away).toHaveAttribute('rel', expect.stringContaining('noopener'))

    rerender(
      <MemoryRouter>
        <ButtonCard widget={widget()} data={{ meta: { kind: 'link', where: 'https://nas.example.com', new_tab: false } } as unknown as WidgetData} />
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: 'Network' })).not.toHaveAttribute('target')
  })

  it('takes its name and symbol from the card, not from a second field', () => {
    show({ kind: 'board', where: 'home' }, false, widget('Kitchen'))
    expect(screen.getByRole('link', { name: 'Kitchen' })).toBeInTheDocument()
  })

  it('keeps the name when only the symbol is shown', () => {
    // ⚠️ Named outright. Without the text there is nothing else to read it
    // by, and a `title` is a hover text: announced unreliably, never reachable
    // by touch.
    show({ kind: 'board', where: 'home', look: 'icon' })
    const only = screen.getByRole('link', { name: 'Network' })
    expect(only).toHaveAttribute('aria-label', 'Network')
    expect(screen.queryByText('Network')).toBeNull()
  })

  it('shows the name alone when the symbol is switched off', () => {
    show({ kind: 'board', where: 'home', look: 'text' })
    expect(screen.getByText('Network')).toBeInTheDocument()
    expect(document.querySelector('svg, img')).toBeNull()
  })

  it('leads nowhere while the board is being arranged', () => {
    show({ kind: 'board', where: 'home' }, true)
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.getByText('Network')).toBeInTheDocument()
  })

  it('is no link at all when it leads nowhere', () => {
    show({ kind: 'link', where: 'javascript:alert(1)' })
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('paints itself in the colour it was given', () => {
    show({ kind: 'board', where: 'home', colour: '#ff8800' })
    const link = screen.getByRole('link', { name: 'Network' })
    expect(link.style.background).toBe('rgb(255, 136, 0)')
  })
})

describe('readableOn', () => {
  it('puts dark text on a light ground and light text on a dark one', () => {
    // ⚠️ Measured, not guessed. A picked colour is a ground the name has to
    // be read on, and a pale yellow with white on it is a card nobody can
    // read at all.
    expect(readableOn('#ffe066')).toBe('#0b1116')
    expect(readableOn('#22d3ee')).toBe('#0b1116')
    expect(readableOn('#0e7490')).toBe('#ffffff')
    expect(readableOn('#000000')).toBe('#ffffff')
  })

  it('copes with three digits and with nonsense', () => {
    expect(readableOn('#fff')).toBe('#0b1116')
    expect(readableOn('rebeccapurple')).toBe('#ffffff')
  })
})
