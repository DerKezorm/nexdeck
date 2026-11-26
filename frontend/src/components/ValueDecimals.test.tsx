/**
 * Issue #78: a card set to a number of decimals shows them. A rate of 0.07
 * per kWh read 0.1, because every number below 10 was written with one.
 */
import { render, screen } from '@testing-library/react'

import type { WidgetData, WidgetView } from '../lib/types'
import { ValueCard } from './renderers'

const VIEW = { id: 1, renderer: 'value' } as unknown as WidgetView

describe('ValueCard with decimals', () => {
  it('writes the number with the decimals the card was set to', () => {
    render(<ValueCard widget={VIEW} data={{ status: 'ok', primary: { label: 'Rate', value: 0.07, unit: 'GBP/kWh', decimals: 2 } } as WidgetData} />)
    expect(screen.getByText(/0\.07/)).toBeInTheDocument()
  })

  it('reads as before without them', () => {
    render(<ValueCard widget={VIEW} data={{ status: 'ok', primary: { label: 'Rate', value: 0.07, unit: 'GBP/kWh' } } as WidgetData} />)
    expect(screen.getByText(/0\.1/)).toBeInTheDocument()
    expect(screen.queryByText(/0\.07/)).toBeNull()
  })
})
