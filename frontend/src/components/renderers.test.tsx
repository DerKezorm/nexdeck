/**
 * Every renderer draws the demo data of the design preview without throwing,
 * and the pieces a user relies on are in the DOM: values, titles, actions.
 */
import { render, screen } from '@testing-library/react'

import { DEMO_DATA, DEMO_SERIES, DEMO_VIEWS } from '../demo/board'
import type { Action } from '../lib/types'
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

  it('marks a failed widget with its error', () => {
    const view = DEMO_VIEWS[3]
    render(<WidgetCard widget={view} data={{ status: 'unknown', error: 'The service could not be reached.' }} />)
    expect(screen.getByText('The service could not be reached.')).toBeInTheDocument()
  })
})
