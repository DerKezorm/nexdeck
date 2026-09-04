/**
 * The switch is usable by a screen reader: it has a role and a name.
 * A ``<label for>`` pointing at a div names nothing; ``aria-labelledby`` does.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { Switch } from './ui'

describe('Switch', () => {
  it('has an accessible name and toggles', async () => {
    let value = false
    const { rerender } = render(<Switch checked={value} onChange={(v) => (value = v)} label="Demo mode" description="Fake data" />)
    const control = screen.getByRole('switch', { name: 'Demo mode' })
    expect(control).toHaveAttribute('aria-checked', 'false')
    await userEvent.click(control)
    expect(value).toBe(true)
    rerender(<Switch checked={value} onChange={(v) => (value = v)} label="Demo mode" />)
    expect(screen.getByRole('switch', { name: 'Demo mode' })).toHaveAttribute('aria-checked', 'true')
  })
})
