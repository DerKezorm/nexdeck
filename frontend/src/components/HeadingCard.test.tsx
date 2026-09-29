/**
 * The heading card: a title, a line, or both, drawn from the card's own
 * options and without the glass ground every other card has.
 */
import { render, screen } from '@testing-library/react'

import type { WidgetView } from '../lib/types'
import { WidgetCard } from './WidgetCard'

function heading(options: Record<string, unknown> = {}, title = 'Network'): WidgetView {
  return { id: 7, kind: 'core.heading', title, icon: '', link: '', renderer: 'heading', options, integration_id: null, refresh_seconds: null, client_only: true }
}

describe('the heading card', () => {
  it('shows its title as a heading with a line, and no card header or dot', () => {
    const { container } = render(<WidgetCard widget={heading()} data={undefined} />)
    expect(screen.getByRole('heading', { name: 'Network', level: 2 })).toBeTruthy()
    expect(screen.getAllByTestId('heading-line')).toHaveLength(1)
    expect(container.querySelector('header')).toBeNull()
    expect(container.querySelector('.dot')).toBeNull()
    expect(container.querySelector('section')?.classList.contains('card-plain')).toBe(true)
  })

  it('is a plain divider with the line alone', () => {
    render(<WidgetCard widget={heading({ style: 'line' })} data={undefined} />)
    expect(screen.queryByRole('heading')).toBeNull()
    expect(screen.getAllByTestId('heading-line')).toHaveLength(1)
  })

  it('leaves the line out when asked, and draws one on each side when centred', () => {
    const { rerender } = render(<WidgetCard widget={heading({ style: 'title' })} data={undefined} />)
    expect(screen.getByRole('heading', { name: 'Network' })).toBeTruthy()
    expect(screen.queryAllByTestId('heading-line')).toHaveLength(0)
    rerender(<WidgetCard widget={heading({ align: 'center' })} data={undefined} />)
    expect(screen.getAllByTestId('heading-line')).toHaveLength(2)
  })

  it('draws a divider when the title is emptied', () => {
    render(<WidgetCard widget={heading({}, '  ')} data={undefined} />)
    expect(screen.queryByRole('heading')).toBeNull()
    expect(screen.getAllByTestId('heading-line')).toHaveLength(1)
  })

  it('takes the colour for text and line', () => {
    render(<WidgetCard widget={heading({ colour: '#ff8800' })} data={undefined} />)
    expect(screen.getByRole('heading', { name: 'Network' }).style.color).toBe('rgb(255, 136, 0)')
    expect(screen.getByTestId('heading-line').style.borderColor).toBe('rgb(255, 136, 0)')
  })
})
