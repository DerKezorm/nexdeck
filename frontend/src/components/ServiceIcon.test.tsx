/**
 * A logo that failed to load must not poison the next one: while a name is
 * typed, "r" and "ra" have no logo, and "radarr" must still get its image.
 */
import { fireEvent, render } from '@testing-library/react'

import { ServiceIcon } from './ServiceIcon'

describe('ServiceIcon', () => {
  it('tries again with a new name after an earlier one failed', () => {
    const { container, rerender } = render(<ServiceIcon icon="ra" />)
    const image = container.querySelector('img')
    expect(image).not.toBeNull()
    fireEvent.error(image!)
    // The failed name shows the fallback box, not a broken image.
    expect(container.querySelector('img')).toBeNull()
    rerender(<ServiceIcon icon="radarr" />)
    expect(container.querySelector('img')?.getAttribute('src')).toContain('radarr.svg')
  })

  it('shows a symbol for lucide names and the box for unknown ones', () => {
    const { container, rerender } = render(<ServiceIcon icon="lucide:rss" />)
    expect(container.querySelector('svg')).not.toBeNull()
    expect(container.querySelector('img')).toBeNull()
    rerender(<ServiceIcon icon="" />)
    expect(container.querySelector('svg')).not.toBeNull()
  })
})
