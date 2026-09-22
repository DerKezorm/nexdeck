/**
 * A colour theme on the page: one block for dark and one for light, the
 * accent left to the theme unless a colour of one's own was chosen, and the
 * same rule for what is hard to read as the server keeps.
 */
import { afterEach, describe, expect, it } from 'vitest'

import { applyAppearance, contrast, readTheme, themeCss, themeFile, weakSpots, type Appearance } from './appearance'

const THEME = {
  name: 'Test',
  dark: { bg: '#101010', surface: '#202020', accent: '#40c0a0', text: '#f0f0f0' },
  light: { bg: '#fafafa', accent: '#206050' },
}

const LOOK: Appearance = { preset: 'cyan', accent: '', css: '', colour: '#22d3ee', theme: THEME }

afterEach(() => {
  applyAppearance(null)
  document.documentElement.removeAttribute('data-theme')
})

describe('a theme as a style sheet', () => {
  it('writes dark so that it does not reach the light look', () => {
    const css = themeCss(THEME)
    expect(css).toContain(":root:not([data-theme='light']) {")
    expect(css).toContain(":root[data-theme='light'] {")
    expect(css).not.toMatch(/^:root \{/m)
  })

  it('makes the surfaces see-through and the accent its own shades', () => {
    const css = themeCss(THEME)
    expect(css).toContain('--nd-surface: rgba(32, 32, 32, 0.64);')
    expect(css).toContain('--nd-accent-soft: rgba(64, 192, 160, 0.14);')
    expect(css).toContain('--nd-accent-soft: rgba(32, 96, 80, 0.12);')
    expect(css).toContain('--nd-bg: #fafafa;')
  })

  it('leaves the accent to the theme, and a colour of ones own wins over it', () => {
    applyAppearance(LOOK)
    expect(document.getElementById('nexdeck-theme')?.textContent).toContain('--nd-accent: #40c0a0')
    expect(document.documentElement.style.getPropertyValue('--nd-accent')).toBe('')
    applyAppearance({ ...LOOK, accent: '#ff0066', colour: '#ff0066' })
    expect(document.documentElement.style.getPropertyValue('--nd-accent')).toBe('#ff0066')
    applyAppearance({ ...LOOK, theme: null })
    expect(document.getElementById('nexdeck-theme')).toBeNull()
    expect(document.documentElement.style.getPropertyValue('--nd-accent')).toBe('#22d3ee')
  })

  it('puts the theme before the operators style sheet, so the style sheet wins', () => {
    applyAppearance({ ...LOOK, css: '.card { border-radius: 0 }' })
    const tags = Array.from(document.head.querySelectorAll('style[id^="nexdeck-"]')).map((tag) => tag.id)
    expect(tags).toEqual(['nexdeck-theme', 'nexdeck-appearance'])
  })
})

describe('what is hard to read', () => {
  it('counts contrast the way the server does', () => {
    expect(contrast('#000000', '#ffffff')).toBeCloseTo(21)
    expect(contrast('#777777', '#ffffff')).toBeCloseTo(4.48, 2)
  })

  it('names the colours below 4.5:1 in each brightness', () => {
    const faint = { name: 'Faint', dark: { bg: '#111111', 'bg-elev': '#111111', surface: '#111111', text: '#444444' } }
    expect(weakSpots(faint)).toEqual([{ mode: 'dark', token: 'text', ratio: 1.94 }])
    expect(weakSpots(null)).toEqual([])
    // Just under the line counts, and so does a card the page does not show.
    expect(weakSpots({ name: 'Near', light: { bg: '#ffffff', text: '#777777' } }).map((spot) => spot.ratio)).toEqual([4.48])
    expect(weakSpots({ name: 'Card', dark: { bg: '#000000', surface: '#555555', text: '#999999' } }).map((spot) => spot.token)).toEqual(['text'])
  })
})

describe('a theme as a file', () => {
  it('goes out and comes back the same', () => {
    const read = readTheme(themeFile(THEME))
    expect(read).toEqual({ theme: THEME })
  })

  it('says what is wrong with something that is not one', () => {
    expect(readTheme('not json')).toEqual({ error: 'json' })
    expect(readTheme('{"dark": {}}')).toEqual({ error: 'shape' })
    expect(readTheme('{"name": "Only a name"}')).toEqual({ error: 'shape' })
  })
})
