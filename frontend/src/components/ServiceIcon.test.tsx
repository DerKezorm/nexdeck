/**
 * The icon of a service, and the symbol that is not one.
 *
 * A name like `book` is a drawn symbol, not a logo any collection has. Asked
 * for as a logo it answers 404 on every single board load, and the bookmarks
 * card shipped with two of them.
 */
import { render } from '@testing-library/react'

import { ServiceIcon } from './ServiceIcon'

describe('ServiceIcon', () => {
  it('draws a known symbol instead of fetching it', () => {
    const { container } = render(<ServiceIcon icon="book" />)
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('svg')).not.toBeNull()
  })

  it('draws a symbol written with the prefix as well', () => {
    const { container } = render(<ServiceIcon icon="lucide:activity" />)
    expect(container.querySelector('img')).toBeNull()
  })

  it('still fetches a real service logo', () => {
    const { container } = render(<ServiceIcon icon="radarr" />)
    const image = container.querySelector('img')
    expect(image?.getAttribute('src')).toContain('radarr')
  })

  it('falls back to a plain box for a name nobody knows', () => {
    const { container } = render(<ServiceIcon icon="" />)
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('svg')).not.toBeNull()
  })
})
