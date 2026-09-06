/**
 * The dial. Two things it must never do: show a percentage where the card
 * measures megabytes, and point the needle somewhere the number does not.
 */
import { render, screen } from '@testing-library/react'

import type { WidgetData, WidgetView } from '../lib/types'
import { GaugeCard } from './renderers'

const VIEW = { id: 1, renderer: 'gauge' } as unknown as WidgetView

function draw(data: WidgetData) {
  return render(<GaugeCard widget={VIEW} data={data} />)
}

/** How far round the needle points, as a share of the dial. */
function needleShare(container: HTMLElement): number {
  const needle = container.querySelectorAll('line')[5] as SVGLineElement | undefined
  const x = Number(needle?.getAttribute('x2'))
  const y = Number(needle?.getAttribute('y2'))
  let degrees = (Math.atan2(y - 50, x - 50) * 180) / Math.PI
  if (degrees < 135) degrees += 360
  return ((degrees - 135) / 270) * 100
}

describe('GaugeCard', () => {
  it('shows the measured number and its unit, not a percentage', () => {
    draw({
      status: 'ok',
      primary: { label: 'Download', value: 38, unit: 'MB/s' },
      meta: { renderer: 'gauge', gauge: { share: 90, max: 48 } },
    } as WidgetData)
    expect(screen.getByText('38MB/s')).toBeInTheDocument()
    expect(screen.queryByText('90%')).toBeNull()
  })

  it('says what counts as full, because a dial alone cannot', () => {
    draw({
      status: 'ok',
      primary: { label: 'Download', value: 43.3, unit: 'MB/s' },
      meta: { renderer: 'gauge', gauge: { share: 90, max: 48 } },
    } as WidgetData)
    expect(screen.getByText(/48MB\/s/)).toBeInTheDocument()
  })

  it('points the needle at the share, not at the number', () => {
    const { container } = draw({
      status: 'ok',
      primary: { label: 'Download', value: 43.3, unit: 'MB/s' },
      meta: { renderer: 'gauge', gauge: { share: 90, max: 48 } },
    } as WidgetData)
    expect(needleShare(container)).toBeCloseTo(90, 0)
  })

  it('stays quiet about the ceiling of a card that is already a percentage', () => {
    draw({ status: 'ok', primary: { label: 'Blocked', value: 18, unit: '%' }, meta: { renderer: 'gauge' } } as WidgetData)
    expect(screen.queryByText(/of 100%/)).toBeNull()
  })

  it('reads a card that measures a percentage to begin with', () => {
    const { container } = draw({
      status: 'ok',
      primary: { label: 'Blocked', value: 42, unit: '%' },
      meta: { renderer: 'gauge' },
    } as WidgetData)
    expect(screen.getByText('42%')).toBeInTheDocument()
    expect(needleShare(container)).toBeCloseTo(42, 0)
  })

  it('parks the needle at the start when there is nothing to show', () => {
    const { container } = draw({ status: 'ok', primary: { label: 'Download', value: 0, unit: 'MB/s' }, meta: { renderer: 'gauge', gauge: { share: 0, max: 48 } } } as WidgetData)
    expect(needleShare(container)).toBeCloseTo(0, 0)
    expect(screen.getByText('0MB/s')).toBeInTheDocument()
  })

  it('never runs the needle past the end of the dial', () => {
    const { container } = draw({ status: 'ok', primary: { label: 'Download', value: 999, unit: 'MB/s' }, meta: { renderer: 'gauge', gauge: { share: 140, max: 48 } } } as WidgetData)
    expect(needleShare(container)).toBeCloseTo(100, 0)
  })

  it('opens the dial downwards, the way a rev counter does', () => {
    const { container } = draw({ status: 'ok', primary: { label: 'Download', value: 0, unit: 'MB/s' }, meta: { renderer: 'gauge', gauge: { share: 0, max: 48 } } } as WidgetData)
    const track = container.querySelector('path')!.getAttribute('d')!
    const [, x1, y1] = /M ([\d.]+) ([\d.]+)/.exec(track)!.map(Number) as unknown as number[]
    // 135° on a downward y axis is bottom left, below the middle of the face.
    expect(Number(x1)).toBeLessThan(50)
    expect(Number(y1)).toBeGreaterThan(50)
  })
})
