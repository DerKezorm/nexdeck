/**
 * A value card whose adapter declares no metric draws a line under its big
 * number all the same: the stream keeps the number as `headline`, the same
 * rule the server uses, and the card picks that line up.
 */
import { render } from '@testing-library/react'

import { renderWidget } from '../components/renderers'
import { useLive } from '../stores/live'
import { HEADLINE, recordedMetrics } from './recorded'
import type { WidgetData, WidgetView } from './types'

const VIEW: WidgetView = {
  id: 1,
  kind: 'plex.library',
  title: 'Library',
  icon: '',
  link: '',
  renderer: 'value',
  options: {},
  integration_id: 1,
  refresh_seconds: 60,
}

describe('recorded metrics', () => {
  beforeEach(() => {
    useLive.setState({ data: {}, series: {}, health: {}, logs: {} })
  })

  it('are the declared metrics, else the number itself', () => {
    expect(recordedMetrics({ status: 'ok', primary: { label: 'Load', value: 3 }, metrics: { load: 0.4 } } as WidgetData)).toEqual({ load: 0.4 })
    expect(recordedMetrics({ status: 'ok', primary: { label: 'Films', value: 1284 } } as WidgetData)).toEqual({ [HEADLINE]: 1284 })
    expect(recordedMetrics({ status: 'ok', primary: { label: 'Version', value: '1.2' } } as WidgetData)).toEqual({})
    expect(recordedMetrics({ status: 'bad', primary: { label: 'Films', value: 1284 }, error: 'gone' } as WidgetData)).toEqual({})
  })

  it('grow the line from the answers the stream pushes', () => {
    for (const [at, value] of [[1, 10], [2, 12]]) {
      useLive.getState().applyWidget(1, { status: 'ok', primary: { label: 'Films', value }, updated_at: at } as unknown as WidgetData)
    }
    useLive.getState().applyWidget(1, { status: 'bad', error: 'gone', primary: { label: 'Films', value: 0 } } as unknown as WidgetData)
    expect(useLive.getState().series[1][HEADLINE]).toEqual([10, 12])
  })

  it('give a value card without a declared metric its line', () => {
    const data = { status: 'ok', primary: { label: 'Films', value: 12 } } as WidgetData
    const { container } = render(<>{renderWidget({ widget: VIEW, data, series: { [HEADLINE]: [8, 9, 10, 11, 12] } })}</>)
    expect(container.querySelector('svg')).not.toBeNull()
  })
})
