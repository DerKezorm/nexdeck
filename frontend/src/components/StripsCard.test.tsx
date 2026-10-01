import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { DEMO_VIEWS } from '../demo/board'
import type { WidgetData, WidgetView } from '../lib/types'
import { renderWidget } from './renderers'

const view = { ...DEMO_VIEWS[0], id: 41, kind: 'core.status', renderer: 'list' } as WidgetView

describe('the status page as strips', () => {
  it('draws one wide strip per service when the data asks for it', () => {
    const data = {
      status: 'bad',
      items: [
        { title: 'Nextcloud', subtitle: 'unreachable', status: 'bad', value: 97, unit: '%', bars: [1, 1, 0.5, 0, null] },
        { title: 'Jellyfin', status: 'ok', value: 100, unit: '%', bars: [1, 1, 1, 1, 1] },
      ],
      meta: { renderer: 'strips', bars: '24h' },
    } as unknown as WidgetData
    render(<>{renderWidget({ widget: view, data })}</>)
    const strips = screen.getAllByTestId('strip')
    expect(strips).toHaveLength(2)
    expect(strips[0].children).toHaveLength(5)
    expect(screen.getByText('97%')).toBeInTheDocument()
    expect(strips[0]).toHaveAccessibleName(/Nextcloud/)
  })

  it('keeps the rows when the data does not ask for strips', () => {
    const data = { status: 'ok', items: [{ title: 'Jellyfin', status: 'ok', bars: [1, 1] }], meta: { bars: '24h' } } as unknown as WidgetData
    render(<>{renderWidget({ widget: view, data })}</>)
    expect(screen.queryByTestId('strips')).toBeNull()
  })
})
