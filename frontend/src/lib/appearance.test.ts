import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { accentVariables, applyAppearance, channels, contrast, darker, lookFile, OWN_PALETTES, onAccent, readableAccent, readLook, useLook } from './appearance'
import { followTheme } from './themeMode'

describe('the accent colour', () => {
  it('reads the three parts of a colour', () => {
    expect(channels('#22d3ee')).toEqual([34, 211, 238])
  })

  it('refuses anything that is not a colour', () => {
    for (const text of ['', 'red', 'rgb(1,2,3)', '#fff', '#22d3e', 'javascript:1']) {
      expect(channels(text)).toBeNull()
    }
  })

  it('makes a darker shade for the pressed state', () => {
    expect(darker('#22d3ee')).toBe('#1cadc3')
    expect(darker('#000000')).toBe('#000000')
  })

  it('turns one colour into the four variables the interface uses', () => {
    expect(accentVariables('#22d3ee')).toEqual({
      '--nd-accent': '#22d3ee',
      '--nd-on-accent': '#041016',
      '--nd-accent-strong': '#1cadc3',
      '--nd-accent-soft': 'rgba(34, 211, 238, 0.14)',
      '--nd-accent-glow': 'rgba(34, 211, 238, 0.35)',
      '--nd-aurora-1': 'rgba(34, 211, 238, 0.16)',
    })
  })

  it('puts the ink that reads on the accent, not the white of the light theme, over a light colour', () => {
    // A fresh installation: preset cyan, light theme. White on #22d3ee is 1.7:1.
    for (const colour of ['#22d3ee', '#a78bfa', '#34d399', '#fbbf24', '#fb7185', '#38bdf8', '#94a3b8']) {
      expect(contrast(colour, onAccent(colour)), colour).toBeGreaterThanOrEqual(4.5)
    }
    expect(onAccent('#0e7490')).toBe('#ffffff')
    expect(onAccent('#22d3ee')).toBe('#041016')
  })

  it('hands back nothing for a colour it cannot read, so the shipped one stays', () => {
    expect(accentVariables('nonsense')).toEqual({})
  })
})

describe('painting it on', () => {
  beforeEach(() => {
    document.documentElement.removeAttribute('style')
    document.getElementById('nexdeck-appearance')?.remove()
  })

  it('sets the variables and adds the style sheet', () => {
    applyAppearance({ preset: 'violet', accent: '', colour: '#a78bfa', css: '.card { border-radius: 4px; }' })
    expect(document.documentElement.style.getPropertyValue('--nd-accent')).toBe('#a78bfa')
    expect(document.getElementById('nexdeck-appearance')?.textContent).toBe('.card { border-radius: 4px; }')
  })

  it('paints the ink over the accent too, and gives it back with it', () => {
    applyAppearance({ preset: 'cyan', accent: '', colour: '#22d3ee', css: '' })
    expect(document.documentElement.style.getPropertyValue('--nd-on-accent')).toBe('#041016')
    applyAppearance(null)
    expect(document.documentElement.style.getPropertyValue('--nd-on-accent')).toBe('')
  })

  it('takes the style sheet away again when it is emptied', () => {
    applyAppearance({ preset: 'cyan', accent: '', colour: '#22d3ee', css: '.card { border-radius: 4px; }' })
    applyAppearance({ preset: 'cyan', accent: '', colour: '#22d3ee', css: '   ' })
    expect(document.getElementById('nexdeck-appearance')).toBeNull()
  })

  it('keeps only one tag however often it is painted', () => {
    for (let round = 0; round < 3; round += 1) applyAppearance({ preset: 'cyan', accent: '', colour: '#22d3ee', css: `.a${round} {}` })
    expect(document.querySelectorAll('#nexdeck-appearance')).toHaveLength(1)
    expect(document.getElementById('nexdeck-appearance')?.textContent).toBe('.a2 {}')
  })

  it('gives the shipped colour back when there is nothing to apply', () => {
    applyAppearance({ preset: 'violet', accent: '', colour: '#a78bfa', css: '' })
    applyAppearance(null)
    expect(document.documentElement.style.getPropertyValue('--nd-accent')).toBe('')
  })
})

