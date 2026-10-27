/** The four answers, and with "by the clock" the two times, handed on only when they make a day. */
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { ThemePlanField } from './ThemePlanField'

describe('ThemePlanField', () => {
  it('shows the two times only by the clock', async () => {
    const changed = vi.fn()
    const { rerender } = render(<ThemePlanField id="t" value={{ theme: 'dark' }} onChange={changed} />)
    expect(screen.queryByLabelText('Light from')).toBeNull()
    await userEvent.selectOptions(screen.getByLabelText('Appearance'), 'schedule')
    expect(changed).toHaveBeenLastCalledWith({ theme: 'schedule', light_from: '07:00', dark_from: '20:00' })
    rerender(<ThemePlanField id="t" value={{ theme: 'schedule', light_from: '07:00', dark_from: '20:00' }} onChange={changed} />)
    expect(screen.getByLabelText('Light from')).toHaveValue('07:00')
    expect(screen.getByLabelText('Dark from')).toHaveValue('20:00')
  })

  it('hands on a new time, and not one that leaves no day', () => {
    const changed = vi.fn()
    render(<ThemePlanField id="t" value={{ theme: 'schedule', light_from: '07:00', dark_from: '20:00' }} onChange={changed} />)
    fireEvent.change(screen.getByLabelText('Dark from'), { target: { value: '21:30' } })
    expect(changed).toHaveBeenLastCalledWith({ theme: 'schedule', light_from: '07:00', dark_from: '21:30' })
    changed.mockClear()
    fireEvent.change(screen.getByLabelText('Light from'), { target: { value: '20:00' } })
    fireEvent.change(screen.getByLabelText('Light from'), { target: { value: '' } })
    expect(changed).not.toHaveBeenCalled()
  })
})
