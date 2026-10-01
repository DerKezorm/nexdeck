import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { WidgetData } from '../lib/types'
import { FlowCard, runSeconds } from './FlowCard'

const card = (flow: Record<string, number | null>) => ({ status: 'ok', meta: { flow } }) as unknown as WidgetData

describe('the energy flow', () => {
  it('runs each line the way the power goes', () => {
    render(<FlowCard data={card({ solar: 5.1, home: 0.6, grid: -1.2, battery: -2.1, battery_soc: 64, car: 7.4 })} />)
    expect(screen.getByTestId('flow-solar').dataset.way).toBe('on')
    // Feeding in runs away from the house, and so does charging the battery.
    expect(screen.getByTestId('flow-grid').dataset.way).toBe('back')
    expect(screen.getByTestId('flow-battery').dataset.way).toBe('back')
    expect(screen.getByTestId('flow-car').dataset.way).toBe('on')
  })

  it('draws nothing running on an idle line, and leaves out what the house does not have', () => {
    render(<FlowCard data={card({ solar: 0, home: 0.6, grid: 0.6, battery: null, car: null })} />)
    expect(screen.queryByTestId('flow-solar')).toBeNull()
    expect(screen.getByTestId('flow-grid')).toBeInTheDocument()
    expect(screen.queryByTestId('flow-battery')).toBeNull()
    expect(screen.queryByTestId('flow-car')).toBeNull()
  })

  it('runs faster the more power there is, within bounds', () => {
    expect(runSeconds(7)).toBeLessThan(runSeconds(1))
    expect(runSeconds(100)).toBe(0.5)
    expect(runSeconds(0.1)).toBeLessThanOrEqual(3)
  })
})
