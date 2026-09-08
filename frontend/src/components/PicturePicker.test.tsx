/**
 * The pictures of a picture card.
 *
 * ⚠️ It shipped as a text field with one line per picture, which is fine for
 * somebody who already has the addresses and useless for somebody with a photo
 * on their disk. Both go in the same list now, and a card filled in under the
 * old field keeps its pictures.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { PicturePicker, asPictures } from './PicturePicker'

const calls = vi.hoisted(() => ({ uploaded: [] as { path: string; name: string; fields: Record<string, string> }[] }))
vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  upload: vi.fn(async (path: string, file: File, fields: Record<string, string>) => {
    calls.uploaded.push({ path, name: file.name, fields })
    return { id: 4, filename: file.name, url: `/api/v1/assets/4/${file.name}` }
  }),
}))

function show(value: unknown) {
  const written: unknown[] = []
  render(<PicturePicker value={value} onChange={(next) => written.push(next)} label="Pictures" />)
  return written
}

describe('asPictures', () => {
  it('reads the list the picker writes', () => {
    expect(asPictures([{ url: '/a/1.png', caption: 'Rack' }])).toEqual([{ url: '/a/1.png', caption: 'Rack' }])
  })

  it('still reads the shape the old text field wrote', () => {
    // ⚠️ A card filled in before the picker existed must not lose its
    // pictures the day the field changed underneath it.
    expect(asPictures('/a/1.png | Rack\nhttps://example.com/x.jpg')).toEqual([
      { url: '/a/1.png', caption: 'Rack' },
      { url: 'https://example.com/x.jpg', caption: '' },
    ])
  })

  it('drops what is not a picture at all', () => {
    expect(asPictures([{ caption: 'no address' }, null, 'nonsense'])).toEqual([])
    expect(asPictures(undefined)).toEqual([])
  })
})

describe('PicturePicker', () => {
  beforeEach(() => {
    calls.uploaded.length = 0
  })

  it('uploads a file and puts it at the end of the list', async () => {
    const written = show([{ url: '/a/1.png', caption: 'First' }])
    await userEvent.upload(screen.getByLabelText('Upload a picture'), new File(['x'], 'rack.png', { type: 'image/png' }))

    await waitFor(() => expect(calls.uploaded).toHaveLength(1))
    expect(calls.uploaded[0]).toMatchObject({ path: '/assets', name: 'rack.png', fields: { kind: 'picture' } })
    await waitFor(() =>
      expect(written.at(-1)).toEqual([
        { url: '/a/1.png', caption: 'First' },
        { url: '/api/v1/assets/4/rack.png', caption: '' },
      ]),
    )
  })

  it('takes an address as well', async () => {
    const written = show([])
    await userEvent.type(screen.getByLabelText('Address of a picture'), 'https://example.com/x.jpg')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    expect(written.at(-1)).toEqual([{ url: 'https://example.com/x.jpg', caption: '' }])
  })

  it('refuses an address that would run instead of drawing', async () => {
    // ⚠️ The same rule as everywhere else a person types an address in: this
    // one ends up in a src attribute on the board.
    const written = show([])
    await userEvent.type(screen.getByLabelText('Address of a picture'), 'javascript:alert(1)')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    expect(written).toEqual([])
    expect(screen.getByRole('alert')).toHaveTextContent(/not an address/)
  })

  it('removes one', async () => {
    const written = show([{ url: '/a/1.png' }, { url: '/a/2.png' }])
    await userEvent.click(screen.getByRole('button', { name: 'Remove picture 1' }))
    expect(written.at(-1)).toEqual([{ url: '/a/2.png', caption: '' }])
  })

  it('takes a caption per picture, and only that one', async () => {
    // ⚠️ Two pictures, not one. With a single picture "write it to this one"
    // and "write it to all of them" look exactly the same.
    const written = show([{ url: '/a/1.png' }, { url: '/a/2.png' }])
    await userEvent.type(screen.getByLabelText('Caption of picture 1'), 'R')
    expect(written.at(-1)).toEqual([{ url: '/a/1.png', caption: 'R' }, { url: '/a/2.png', caption: '' }])
  })

  it('sorts by the handle, with the keyboard too', async () => {
    const written = show([{ url: '/a/1.png' }, { url: '/a/2.png' }])
    const handle = screen.getByRole('button', { name: 'Move picture 1' })
    handle.focus()
    await userEvent.keyboard('{ArrowDown}')
    await waitFor(() => expect(written.at(-1)).toEqual([{ url: '/a/2.png', caption: '' }, { url: '/a/1.png', caption: '' }]))
  })
})