describe('the cards', () => {
  const base = { preset: 'cyan', accent: '', css: '', colour: '#22d3ee' }
  beforeEach(() => {
    document.documentElement.removeAttribute('style')
    delete document.documentElement.dataset.cards
    useLook.setState({ gap: 12 })
  })

  it('marks the page with a style other than glass, and its corners and gap', () => {
    applyAppearance({ ...base, card_style: 'neon', radius: 4, gap: 20 })
    expect(document.documentElement.dataset.cards).toBe('neon')
    expect(document.documentElement.style.getPropertyValue('--nd-radius')).toBe('4px')
    expect(useLook.getState().gap).toBe(20)
  })

  it('leaves no mark for glass, so the sheet nexdeck ships draws it as always', () => {
    applyAppearance({ ...base, card_style: 'flat', radius: 8, gap: 6 })
    applyAppearance({ ...base, card_style: 'glass' })
    expect(document.documentElement.dataset.cards).toBeUndefined()
    expect(document.documentElement.style.getPropertyValue('--nd-radius')).toBe('')
    expect(useLook.getState().gap).toBe(12)
  })

  it('keeps nexdeck as it was when the server knows nothing of cards yet', () => {
    applyAppearance(base)
    expect(document.documentElement.dataset.cards).toBeUndefined()
    expect(useLook.getState().gap).toBe(12)
  })
})

describe('a look to share', () => {
  const base = { preset: 'cyan', accent: '#ff00aa', css: '.secret { }', colour: '#ff00aa', card_style: 'neon' as const, radius: 6, gap: 20, theme: { name: 'Dusk', dark: { bg: '#101010' } } }

  it('travels as theme, colour and cards, and leaves the style sheet at home', () => {
    const text = lookFile(base)
    expect(text).not.toContain('secret')
    const read = readLook(text)
    expect('look' in read && read.look).toEqual({ theme: { name: 'Dusk', dark: { bg: '#101010' }, light: undefined }, accent: '#ff00aa', card_style: 'neon', refraction: true, radius: 6, gap: 20, font: 'inter', retro: { status: 'symbol', icons: 'colour', desk: 'dither', type: 'titles' } })
  })

  it('carries the calm cards and the font, and an older look leaves the font as it is', () => {
    const read = readLook(lookFile({ ...base, card_style: 'calm', font: 'mono' }))
    expect('look' in read && [read.look.card_style, read.look.font]).toEqual(['calm', 'mono'])
    const older = readLook(JSON.stringify({ nexdeck_look: 1, theme: null, card_style: 'flat', radius: 8, gap: 8 }))
    expect('look' in older && 'font' in older.look).toBe(false)
    const strange = readLook(JSON.stringify({ nexdeck_look: 1, theme: null, font: 'comic' }))
    expect('look' in strange && strange.look.font).toBe('inter')
  })

  it('takes a theme shared on its own, as before looks existed', () => {
    const read = readLook(JSON.stringify({ nexdeck_theme: 1, name: 'Old', dark: { bg: '#000000' } }))
    expect('look' in read && read.look.theme?.name).toBe('Old')
  })

  it('falls back on what is out of bounds, and says so in words for what is not a look', () => {
    const read = readLook(JSON.stringify({ nexdeck_look: 1, theme: null, card_style: 'wood', radius: 99, gap: 2 }))
    expect('look' in read && [read.look.card_style, read.look.radius, read.look.gap]).toEqual(['glass', 16, 12])
    expect(readLook('nonsense')).toEqual({ error: 'json' })
  })
})

