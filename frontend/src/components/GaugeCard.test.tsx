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

describe('the arc itself', () => {
  /** The filled arc of a card at this share, as SVG path data. */
  function filledArc(share: number): string {
    const { container, unmount } = draw({
      status: 'ok',
      primary: { label: 'Memory', value: share, unit: '%' },
      meta: { renderer: 'gauge', gauge: { share } },
    } as WidgetData)
    const paths = container.querySelectorAll('path')
    const arc = paths[1]?.getAttribute('d') ?? ''
    unmount()
    return arc
  }

  /** The large-arc flag SVG was handed: 0 draws the short way, 1 the long way. */
  function largeFlag(share: number): number {
    const match = /A [\d.]+ [\d.]+ 0 (\d)/.exec(filledArc(share))
    return Number(match?.[1])
  }

  it('goes the short way round below two thirds and the long way above', () => {
    /**
     * ⚠️ The face spans 270°, not 360, so the flag flips at two thirds of the
     * way and not at half. Read as half, every value between 50% and 67% was
     * drawn the long way round: a ring with a bite out of the wrong side.
     */
    expect(largeFlag(10)).toBe(0)
    expect(largeFlag(53)).toBe(0)
    expect(largeFlag(66)).toBe(0)
    expect(largeFlag(68)).toBe(1)
    expect(largeFlag(100)).toBe(1)
  })

  it('flips exactly once, and where the arc passes half a turn', () => {
    // From 2 upwards: a share of 0 draws no filled arc at all, which the next
    // test is about.
    const shares = [...Array(99).keys()].map((n) => n + 2)
    const flipping = shares.filter((share) => largeFlag(share) !== largeFlag(share - 1))
    expect(flipping, 'one change, at 180 degrees of the 270 the face spans').toEqual([67])
  })

  it('draws no filled arc at all when there is nothing to fill', () => {
    const { container } = draw({
      status: 'ok',
      primary: { label: 'Memory', value: 0, unit: '%' },
      meta: { renderer: 'gauge', gauge: { share: 0 } },
    } as WidgetData)
    expect(container.querySelectorAll('path')).toHaveLength(1)
  })

  it('ends where the needle points', () => {
    /** A filled arc that stops somewhere else than the needle is two answers. */
    const { container } = draw({
      status: 'ok',
      primary: { label: 'Memory', value: 53, unit: '%' },
      meta: { renderer: 'gauge', gauge: { share: 53 } },
    } as WidgetData)
    const arc = container.querySelectorAll('path')[1].getAttribute('d')!
    const [, ex, ey] = /A [\d.]+ [\d.]+ 0 \d 1 ([\d.-]+) ([\d.-]+)/.exec(arc)!.map(Number) as unknown as number[]
    const angleOfEnd = (Math.atan2(Number(ey) - 50, Number(ex) - 50) * 180) / Math.PI
    const needle = needleShare(container)
    const asShare = (((angleOfEnd < 135 ? angleOfEnd + 360 : angleOfEnd) - 135) / 270) * 100
    expect(asShare).toBeCloseTo(needle, 0)
  })
})
