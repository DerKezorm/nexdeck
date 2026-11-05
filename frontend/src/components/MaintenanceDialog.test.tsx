/**
 * Maintenance from the card: an administrator sees the button, a card in
 * maintenance says until when, and the dialog sends what was chosen.
 */
import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { WidgetView } from '../lib/types'
import { useAuth } from '../stores/auth'
import { endOnTheClock, maintenanceTarget, weekdayNames } from '../lib/maintenance'
import { nextTime } from './MaintenanceDialog'
import { WidgetCard } from './WidgetCard'

const sent: { method: string; path: string; body?: unknown }[] = []
const plans: unknown[] = []
vi.mock('../api/client', async (original) => ({
  ...(await original<typeof import('../api/client')>()),
  get: vi.fn(async (path: string) => {
    sent.push({ method: 'GET', path })
    return path.startsWith('/maintenance/plans') ? plans : {}
  }),
  post: vi.fn(async (path: string, body?: unknown) => {
    sent.push({ method: 'POST', path, body })
    return path === '/maintenance/plans' ? { id: 31, integration_id: 7, widget_id: null, name: 'Movies', minutes: 120, zone: 'Europe/Berlin', next_starts_at: null, next_ends_at: null, ...(body as object) } : {}
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
    plans.length = 0
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
    expect(sent.filter((one) => one.method !== 'GET')).toEqual([{ method: 'POST', path: '/maintenance', body: { integration_id: 7, minutes: 240 } }])
  })

  it('says until when on a card in maintenance, and ends it', async () => {
    const until = new Date(Date.now() + 3600_000).toISOString()
    card({ ...QUEUE, maintenance: { id: 12, until } })
    const chip = screen.getByTestId('card-maintenance')
    expect(chip.getAttribute('aria-label')).toContain('Maintenance until')
    fireEvent.click(chip)
    const end = await screen.findByRole('button', { name: 'End now' })
    await act(async () => fireEvent.click(end))
    expect(sent.filter((one) => one.method !== 'GET')).toEqual([{ method: 'DELETE', path: '/maintenance/12' }])
  })

  it('shows a member until when, without a way to change it', () => {
    useAuth.setState({ user: { id: 2, username: 'kim', role: 'user' } as never })
    card({ ...QUEUE, maintenance: { id: 12, until: new Date(Date.now() + 3600_000).toISOString() } })
    expect(screen.getByTestId('card-maintenance').tagName).toBe('SPAN')
  })

  it('names the weekdays from Monday and the end of a window on the clock, past midnight too', () => {
    expect(weekdayNames('en')).toEqual(['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'])
    expect(endOnTheClock('03:00', 120)).toBe('05:00')
    expect(endOnTheClock('23:30', 90)).toBe('01:00')
  })

  it('lists the weekly maintenance of the connection and removes one', async () => {
    plans.push({ id: 30, integration_id: 7, widget_id: null, name: 'Movies', days: [2, 6], starts: '03:00', minutes: 120, zone: 'UTC', next_starts_at: new Date().toISOString(), next_ends_at: null })
    card(QUEUE)
    fireEvent.click(screen.getByRole('button', { name: 'Maintenance' }))
    const weekly = await screen.findByTestId('maintenance-weekly')
    expect(await screen.findByText('Wed, Sun, 03:00 AM to 05:00 AM (UTC)')).toBeTruthy()
    expect(sent).toContainEqual({ method: 'GET', path: '/maintenance/plans?integration_id=7' })
    expect(weekly.textContent).toContain('Next:')
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Remove Wed, Sun, 03:00 AM to 05:00 AM (UTC)' })))
    expect(sent).toContainEqual({ method: 'DELETE', path: '/maintenance/plans/30' })
    expect(screen.queryByText('Wed, Sun, 03:00 AM to 05:00 AM (UTC)')).toBeNull()
    expect(weekly.textContent).toContain('Nothing planned yet.')
  })

  it('plans maintenance on the chosen days, from a time, for so long, on the clock of the browser', async () => {
    card(QUEUE)
    fireEvent.click(screen.getByRole('button', { name: 'Maintenance' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Plan weekly maintenance' }))
    const form = screen.getByTestId('maintenance-weekly-new')
    fireEvent.click(screen.getByRole('button', { name: 'Wed' }))
    fireEvent.change(form.querySelector('input[type="time"]') as HTMLInputElement, { target: { value: '04:30' } })
    fireEvent.change(form.querySelector('select') as HTMLSelectElement, { target: { value: '3' } })
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Add to the plan' })))
    const [made] = sent.filter((one) => one.method === 'POST')
    expect(made).toEqual({ method: 'POST', path: '/maintenance/plans', body: { integration_id: 7, days: [2, 6], starts: '04:30', minutes: 180, zone: Intl.DateTimeFormat().resolvedOptions().timeZone } })
    expect(await screen.findByText('Wed, Sun, 04:30 AM to 07:30 AM')).toBeTruthy()
    expect(screen.queryByTestId('maintenance-weekly-new')).toBeNull()
  })

  it('keeps the add button from a day-less plan', async () => {
    card(QUEUE)
    fireEvent.click(screen.getByRole('button', { name: 'Maintenance' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Plan weekly maintenance' }))
    fireEvent.click(screen.getByRole('button', { name: 'Sun' }))
    expect((screen.getByRole('button', { name: 'Add to the plan' }) as HTMLButtonElement).disabled).toBe(true)
  })
})
