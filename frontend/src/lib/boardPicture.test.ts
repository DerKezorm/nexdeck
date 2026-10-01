import { describe, expect, it } from 'vitest'

import { fileName, leftOut } from './boardPicture'

describe('the board as a picture', () => {
  it('names the file after the board and the day', () => {
    expect(fileName('Home', new Date('2026-10-01T20:00:00Z'))).toBe('nexdeck-home-2026-10-01.png')
    expect(fileName('Media & Network!', new Date('2026-10-01T20:00:00Z'))).toBe('nexdeck-media-network-2026-10-01.png')
    expect(fileName('???', new Date('2026-10-01T20:00:00Z'))).toBe('nexdeck-board-2026-10-01.png')
  })

  it('leaves out the bars, the floating buttons, dialogs and passing notices', () => {
    const make = (html: string) => {
      const box = document.createElement('div')
      box.innerHTML = html
      return box.firstElementChild as Element
    }
    expect(leftOut(make('<header data-no-picture></header>'))).toBe(true)
    expect(leftOut(make('<div class="card-controls glass"></div>'))).toBe(true)
    expect(leftOut(make('<div role="dialog"></div>'))).toBe(true)
    expect(leftOut(make('<div role="status"></div>'))).toBe(true)
    expect(leftOut(make('<section class="card glass"></section>'))).toBe(false)
    expect(leftOut(document.createTextNode('text'))).toBe(false)
  })
})
