import { beforeEach, describe, expect, it } from 'vitest'

import { accentVariables, applyAppearance, channels, darker, lookFile, readLook, useLook } from './appearance'

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
      '--nd-accent-strong': '#1cadc3',
      '--nd-accent-soft': 'rgba(34, 211, 238, 0.14)',
      '--nd-accent-glow': 'rgba(34, 211, 238, 0.35)',
      '--nd-aurora-1': 'rgba(34, 211, 238, 0.16)',
    })
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
    expect('look' in read && read.look).toEqual({ theme: { name: 'Dusk', dark: { bg: '#101010' }, light: undefined }, accent: '#ff00aa', card_style: 'neon', radius: 6, gap: 20 })
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
