/**
 * Maintenance from the card: an administrator sees the button, a card in
 * maintenance says until when, and the dialog sends what was chosen.
 */
import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { WidgetView } from '../lib/types'
import { useAuth } from '../stores/auth'
import { maintenanceTarget } from '../lib/maintenance'
import { nextTime } from './MaintenanceDialog'
import { WidgetCard } from './WidgetCard'

const sent: { method: string; path: string; body?: unknown }[] = []
vi.mock('../api/client', async (original) => ({
  ...(await original<typeof import('../api/client')>()),
  post: vi.fn(async (path: string, body?: unknown) => {
    sent.push({ method: 'POST', path, body })
    return {}
  }),
  del: vi.fn(async (path: string) => {
    sent.push({ method: 'DELETE', path })
  }),
}))

const QUEUE: WidgetView = {
  id: 4,
  kind: 'radarr.queue',
  title: 'Radarr',
  icon: '',
  link: '',
  renderer: 'list',
  options: {},
  integration_id: 7,
  integration_name: 'Movies',
  refresh_seconds: 30,
}

function card(view: WidgetView) {
  return render(<MemoryRouter><WidgetCard widget={view} data={{ status: 'ok', items: [] }} /></MemoryRouter>)
}

describe('maintenance', () => {
  beforeEach(() => {
    sent.length = 0
    useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin' } as never })
  })

  it('takes the next time the clock shows: today while it is ahead, else tomorrow', () => {
    const evening = new Date(2026, 9, 24, 21, 0)
    expect(nextTime('22:00', evening)?.getDate()).toBe(24)
    expect(nextTime('20:00', evening)?.getDate()).toBe(25)
    expect(nextTime('half past', evening)).toBeNull()
  })

  it('is for the connection of a card, the tile itself, and nothing for a clock', () => {
    expect(maintenanceTarget(QUEUE)).toEqual({ integration_id: 7 })
    expect(maintenanceTarget({ ...QUEUE, kind: 'core.app', integration_id: null, health: { id: 1 } as never })).toEqual({ widget_id: 4 })
    expect(maintenanceTarget({ ...QUEUE, kind: 'core.clock', integration_id: null })).toBeNull()
  })

  it('offers an administrator the button and nobody else', () => {
    card(QUEUE)
    expect(screen.getByRole('button', { name: 'Maintenance' })).toBeTruthy()
    act(() => useAuth.setState({ user: { id: 2, username: 'kim', role: 'user' } as never }))
    expect(screen.queryByRole('button', { name: 'Maintenance' })).toBeNull()
  })

  it('starts maintenance for the chosen hours on the whole connection', async () => {
    card(QUEUE)
    fireEvent.click(screen.getByRole('button', { name: 'Maintenance' }))
    // The dialog loads when it is first opened.
    expect((await screen.findByTestId('maintenance-dialog')).textContent).toContain('Every card of this connection goes along.')
    fireEvent.click(screen.getByRole('button', { name: '4 hours' }))
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Start maintenance' })))
    expect(sent).toEqual([{ method: 'POST', path: '/maintenance', body: { integration_id: 7, minutes: 240 } }])
  })

  it('says until when on a card in maintenance, and ends it', async () => {
    const until = new Date(Date.now() + 3600_000).toISOString()
    card({ ...QUEUE, maintenance: { id: 12, until } })
    const chip = screen.getByTestId('card-maintenance')
    expect(chip.getAttribute('aria-label')).toContain('Maintenance until')
    fireEvent.click(chip)
    const end = await screen.findByRole('button', { name: 'End now' })
    await act(async () => fireEvent.click(end))
    expect(sent).toEqual([{ method: 'DELETE', path: '/maintenance/12' }])
  })

  it('shows a member until when, without a way to change it', () => {
    useAuth.setState({ user: { id: 2, username: 'kim', role: 'user' } as never })
    card({ ...QUEUE, maintenance: { id: 12, until: new Date(Date.now() + 3600_000).toISOString() } })
    expect(screen.getByTestId('card-maintenance').tagName).toBe('SPAN')
  })
})
