/**
 * 1984: chosen, it marks the page and fetches its sheet and its pixel type;
 * not chosen, nothing of it is fetched at all; it wins over a board's own
 * style; and it travels with a shared look.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

const fetched = vi.hoisted(() => ({ sheet: 0 }))
vi.mock('../styles/retro.css', () => {
  fetched.sheet += 1
  return {}
})

import { applyAppearance, BOARD_STYLES, lookFile, readLook, setBoardStyle, shownStyle, useLook } from './appearance'
import { FONTS } from './fonts'
import { pixelSize, retroOf } from './retro'

const root = () => document.documentElement

afterEach(() => {
  setBoardStyle(null)
  applyAppearance(null)
})

describe('1984', () => {
  it('fetches nothing of itself while another look is shown', async () => {
    const pixel = FONTS.find((font) => font.key === 'pixel')!
    const original = pixel.load
    const load = vi.fn(async () => undefined)
    pixel.load = load
    try {
      applyAppearance({ preset: 'cyan', accent: '', css: '', colour: '#22d3ee', card_style: 'calm' })
      setBoardStyle('flat')
      await new Promise((resolve) => setTimeout(resolve, 0))
      expect(fetched.sheet).toBe(0)
      expect(load).not.toHaveBeenCalled()
      expect(root().dataset.rStatus).toBeUndefined()
      expect(document.getElementById('nd-r-patterns')).toBeNull()
    } finally {
      pixel.load = original
    }
  })

  it('marks the page with its choices and fetches its sheet and its type once chosen', async () => {
    applyAppearance({ preset: 'cyan', accent: '', css: '', colour: '#22d3ee', card_style: 'window', retro: { status: 'pattern', icons: 'mono', desk: 'weave', type: 'all' } })
    await vi.waitFor(() => expect(fetched.sheet).toBe(1))
    expect(root().dataset.cards).toBe('window')
    expect([root().dataset.rStatus, root().dataset.rIcons, root().dataset.rDesk, root().dataset.rType]).toEqual(['pattern', 'mono', 'weave', 'all'])
    expect(root().style.getPropertyValue('--r-px')).toBe('1px')
    expect(document.getElementById('nd-r-patterns')?.querySelector('#nd-r-dither')).not.toBeNull()
    // And off again: no mark of it is left behind for the next look.
    applyAppearance({ preset: 'cyan', accent: '', css: '', colour: '#22d3ee', card_style: 'glass' })
    expect(root().dataset.cards).toBeUndefined()
    expect(root().dataset.rStatus).toBeUndefined()
    expect(document.getElementById('nd-r-patterns')).toBeNull()
  })

  it('wins over a board that has a style of its own, and a board cannot choose it alone', () => {
    applyAppearance({ preset: 'cyan', accent: '', css: '', colour: '#22d3ee', card_style: 'window' })
    setBoardStyle('neon')
    expect(shownStyle(useLook.getState())).toBe('window')
    expect(root().dataset.cards).toBe('window')
    applyAppearance({ preset: 'cyan', accent: '', css: '', colour: '#22d3ee', card_style: 'glass' })
    setBoardStyle('window')
    expect(shownStyle(useLook.getState())).toBe('glass')
    expect(BOARD_STYLES).not.toContain('window')
  })

  it('keeps unknown choices out, each falling back on the approved mock-up', () => {
    expect(retroOf({ status: 'blink', desk: 'grey' })).toEqual({ status: 'symbol', icons: 'colour', desk: 'grey', type: 'titles' })
    expect(retroOf('pattern')).toEqual({ status: 'symbol', icons: 'colour', desk: 'dither', type: 'titles' })
  })

  it('draws its patterns in whole screen pixels at every zoom', () => {
    // 100 % and 125 %: one screen pixel; 150 % and 200 %: two.
    expect(pixelSize(1)).toBe(1)
    expect(pixelSize(1.25)).toBeCloseTo(0.8)
    expect(pixelSize(1.5) * 1.5).toBe(2)
    expect(pixelSize(2)).toBe(1)
  })

  it('travels in a shared look with its choices', () => {
    const text = lookFile({ preset: 'cyan', accent: '', css: '', colour: '#22d3ee', card_style: 'window', radius: 0, gap: 14, retro: { status: 'tint' } })
    const read = readLook(text)
    expect('look' in read && read.look.card_style).toBe('window')
    expect('look' in read && read.look.retro).toEqual({ status: 'tint', icons: 'colour', desk: 'dither', type: 'titles' })
  })
})
