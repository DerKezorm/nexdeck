/**
 * The picture dialog draws the board with showcase mode on for that one
 * picture, and leaves the setting of the browser as it was.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useShowcase } from '../lib/showcase'
import { PictureDialog } from './PictureDialog'

const seen = vi.hoisted(() => ({ showcase: [] as boolean[] }))
vi.mock('../lib/boardPicture', async (load) => {
  const real = await load<typeof import('../lib/boardPicture')>()
  return {
    ...real,
    painted: async () => undefined,
    boardCanvas: vi.fn(async () => {
      seen.showcase.push(useShowcase.getState().on)
      return document.createElement('canvas')
    }),
    // jsdom draws nothing: a canvas that hands back a picture is enough.
    framed: () => ({ toDataURL: () => 'data:image/png;base64,AAAA', toBlob: () => undefined }),
  }
})

afterEach(() => {
  seen.showcase.length = 0
  useShowcase.setState({ on: false })
  document.querySelector('[data-board-page]')?.remove()
})

function page() {
  const element = document.createElement('div')
  element.setAttribute('data-board-page', '')
  document.body.append(element)
}

describe('saving the board as a picture', () => {
  it('takes the picture in showcase mode and switches it back off afterwards', async () => {
    page()
    useShowcase.setState({ on: false })
    render(<PictureDialog open onClose={() => undefined} boardName="Home" />)
    await waitFor(() => expect(screen.getByTestId('picture-preview')).toBeInTheDocument())
    expect(seen.showcase).toEqual([true])
    expect(useShowcase.getState().on).toBe(false)
  })

  it('leaves showcase mode on for a browser that had it on', async () => {
    page()
    useShowcase.setState({ on: true })
    render(<PictureDialog open onClose={() => undefined} boardName="Home" />)
    await waitFor(() => expect(screen.getByTestId('picture-preview')).toBeInTheDocument())
    expect(useShowcase.getState().on).toBe(true)
  })

  it('says so when there is no board to draw', async () => {
    render(<PictureDialog open onClose={() => undefined} boardName="Home" />)
    await waitFor(() => expect(screen.getByText(/could not be drawn/i)).toBeInTheDocument())
  })
})
