/**
 * Every renderer draws the demo data of the design preview without throwing,
 * and the pieces a user relies on are in the DOM: values, titles, actions.
 */
import { render, screen } from '@testing-library/react'

import { DEMO_DATA, DEMO_SERIES, DEMO_VIEWS } from '../demo/board'
import type { Action, WidgetData, WidgetView } from '../lib/types'
import { renderWidget } from './renderers'
import { WidgetCard } from './WidgetCard'

describe('renderers', () => {
  it('draw every demo widget', () => {
    let drawn = 0
    for (const view of DEMO_VIEWS) {
      const { unmount } = render(<>{renderWidget({ widget: view, data: DEMO_DATA[view.id], series: DEMO_SERIES[view.id], canAct: true, onAction: () => undefined })}</>)
      drawn += 1
      unmount()
    }
    expect(drawn).toBe(DEMO_VIEWS.length)
  })

  it('keeps the bar of a percentage row once its history has come in', () => {
    const view = { ...DEMO_VIEWS[0], id: 9, renderer: 'stats' } as WidgetView
    const data = {
      status: 'ok',
      primary: { label: 'CPU', value: 82, unit: '%' },
      metrics: { cpu: 82 },
      secondary: [{ label: 'Traffic', value: 3.2, unit: 'MB/s', metric: 'rx' }],
    } as unknown as WidgetData
    const series = { cpu: [10, 30, 50, 70, 80, 82], rx: [1, 2, 3, 2, 3, 3.2] }
    render(<>{renderWidget({ widget: view, data, series })}</>)
    const cpu = screen.getByTitle('CPU').parentElement!
    const bar = cpu.querySelector('.bar')
    expect(bar).toHaveAttribute('data-status', 'warn')
    expect(bar?.querySelector('i')).toHaveStyle({ width: '82%' })
    expect(cpu.querySelector('svg')).toBeNull()
    // A row that is not a share keeps its line.
    expect(screen.getByTitle('Traffic').parentElement!.querySelector('svg')).not.toBeNull()
  })

  it('shows the time of a timed calendar entry and none for an all-day one', () => {
    const view = { ...DEMO_VIEWS[0], id: 10, renderer: 'calendar' } as WidgetView
    const today = new Date().toISOString().slice(0, 10)
    const data = { status: 'ok', items: [{ date: today, title: 'Holiday' }, { date: today, title: 'Choir', time: '19:30' }] } as unknown as WidgetData
    const { container } = render(<>{renderWidget({ widget: view, data })}</>)
    const times = container.querySelectorAll('time')
    expect(times).toHaveLength(1)
    expect(times[0]).toHaveAttribute('datetime', '19:30')
    expect(times[0].closest('div')).toHaveTextContent('Choir')
  })

  it('draws the availability bars of a status row and how long ago a notice came', () => {
    const view = { ...DEMO_VIEWS[0], id: 11, renderer: 'list' } as WidgetView
    const now = Date.now() / 1000
    const data = {
      status: 'bad',
      meta: { bars: '24h' },
      items: [
        { title: 'Nextcloud', subtitle: 'ConnectError', status: 'bad', value: 97, unit: '%', bars: [1, 1, 0.5, 0, null] },
        { title: 'Backup written', status: 'ok', when: now - 240 },
      ],
    } as unknown as WidgetData
    render(<>{renderWidget({ widget: view, data })}</>)
    const bars = screen.getAllByTestId('availability-bars')
    expect(bars).toHaveLength(1)
    expect(bars[0].children).toHaveLength(5)
    expect(screen.getByText('97%')).toBeInTheDocument()
    expect(screen.getByText('4m')).toBeInTheDocument()
  })

  it('shows the value and the unit of a value card', () => {
    const view = DEMO_VIEWS.find((v) => v.renderer === 'value')!
    render(<WidgetCard widget={view} data={DEMO_DATA[view.id]} series={DEMO_SERIES[view.id]} />)
    expect(screen.getByText(String(DEMO_DATA[view.id].primary?.value))).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: view.title })).toBeInTheDocument()
  })

  it('offers list actions only when acting is allowed', () => {
    const view = DEMO_VIEWS.find((v) => v.kind === 'docker.containers')!
    const received: Action[] = []
    const { unmount } = render(<WidgetCard widget={view} data={DEMO_DATA[view.id]} canAct onAction={(action) => received.push(action)} />)
    expect(screen.getAllByRole('button', { name: 'Restart' }).length).toBeGreaterThan(0)
    unmount()
    render(<WidgetCard widget={view} data={DEMO_DATA[view.id]} canAct={false} />)
    expect(screen.queryByRole('button', { name: 'Restart' })).toBeNull()
  })

  it('offers a row file as a real download, pointed at nexdeck', () => {
    // ⚠️ Both halves matter. `download` is ignored across origins, so a link
    // straight to the service would play the video in a tab instead of saving
    // it, and on a homelab the browser usually cannot reach the service at all.
    const view = { ...DEMO_VIEWS[0], id: 7, renderer: 'list' } as WidgetView
    const data = {
      status: 'ok',
      items: [{ title: 'Me at the zoo', file: { path: '/download/Me%20at%20the%20zoo.webm', name: 'Me at the zoo.webm' } }],
    } as unknown as WidgetData
    render(<>{renderWidget({ widget: view, data, canAct: false })}</>)
    const link = screen.getByRole('link', { name: /Me at the zoo\.webm/ })
    expect(link).toHaveAttribute('download', 'Me at the zoo.webm')
    expect(link.getAttribute('href')).toContain('/widgets/7/file?path=')
    expect(link.getAttribute('href')).toContain(encodeURIComponent('/download/Me%20at%20the%20zoo.webm'))
  })

  it('shows row buttons without a hover only when the card asks for it', () => {
    // ⚠️ A touchscreen has no hover. A card whose rows exist to be pressed
    // says so; every other list keeps its buttons out of the way.
    const view = { ...DEMO_VIEWS[0], id: 8, renderer: 'list' } as WidgetView
    const rows = [{ title: 'Copper Sky', actions: [{ id: 'approve', label: 'Approve' }] }]
    const draw = (meta: Record<string, unknown>) =>
      render(<>{renderWidget({ widget: view, data: { status: 'ok', items: rows, meta } as unknown as WidgetData, canAct: true, onAction: () => undefined })}</>)

    const quiet = draw({})
    expect(quiet.getByRole('button', { name: /Approve|Freigeben/ }).closest('span')?.className).toContain('opacity-0')
    quiet.unmount()

    draw({ actions_visible: true })
    expect(screen.getByRole('button', { name: /Approve|Freigeben/ }).closest('span')?.className).not.toContain('opacity-0')
  })

  it('marks a failed widget with its error', () => {
    const view = DEMO_VIEWS[3]
    render(<WidgetCard widget={view} data={{ status: 'unknown', error: 'The service could not be reached.' }} />)
    expect(screen.getByText('The service could not be reached.')).toBeInTheDocument()
  })
})
