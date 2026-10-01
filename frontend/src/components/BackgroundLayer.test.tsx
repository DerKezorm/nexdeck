import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { BackgroundLayer, skyAt, STARS } from './BackgroundLayer'

describe('the grounds that move', () => {
  it('draws the drifting aurora as clouds of its own', () => {
    render(<BackgroundLayer background={{ kind: 'bundled', value: 'flow' }} />)
    expect(screen.getByTestId('background-flow').children).toHaveLength(3)
  })

  it('draws the stars as a few layers, not a hundred elements', () => {
    render(<BackgroundLayer background={{ kind: 'bundled', value: 'stars' }} />)
    const layers = screen.getByTestId('background-stars').children
    expect(layers.length).toBeLessThanOrEqual(3)
    // jsdom drops a shadow list this long, so the list itself is what is read.
    expect(STARS[0].split('rgba').length - 1).toBe(70)
  })

  it('follows the hour, with stars at night only', () => {
    render(<BackgroundLayer background={{ kind: 'bundled', value: 'daytime' }} />)
    const sky = screen.getByTestId('background-sky')
    const hour = Number(sky.dataset.hour)
    expect(hour).toBe(new Date().getHours())
    expect(Boolean(screen.queryByTestId('background-stars'))).toBe(skyAt(hour).night)
  })

  it('keeps an uploaded picture, whatever name came with it', () => {
    render(<BackgroundLayer background={{ kind: 'upload', value: '/api/v1/assets/1/stars.png' }} />)
    expect(screen.queryByTestId('background-stars')).toBeNull()
  })
})

describe('the sky at an hour', () => {
  it('is night late and early, and day around noon', () => {
    expect(skyAt(23).night).toBe(true)
    expect(skyAt(3).night).toBe(true)
    expect(skyAt(12).night).toBe(false)
    expect(skyAt(6).ground).not.toBe(skyAt(12).ground)
    expect(skyAt(18).ground).not.toBe(skyAt(12).ground)
  })
})

describe('the room when a card is down', () => {
  it('fades the red in and out rather than adding and removing it', () => {
    const { rerender } = render(<BackgroundLayer alarm={false} />)
    expect(screen.getByTestId('background-alarm').dataset.on).toBe('false')
    rerender(<BackgroundLayer alarm />)
    expect(screen.getByTestId('background-alarm').dataset.on).toBe('true')
    expect(screen.getByTestId('background-alarm').style.opacity).toBe('1')
  })
})
