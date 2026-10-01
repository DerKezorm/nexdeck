import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { WidgetData } from '../lib/types'
import { HeatmapCard, shade, weeks } from './HeatmapCard'

describe('days as squares', () => {
  it('starts the first week on its weekday, Monday on top', () => {
    // 2026-10-01 is a Thursday: three empty squares above it.
    const columns = weeks([['2026-10-01', 1], ['2026-10-02', 2], ['2026-10-05', 3]])
    expect(columns[0].slice(0, 4)).toEqual([null, null, null, ['2026-10-01', 1]])
    expect(columns).toHaveLength(1)
  })

  it('shades by the share of the busiest day, in four steps, and nothing for an empty day', () => {
    expect(shade(0, 10)).toBe(0)
    expect(shade(1, 10)).toBe(1)
    expect(shade(5, 10)).toBe(2)
    expect(shade(10, 10)).toBe(4)
  })

  it('draws a square per day and names the busiest', () => {
    const days: [string, number][] = Array.from({ length: 14 }, (_, index) => [`2026-09-${String(index + 7).padStart(2, '0')}`, index === 5 ? 9 : 1])
    const data = { status: 'ok', primary: { label: 'Plays', value: 22 }, meta: { heatmap: { days } } } as unknown as WidgetData
    render(<HeatmapCard data={data} />)
    expect(screen.getByTestId('heatmap').querySelectorAll('[data-shade]')).toHaveLength(14)
    expect(screen.getByTestId('heatmap').querySelectorAll('[data-shade="4"]')).toHaveLength(1)
  })
})
