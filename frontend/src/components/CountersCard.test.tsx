/** A row of icons with numbers, and the data may pick this drawing for a card that is normally a value. */
import { render, screen } from '@testing-library/react'

import type { WidgetView } from '../lib/types'
import { CountersCard, renderWidget } from './renderers'

const widget: WidgetView = { id: 3, kind: 'plex.library', title: 'Library', icon: 'plex', link: '', renderer: 'value', options: {}, integration_id: 1, refresh_seconds: null }

describe('CountersCard', () => {
  it('shows one icon and number per item', () => {
    render(<CountersCard widget={widget} data={{ status: 'ok', items: [{ label: 'Movies', value: 3554, icon: 'lucide:film' }, { label: 'Playing', value: 1, icon: 'lucide:play' }] }} />)
    const row = screen.getByTestId('counters')
    expect(row.querySelectorAll('svg')).toHaveLength(2)
    expect(screen.getByText((3554).toLocaleString())).toBeInTheDocument()
    expect(screen.getByText('Movies')).toBeInTheDocument()
  })

  it('is chosen by the data over the widget renderer', () => {
    render(<>{renderWidget({ widget, data: { status: 'ok', items: [{ label: 'Series', value: 178, icon: 'lucide:tv' }], meta: { renderer: 'counters' } } })}</>)
    expect(screen.getByTestId('counters')).toBeInTheDocument()
  })
})
