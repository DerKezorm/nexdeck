import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { DEMO_VIEWS } from '../demo/board'
import type { WidgetData, WidgetView } from '../lib/types'
import { renderWidget } from './renderers'

const view = { ...DEMO_VIEWS[0], id: 42, kind: 'unifi.summary', renderer: 'stats' } as WidgetView
const data = {
  status: 'ok',
  primary: { label: 'Clients', value: 12, metric: 'clients' },
  secondary: [
    { label: 'WAN down', value: '303 Mbit/s', metric: 'wan_down' },
    { label: 'WAN up', value: '4.2 Mbit/s', metric: 'wan_up' },
  ],
  metrics: { clients: 12, wan_down: 303, wan_up: 4.2 },
  meta: { renderer: 'inout', inout: ['wan_down', 'wan_up'] },
} as unknown as WidgetData

describe('in and out, mirrored', () => {
  it('draws in above the axis and out below, with what each is now', () => {
    render(<>{renderWidget({ widget: view, data, series: { wan_down: [100, 300, 200], wan_up: [2, 4, 3] } })}</>)
    const chart = screen.getByTestId('inout')
    expect(chart.querySelectorAll('path')).toHaveLength(4)
    expect(screen.getByText('303 Mbit/s')).toBeInTheDocument()
    expect(screen.getByText('4.2 Mbit/s')).toBeInTheDocument()
  })

  it('waits for a history before it draws one', () => {
    render(<>{renderWidget({ widget: view, data, series: { wan_down: [100] } })}</>)
    expect(screen.queryByTestId('inout')).toBeNull()
  })
})
