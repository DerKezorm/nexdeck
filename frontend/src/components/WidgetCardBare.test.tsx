/**
 * A card may leave off its head and its frame (its settings, Look): it then
 * stands free on the board, says in the corner when it is not well, and keeps
 * an outline and a grip while the board is arranged.
 */
import { render, screen } from '@testing-library/react'

import { DEMO_DATA, DEMO_VIEWS } from '../demo/board'
import type { WidgetView } from '../lib/types'
import { WidgetCard } from './WidgetCard'

const base = DEMO_VIEWS.find((one) => one.renderer === 'value')!
const card = (options: Record<string, unknown>): WidgetView => ({ ...base, options: { ...base.options, ...options } })
const frame = (container: HTMLElement) => container.querySelector('section.card')!

describe('a card without its head or its frame', () => {
  it('draws its head as always unless told otherwise', () => {
    const { container } = render(<WidgetCard widget={card({})} data={DEMO_DATA[base.id]} />)
    expect(screen.getByRole('heading', { name: base.title })).toBeInTheDocument()
    expect(frame(container)).not.toHaveClass('card-plain')
    expect(screen.queryByTestId('card-grip')).toBeNull()
  })

  it('leaves the head off, and the frame', () => {
    const { container } = render(<WidgetCard widget={card({ hide_head: true, frameless: true })} data={DEMO_DATA[base.id]} />)
    expect(screen.queryByRole('heading', { name: base.title })).toBeNull()
    expect(frame(container)).toHaveClass('card-plain')
    expect(frame(container)).toHaveAttribute('aria-label', base.title)
  })

  it('says in the corner when it is not well, and only then', () => {
    const data = DEMO_DATA[base.id]
    const { rerender } = render(<WidgetCard widget={card({ hide_head: true })} data={data} />)
    expect(screen.queryByTestId('card-corner-dot')).toBeNull()
    rerender(<WidgetCard widget={card({ hide_head: true, show_findings: true })} data={{ ...data, status: 'bad' }} />)
    expect(screen.getByTestId('card-corner-dot')).toHaveAttribute('data-status', 'bad')
  })

  it('keeps an outline and a grip while the board is arranged', () => {
    const { container } = render(<WidgetCard widget={card({ frameless: true })} data={DEMO_DATA[base.id]} editing onSettings={() => undefined} />)
    expect(frame(container)).toHaveClass('is-editing')
    expect(screen.getByTestId('card-grip')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Widget settings' })).toBeInTheDocument()
  })
})
