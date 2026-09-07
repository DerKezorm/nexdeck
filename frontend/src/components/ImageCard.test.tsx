/**
 * One picture, or a few of them one after another.
 *
 * ⚠️ The addresses are typed in by hand, exactly like a bookmark's, so the
 * same rule applies: what would run instead of drawing never reaches the src.
 */
import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ImageCard } from './ImageCard'
import type { WidgetData, WidgetView } from '../lib/types'

const WIDGET = { id: 1, title: 'Rack', renderer: 'image' } as unknown as WidgetView

function show(items: { url: string; title?: string }[], meta: Record<string, unknown> = {}) {
  return render(<ImageCard widget={WIDGET} data={{ items, meta } as unknown as WidgetData} />)
}

describe('ImageCard', () => {
  it('draws one picture with its caption', () => {
    show([{ url: '/api/v1/assets/3/rack.png', title: 'Server rack' }])
    const picture = screen.getByTestId('picture')
    expect(picture).toHaveAttribute('src', '/api/v1/assets/3/rack.png')
    expect(picture).toHaveAttribute('alt', 'Server rack')
    expect(screen.getByText('Server rack')).toBeInTheDocument()
  })

  it('leaves out an address that would run instead of drawing', () => {
    show([{ url: 'javascript:alert(1)', title: 'Bad' }, { url: 'https://example.com/ok.png' }])
    const pictures = screen.getAllByTestId('picture')
    expect(pictures).toHaveLength(1)
    expect(pictures[0]).toHaveAttribute('src', 'https://example.com/ok.png')
  })

  it('does not invent a description for a picture without a caption', () => {
    // ⚠️ An empty alt says "decoration" and is right here. A made-up one,
    // the file name for instance, is read aloud as if it meant something.
    show([{ url: '/a/1.png' }])
    expect(screen.getByTestId('picture')).toHaveAttribute('alt', '')
  })

  it('says so when there is nothing to show', () => {
    show([])
    expect(screen.getByText(/No pictures yet/)).toBeInTheDocument()
  })

  describe('as a slideshow', () => {
    beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }))
    afterEach(() => vi.useRealTimers())

    it('moves on by itself', () => {
      show([{ url: '/a/1.png' }, { url: '/a/2.png' }], { every: 4 })
      expect(screen.getByTestId('picture')).toHaveAttribute('src', '/a/1.png')
      act(() => void vi.advanceTimersByTime(4000))
      expect(screen.getByTestId('picture')).toHaveAttribute('src', '/a/2.png')
      // And round again, rather than stopping at the end.
      act(() => void vi.advanceTimersByTime(4000))
      expect(screen.getByTestId('picture')).toHaveAttribute('src', '/a/1.png')
    })

    it('stands still at zero seconds', () => {
      show([{ url: '/a/1.png' }, { url: '/a/2.png' }], { every: 0 })
      act(() => void vi.advanceTimersByTime(60_000))
      expect(screen.getByTestId('picture')).toHaveAttribute('src', '/a/1.png')
    })

    it('stands still with one picture, whatever the interval says', () => {
      show([{ url: '/a/1.png' }], { every: 2 })
      act(() => void vi.advanceTimersByTime(20_000))
      expect(screen.getByTestId('picture')).toHaveAttribute('src', '/a/1.png')
      // And says nothing about pressing on, because there is nowhere to go.
      expect(screen.queryByRole('button')).toBeNull()
    })
  })

  it('moves on when pressed, so a wall display need not be waited out', async () => {
    show([{ url: '/a/1.png' }, { url: '/a/2.png' }], { every: 0 })
    await userEvent.click(screen.getByRole('button'))
    expect(screen.getByTestId('picture')).toHaveAttribute('src', '/a/2.png')
  })

  it('moves on from the keyboard as well', async () => {
    show([{ url: '/a/1.png' }, { url: '/a/2.png' }], { every: 0 })
    screen.getByRole('button').focus()
    await userEvent.keyboard('{Enter}')
    expect(screen.getByTestId('picture')).toHaveAttribute('src', '/a/2.png')
  })

  it('crops or fits as it was told', () => {
    const { rerender } = show([{ url: '/a/1.png' }], { fit: 'cover' })
    expect(screen.getByTestId('picture')).toHaveStyle({ objectFit: 'cover' })
    rerender(<ImageCard widget={WIDGET} data={{ items: [{ url: '/a/1.png' }], meta: { fit: 'contain' } } as unknown as WidgetData} />)
    expect(screen.getByTestId('picture')).toHaveStyle({ objectFit: 'contain' })
  })
})
