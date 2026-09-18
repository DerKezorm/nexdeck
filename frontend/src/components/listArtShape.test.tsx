/**
 * A list row shows a camera detection's crop square, a cover tall.
 *
 * The Frigate detections card gives each row its thumbnail (issue #1). The
 * list had only the poster shape, which squeezes a square crop into a strip.
 */
import { render } from '@testing-library/react'

import type { WidgetData, WidgetView } from '../lib/types'
import { renderWidget } from './renderers'

const VIEW: WidgetView = {
  id: 1,
  kind: 'frigate.events',
  title: 'Detections',
  icon: '',
  link: '',
  renderer: 'list',
  options: {},
  integration_id: 1,
  refresh_seconds: 30,
}

function frameOf(item: Record<string, unknown>): HTMLElement {
  const data: WidgetData = { status: 'ok', items: [{ title: 'Car', subtitle: 'front_gate · 18:17', ...item }] }
  const { container } = render(<>{renderWidget({ widget: VIEW, data })}</>)
  return container.querySelector('li img')!.parentElement as HTMLElement
}

describe('list row pictures', () => {
  it('are square for a detection', () => {
    expect(frameOf({ art: 'proxy:/thumb/1726680000.5-ab12cd', art_shape: 'square' }).className).toContain('aspect-square')
  })

  it('stay a cover without a shape', () => {
    expect(frameOf({ art: 'proxy:/Items/1/Images/Primary' }).className).toContain('aspect-[2/3]')
  })
})
