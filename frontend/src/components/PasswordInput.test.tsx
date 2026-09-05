/**
 * The eye on a password field shows what was typed and hides it again; the
 * field itself stays a labelled input either way.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { PasswordInput } from './ui'

describe('PasswordInput', () => {
  it('hides the password until the eye is pressed', async () => {
    let value = 'secret-1'
    render(
      <>
        <label htmlFor="pw">Password</label>
        <PasswordInput id="pw" value={value} onChange={(next) => (value = next)} />
      </>,
    )
    const input = screen.getByLabelText('Password')
    expect(input).toHaveAttribute('type', 'password')
    await userEvent.click(screen.getByRole('button', { name: 'Show password' }))
    expect(input).toHaveAttribute('type', 'text')
    await userEvent.click(screen.getByRole('button', { name: 'Hide password' }))
    expect(input).toHaveAttribute('type', 'password')
    await userEvent.type(input, 'x')
    expect(value).toBe('secret-1x')
  })
})
