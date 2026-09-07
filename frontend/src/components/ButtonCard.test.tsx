/**
 * Buttons, and where each one is allowed to lead.
 *
 * ⚠️ The target decides the element. A board stays inside nexdeck and has to
 * be a router link, or a press reloads the whole app to go one board over and
 * a wall display drops its stream. An address leaves and has to be an anchor.
 * And a target that is neither leads nowhere at all: a card whose text is
 * typed by hand must not be able to talk the app into opening something it
 * was never meant to.
 */
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { ButtonCard, targetOf } from './ButtonCard'
import type { WidgetData, WidgetView } from '../lib/types'

const WIDGET = { id: 1, title: 'Jump', renderer: 'button' } as unknown as WidgetView

function show(items: { title: string; url: string; icon?: string }[], meta: Record<string, unknown> = {}, editing = false) {
  const data = { items, meta } as unknown as WidgetData
  return render(
    <MemoryRouter>
      <ButtonCard widget={WIDGET} data={data} editing={editing} />
    </MemoryRouter>,
  )
}

describe('targetOf', () => {
  it('reads a board and a page of one', () => {
    expect(targetOf('home')).toEqual({ inside: '/b/home' })
    expect(targetOf('home/media')).toEqual({ inside: '/b/home/media' })
    expect(targetOf(' /home/ ')).toEqual({ inside: '/b/home' })
  })

  it('reads an address', () => {
    expect(targetOf('https://nas.example.com')).toEqual({ outside: 'https://nas.example.com' })
  })

  it('refuses an address that would run as part of nexdeck', () => {
    // ⚠️ The buttons are typed into a text field. javascript: in one of them
    // would run in nexdeck's own origin, with the session.
    expect(targetOf('javascript:alert(1)')).toBeNull()
    expect(targetOf('data:text/html,<script>alert(1)</script>')).toBeNull()
  })

  it('refuses a path that is not a board', () => {
    expect(targetOf('../settings')).toBeNull()
    expect(targetOf('home/media/extra')).toBeNull()
    expect(targetOf('')).toBeNull()
  })
})

describe('ButtonCard', () => {
  it('keeps a board inside the app and sends an address out', () => {
    show([
      { title: 'Network', url: 'network' },
      { title: 'NAS', url: 'https://nas.example.com' },
    ])
    const inside = screen.getByRole('link', { name: 'Network' })
    expect(inside).toHaveAttribute('href', '/b/network')
    expect(inside).not.toHaveAttribute('target')

    const outside = screen.getByRole('link', { name: 'NAS' })
    expect(outside).toHaveAttribute('href', 'https://nas.example.com')
    expect(outside).toHaveAttribute('target', '_blank')
    expect(outside).toHaveAttribute('rel', expect.stringContaining('noopener'))
  })

  it('leads nowhere while the board is being arranged', () => {
    // A press that navigates away in edit mode takes the arrangement with it.
    show([{ title: 'Network', url: 'network' }], {}, true)
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.getByText('Network')).toBeInTheDocument()
  })

  it('keeps the name when the titles are switched off', () => {
    // ⚠️ Without the titles the buttons are symbols, and a symbol has no name
    // for anything that reads the screen aloud.
    show([{ title: 'Network', url: 'network' }], { labels: false })
    const only = screen.getByRole('link', { name: 'Network' })
    expect(screen.queryByText('Network')).toBeNull()
    // ⚠️ Named outright, not by its tooltip. A `title` does end up as the
    // accessible name when nothing else offers one, which is why dropping the
    // label here looks harmless and is not: it is a hover text, announced
    // unreliably and never reachable by touch.
    expect(only).toHaveAttribute('aria-label', 'Network')
  })

  it('draws a button that leads nowhere as no link at all', () => {
    show([{ title: 'Broken', url: 'javascript:alert(1)' }])
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.getByText('Broken')).toBeInTheDocument()
  })

  it('says so when there are no buttons', () => {
    show([])
    expect(screen.getByText(/No buttons yet/)).toBeInTheDocument()
  })
})
