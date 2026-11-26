/**
 * A list row can show the colour of the thing itself in place of its dot: the filament on a spool in an AMS.
 *
 * Only `#rrggbb` reaches the style; anything else keeps the ordinary dot, so a service cannot put its own CSS there.
 */
import { render } from '@testing-library/react'

import type { WidgetData, WidgetView } from '../lib/types'
import { renderWidget } from './renderers'

const VIEW: WidgetView = {
  id: 1,
  kind: 'bambuddy.ams',
  title: 'AMS',
  icon: '',
  link: '',
  renderer: 'list',
  options: {},
  integration_id: 1,
  refresh_seconds: 60,
}

function dotOf(item: Record<string, unknown>): HTMLElement {
  const data: WidgetData = { status: 'ok', items: [{ title: 'A1 · PLA Basic', value: 70, unit: '%', status: 'ok', ...item }] }
  const { container } = render(<>{renderWidget({ widget: VIEW, data })}</>)
  return container.querySelector('li .dot') as HTMLElement
}

describe('list row swatches', () => {
  it('paint the dot in the colour of the row', () => {
    const dot = dotOf({ swatch: '#f4ee2a' })
    expect(dot.style.background).toBe('rgb(244, 238, 42)')
    expect(dot.hasAttribute('data-swatch')).toBe(true)
  })

  it('leave anything but #rrggbb out of the style', () => {
    for (const swatch of ['red', '#fff', 'url(https://example.com/x.png)', '#f4ee2a; background-image: url(x)', 42]) {
      const dot = dotOf({ swatch })
      expect(dot.style.background).toBe('')
      expect(dot.getAttribute('data-status')).toBe('ok')
    }
  })

  it('keep the status dot without one', () => {
    const dot = dotOf({ status: 'warn' })
    expect(dot.hasAttribute('data-swatch')).toBe(false)
    expect(dot.getAttribute('data-status')).toBe('warn')
  })
})