describe('the accent in the brightness on screen', () => {
  const cyan = { preset: 'cyan', accent: '', colour: '#22d3ee', css: '' }
  const light = ['bg', 'bg-elev', 'surface'].map((ground) => OWN_PALETTES.light[ground])
  const dark = ['bg', 'bg-elev', 'surface'].map((ground) => OWN_PALETTES.dark[ground])
  const shown = () => document.documentElement.style.getPropertyValue('--nd-accent')
  const hue = (colour: string) => {
    const [r, g, b] = channels(colour)!
    const high = Math.max(r, g, b)
    const spread = high - Math.min(r, g, b)
    const turn = high === r ? ((g - b) / spread + 6) % 6 : high === g ? (b - r) / spread + 2 : (r - g) / spread + 4
    return turn * 60
  }

  beforeEach(() => {
    document.documentElement.removeAttribute('style')
    document.documentElement.dataset.theme = 'dark'
  })
  afterEach(() => {
    applyAppearance(null)
    delete document.documentElement.dataset.theme
  })

  it('reads cyan at 4.5:1 on every light ground, in its own hue and no darker than it has to be', () => {
    const shade = readableAccent('#22d3ee', 'light', light)
    for (const ground of light) expect(contrast(shade, ground)).toBeGreaterThanOrEqual(4.5)
    expect(Math.abs(hue(shade) - hue('#22d3ee'))).toBeLessThan(2)
    // One notch lighter would fall short again: the shade stops where the line is crossed.
    const [r, g, b] = channels(shade)!
    const lighter = `#${[r, g, b].map((value) => Math.min(255, value + 2).toString(16).padStart(2, '0')).join('')}`
    expect(Math.min(...light.map((ground) => contrast(lighter, ground)))).toBeLessThan(4.6)
  })

  it('leaves a colour that already reads alone, and lightens one too dark for the dark page', () => {
    expect(readableAccent('#0e7490', 'light', light)).toBe('#0e7490')
    expect(readableAccent('#22d3ee', 'dark', dark)).toBe('#22d3ee')
    const lifted = readableAccent('#1e3a8a', 'dark', dark)
    for (const ground of dark) expect(contrast(lifted, ground)).toBeGreaterThanOrEqual(4.5)
    expect(Math.abs(hue(lifted) - hue('#1e3a8a'))).toBeLessThan(3)
  })

  it('paints the darker cyan in the light look, with an ink that goes with it, and the colour itself in the dark one', () => {
    document.documentElement.dataset.theme = 'light'
    applyAppearance(cyan)
    expect(shown()).not.toBe('#22d3ee')
    for (const ground of light) expect(contrast(shown(), ground)).toBeGreaterThanOrEqual(4.5)
    expect(document.documentElement.style.getPropertyValue('--nd-on-accent')).toBe(onAccent(shown()))
    expect(document.documentElement.style.getPropertyValue('--nd-accent-strong')).toBe(darker(shown()))
    document.documentElement.dataset.theme = 'dark'
    applyAppearance(cyan)
    expect(shown()).toBe('#22d3ee')
  })

  it('moves along when the brightness switches, without painting the look again', async () => {
    applyAppearance(cyan)
    expect(shown()).toBe('#22d3ee')
    followTheme({ theme: 'light' }, { remember: false })
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(shown()).toBe(readableAccent('#22d3ee', 'light', light))
    followTheme({ theme: 'dark' }, { remember: false })
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(shown()).toBe('#22d3ee')
  })

  it('reads a colour of one own against the grounds of the theme, and leaves the accent of a theme alone', () => {
    const theme = { name: 'Slate', light: { bg: '#d0d4dc', 'bg-elev': '#d8dce4', surface: '#e0e4ec', accent: '#123456' } }
    document.documentElement.dataset.theme = 'light'
    applyAppearance({ ...cyan, accent: '#22d3ee', theme })
    const own = shown()
    for (const ground of ['#d0d4dc', '#d8dce4', '#e0e4ec']) expect(contrast(own, ground)).toBeGreaterThanOrEqual(4.5)
    // The theme's page is darker than nexdeck's own, so the shade has to go further.
    const sum = (colour: string) => channels(colour)!.reduce((all, part) => all + part, 0)
    expect(sum(own)).toBeLessThan(sum(readableAccent('#22d3ee', 'light', light)))
    applyAppearance({ ...cyan, theme })
    expect(shown()).toBe('')
  })
})
