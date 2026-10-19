/**
 * The big number of a value card stays on one line. On a card two columns wide
 * "535.7 KB/s" broke after the slash; its size now follows how many figures
 * wide it is, so a short reading keeps its full size on the same card.
 */
import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { DEMO_VIEWS } from '../demo/board'
import type { WidgetData, WidgetView } from '../lib/types'
import { renderWidget, valueWidth } from './renderers'

describe('the big number of a value card', () => {
  it('counts its figures and half its unit', () => {
    expect(valueWidth('535.7 KB/s')).toBe(10)
    expect(valueWidth(899, 'Mbps')).toBe(5.5)
    expect(valueWidth(3)).toBe(3)
    expect(valueWidth(undefined)).toBe(3)
  })

  it('carries that width and the class that keeps it on one line', () => {
    const data = { status: 'ok', primary: { label: 'Rate', value: '535.7 KB/s' } } as WidgetData
    const view = { ...DEMO_VIEWS[0], id: 21, renderer: 'value' } as WidgetView
    const { container } = render(<>{renderWidget({ widget: view, data })}</>)
    const number = container.querySelector('.value-number') as HTMLElement
    expect(number).not.toBeNull()
    expect(number.style.getPropertyValue('--chars')).toBe('10')
    expect(number.className).not.toContain('text-[30px]')
  })
})
