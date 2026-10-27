/**
 * The icon of a service, and the symbol that is not one.
 *
 * A name like `book` is a drawn symbol, not a logo any collection has. Asked
 * for as a logo it answers 404 on every single board load, and the bookmarks
 * card shipped with two of them.
 */
import { fireEvent, render } from '@testing-library/react'

import { serviceLogo } from '../lib/format'
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

  it('asks the service for its own logo when there is no icon, and gives up after that', () => {
    const { container } = render(<ServiceIcon icon="" fallback="/api/v1/widgets/7/favicon" />)
    const image = container.querySelector('img')!
    expect(image.getAttribute('src')).toBe('/api/v1/widgets/7/favicon')
    fireEvent.error(image)
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('svg')).not.toBeNull()
  })

  it('asks for it when no collection has the named logo, and not before', () => {
    const { container } = render(<ServiceIcon icon="my-own-wiki" fallback="/api/v1/widgets/7/favicon" />)
    const named = container.querySelector('img')!
    expect(named.getAttribute('src')).toContain('my-own-wiki')
    fireEvent.error(named)
    expect(container.querySelector('img')?.getAttribute('src')).toBe('/api/v1/widgets/7/favicon')
  })
})

describe('serviceLogo', () => {
  it('is asked only for a card with an address of its own or of its service', () => {
    expect(serviceLogo({ id: 7, link: 'http://192.0.2.10:8080/wiki' })).toBe('/api/v1/widgets/7/favicon')
    expect(serviceLogo({ id: 7, link: '', service_link: 'https://wiki.example.com' })).toBe('/api/v1/widgets/7/favicon')
    expect(serviceLogo({ id: 7, link: '' })).toBeNull()
    expect(serviceLogo({ id: 7, link: 'javascript:alert(1)' })).toBeNull()
    expect(serviceLogo({ id: -3, link: 'https://example.com' })).toBeNull()
  })
})
