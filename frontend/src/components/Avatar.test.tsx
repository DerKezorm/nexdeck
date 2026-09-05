/**
 * The picture when there is one, the initials while there is none. Both keep
 * the size they were asked for, so the bar never jumps when one arrives.
 */
import { render } from '@testing-library/react'

import { Avatar } from './Avatar'

describe('Avatar', () => {
  it('shows the initials of a name without a picture', () => {
    const { container } = render(<Avatar name="Ada Lovelace" size={40} />)
    expect(container.textContent).toBe('AL')
    expect(container.querySelector('img')).toBeNull()
    expect(container.firstElementChild).toHaveStyle({ width: '40px', height: '40px' })
  })

  it('takes the first two letters of a single name, and copes with none', () => {
    expect(render(<Avatar name="ada" />).container.textContent).toBe('AD')
    expect(render(<Avatar name="   " />).container.textContent).toBe('?')
  })

  it('shows the picture once the account has one', () => {
    const { container } = render(<Avatar url="/api/v1/avatars/abc.png" name="Ada Lovelace" size={28} />)
    const image = container.querySelector('img')
    expect(image?.getAttribute('src')).toBe('/api/v1/avatars/abc.png')
    expect(image).toHaveAttribute('width', '28')
    // Empty alt text: the picture repeats the name next to it, nothing more.
    expect(image).toHaveAttribute('alt', '')
    expect(container.textContent).toBe('')
  })
})
