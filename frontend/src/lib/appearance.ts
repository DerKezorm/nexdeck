/**
 * The look of the installation, painted onto the page.
 *
 * nexdeck ships one look in two brightnesses. A colour theme, an accent
 * colour and a style sheet of the operator's own make it belong in the room
 * it hangs in, and all three come from one setting that everybody may read.
 *
 * The accent is written into the four variables the whole interface builds
 * on, in both brightnesses, so a light board follows the same colour.
 */
import { useEffect } from 'react'
import { create } from 'zustand'

import { DEFAULT_FONT, fontOf, setFont } from './fonts'
import { paintRetro, retroOf, type RetroChoices } from './retro'

export type Palette = Record<string, string>
export interface Theme {
  name: string
  dark?: Palette
  light?: Palette
}
export interface WeakSpot {
  mode: 'dark' | 'light'
  token: string
  ratio: number
}

export interface Appearance {
  preset: string
  accent: string
  css: string
  colour: string
  presets?: Record<string, string>
  /** A colour theme, or null for nexdeck's own look. */
  theme?: Theme | null
  /** The themes nexdeck ships. */
  themes?: Record<string, Theme>
  /** What in the chosen theme falls below 4.5:1. */
  weak?: WeakSpot[]
  /** How a card is drawn, its corners and the room between two, in pixels. */
  card_style?: CardStyle
  radius?: number
  gap?: number
  card_styles?: CardStyle[]
  /** Liquid glass: whether its rim bends the background (Chromium only). */
  refraction?: boolean
  /** The type of the interface (lib/fonts.ts), and the ones there are. */
  font?: string
  fonts?: string[]
  /** The window style's choices (lib/retro.ts). */
  retro?: Partial<RetroChoices>
}

/**
 * How a card is drawn. Glass is nexdeck as it always looked. A new style is
 * a name here, the same name in `appearance.CARD_STYLES` on the server, its
 * rules under `:root[data-cards='…']` in the style sheet and a sample in the
 * settings; the board, the kiosk and the settings take it from this list.
 *
 * Window is 1984 (lib/retro.ts): it redraws every page, so it is the
 * installation's or nothing, and a board does not get to choose it.
 */
export const CARD_STYLES = ['glass', 'liquid', 'flat', 'outline', 'neon', 'calm', 'window'] as const
export type CardStyle = (typeof CARD_STYLES)[number]
export const BOARD_STYLES: readonly CardStyle[] = CARD_STYLES.filter((style) => style !== 'window')

/**
 * The part of the look a component has to know rather than only paint: the
 * grid needs the gap to lay the cards out, a card needs to know whether it is
 * liquid glass to bend the light. ``board`` is the style of the board on
 * screen when it has one of its own; it wins over the installation's.
 */
export const useLook = create<{ gap: number; cards: CardStyle; board: CardStyle | null; refraction: boolean; retro: RetroChoices }>(() => ({
  gap: 12,
  cards: 'glass',
  board: null,
  refraction: true,
  retro: retroOf(null),
}))

/**
 * The style the cards on screen are drawn in. 1984 wins over a board's own
 * style: with it chosen nothing on any page may look modern.
 */
export function shownStyle(look: { cards: CardStyle; board: CardStyle | null }): CardStyle {
  if (look.cards === 'window') return 'window'
  return look.board && look.board !== 'window' ? look.board : look.cards
}

/** The style onto the page: the board's own, else the installation's. Glass needs no mark. */
function paintCards(): void {
  const look = useLook.getState()
  const style = shownStyle(look)
  const root = document.documentElement
  if (style !== 'glass') root.dataset.cards = style
  else delete root.dataset.cards
  root.dataset.refract = look.refraction ? 'on' : 'off'
  paintRetro(style === 'window', look.retro)
}
useLook.subscribe(paintCards)

/** A board's own card style while it is on screen; it hands back to the installation's when it goes. */
export function setBoardStyle(style: unknown): void {
  const known = STYLES.includes(style as CardStyle) ? (style as CardStyle) : null
  if (useLook.getState().board !== known) useLook.setState({ board: known })
}

/** For a page that shows a board: its own card style while it stands, the installation's after. */
export function useBoardCardStyle(style: unknown): void {
  const known = STYLES.includes(style as CardStyle) ? (style as CardStyle) : null
  useEffect(() => {
    setBoardStyle(known)
    return () => setBoardStyle(null)
  }, [known])
}

const STYLE_ID = 'nexdeck-appearance'
const STYLES: readonly CardStyle[] = CARD_STYLES
const THEME_ID = 'nexdeck-theme'
const HEX = /^#[0-9a-f]{6}$/i

/** The three parts of a `#rrggbb` colour as numbers, or null if it is not one. */
export function channels(colour: string): [number, number, number] | null {
  if (!HEX.test(colour)) return null
  return [colour.slice(1, 3), colour.slice(3, 5), colour.slice(5, 7)].map((part) => parseInt(part, 16)) as [number, number, number]
}

/** A darker shade of the accent, for the pressed state and the strong border. */
export function darker(colour: string, by = 0.18): string {
  const parts = channels(colour)
  if (!parts) return colour
  const shaded = parts.map((value) => Math.max(0, Math.round(value * (1 - by))))
  return `#${shaded.map((value) => value.toString(16).padStart(2, '0')).join('')}`
}

/** The variables an accent colour turns into. */
export function accentVariables(colour: string): Record<string, string> {
  const parts = channels(colour)
  if (!parts) return {}
  const [red, green, blue] = parts
  return {
    '--nd-accent': colour,
    '--nd-accent-strong': darker(colour),
    '--nd-accent-soft': `rgba(${red}, ${green}, ${blue}, 0.14)`,
    '--nd-accent-glow': `rgba(${red}, ${green}, ${blue}, 0.35)`,
    '--nd-aurora-1': `rgba(${red}, ${green}, ${blue}, 0.16)`,
  }
}

/** A colour as rgba with the given opacity; the colour itself if it is not #rrggbb. */
function see(colour: string, alpha: number): string {
  const parts = channels(colour)
  return parts ? `rgba(${parts.join(', ')}, ${alpha})` : colour
}

/**
 * A theme as a style sheet: one block for dark, one for light, so the
 * brightness switch needs nothing from here. The surfaces are see-through
 * as nexdeck's own are, and the accent's shades come from the accent.
 *
 * ⚠️ Dark is written as `:root:not([data-theme='light'])`, not as `:root`.
 * This sheet stands outside the layers of the shipped one and beats it
 * whatever the specificity, so a plain `:root` would have painted the dark
 * colours over the light look too.
 */
export function themeCss(theme: Theme | null | undefined): string {
  if (!theme) return ''
  const blocks: string[] = []
  for (const mode of ['dark', 'light'] as const) {
    const palette = theme[mode]
    if (!palette) continue
    const light = mode === 'light'
    const variables: Record<string, string> = {}
    for (const [token, colour] of Object.entries(palette)) variables[`--nd-${token}`] = colour
    if (palette.surface) {
      variables['--nd-surface'] = see(palette.surface, light ? 0.7 : 0.64)
      variables['--nd-surface-strong'] = see(palette.surface, light ? 0.94 : 0.92)
    }
    if (palette['surface-hover']) variables['--nd-surface-hover'] = see(palette['surface-hover'], light ? 0.9 : 0.78)
    if (palette.accent) {
      variables['--nd-accent-strong'] = darker(palette.accent)
      variables['--nd-accent-soft'] = see(palette.accent, light ? 0.12 : 0.14)
      variables['--nd-accent-glow'] = see(palette.accent, light ? 0.25 : 0.35)
      variables['--nd-aurora-1'] = see(palette.accent, light ? 0.14 : 0.16)
    }
    const body = Object.entries(variables).map(([name, value]) => `  ${name}: ${value};`).join('\n')
    blocks.push(`${light ? ":root[data-theme='light']" : ":root:not([data-theme='light'])"} {\n${body}\n}`)
  }
  return blocks.join('\n')
}

/** Put a tag of ours into the head, or take it out when there is nothing to say. */
function tagFor(id: string, css: string, before?: HTMLElement | null): void {
  let tag = document.getElementById(id) as HTMLStyleElement | null
  if (!css) {
    tag?.remove()
    return
  }
  if (!tag) {
    tag = document.createElement('style')
    tag.id = id
    if (before && before.parentNode === document.head) document.head.insertBefore(tag, before)
    else document.head.append(tag)
  }
  tag.textContent = css
}

/**
 * Paint it on. A theme goes into a tag of its own; the operator's style
 * sheet into one after it, so it wins over everything nexdeck ships and over
 * the theme. The accent goes onto the root element, where it beats both
 * brightnesses: the preset's always, a theme's only when a colour of one's
 * own was chosen, since a theme brings an accent for dark and one for light.
 */
export function applyAppearance(look: Appearance | null | undefined): void {
  const root = document.documentElement
  const own = HEX.test(look?.accent ?? '')
  const colour = look?.theme && !own ? '' : (look?.colour ?? '')
  const variables = accentVariables(colour)
  for (const name of ['--nd-accent', '--nd-accent-strong', '--nd-accent-soft', '--nd-accent-glow', '--nd-aurora-1']) {
    if (variables[name]) root.style.setProperty(name, variables[name])
    else root.style.removeProperty(name)
  }
  tagFor(THEME_ID, themeCss(look?.theme), document.getElementById(STYLE_ID))
  tagFor(STYLE_ID, (look?.css ?? '').trim())
  // The cards: a style the sheet answers to, and two sizes. Glass is the
  // default and needs no mark, so a page without a stored look is unchanged.
  // A board with a style of its own wins over this one (setBoardStyle).
  if (typeof look?.radius === 'number') root.style.setProperty('--nd-radius', `${look.radius}px`)
  else root.style.removeProperty('--nd-radius')
  useLook.setState({
    gap: typeof look?.gap === 'number' ? look.gap : 12,
    cards: STYLES.includes(look?.card_style as CardStyle) ? (look?.card_style as CardStyle) : 'glass',
    refraction: look?.refraction !== false,
    retro: retroOf(look?.retro),
  })
  paintCards()
  void setFont(look?.font ?? DEFAULT_FONT)
  remember(look)
}

const KEPT = 'nexdeck.look'

/**
 * The look as this browser saw it last, without the operator's style sheet.
 *
 * The look is read from the server after the page has started, so every load
 * began in nexdeck's own glass and turned into the chosen look a moment
 * later. For a theme that is a flicker; for 1984, which redraws everything,
 * it is a different program for half a second. The start paints what was
 * kept here first (main.tsx), the server's answer follows as before.
 */
function remember(look: Appearance | null | undefined): void {
  try {
    if (!look) localStorage.removeItem(KEPT)
    else {
      const { theme, accent, colour, preset, card_style, radius, gap, refraction, font, retro } = look
      localStorage.setItem(KEPT, JSON.stringify({ theme: theme ?? null, accent, colour, preset, card_style, radius, gap, refraction, font, retro, css: '' }))
    }
  } catch {
    // A browser that keeps nothing starts in nexdeck's own look, as it always did.
  }
}

/** Paint the look this browser kept, before the server has said anything. */
export function recallLook(): void {
  try {
    const kept = localStorage.getItem(KEPT)
    if (kept) applyAppearance(JSON.parse(kept) as Appearance)
  } catch {
    // Nothing kept, or nothing readable: nexdeck's own look until the server answers.
  }
}

/** The contrast ratio of two #rrggbb colours, from 1 to 21, the way WCAG counts it. */
export function contrast(one: string, other: string): number {
  const luminance = (colour: string) => {
    const parts = channels(colour)
    if (!parts) return 0
    const [r, g, b] = parts.map((value) => {
      const c = value / 255
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
    })
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
  }
  const [a, b] = [luminance(one), luminance(other)]
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}

/** The fifteen colours a theme sets, as the server names them (`themes.TOKENS`). */
export const THEME_TOKENS = [
  'bg', 'bg-elev', 'surface', 'surface-hover', 'border', 'border-strong',
  'text', 'text-muted', 'text-faint', 'accent', 'on-accent', 'ok', 'warn', 'bad', 'unknown',
] as const

/**
 * nexdeck's own look as fifteen plain colours, the start of a theme of one's
 * own. The style sheet draws surfaces and lines see-through; here they are
 * the colour they come out as over the page.
 */
export const OWN_PALETTES: { dark: Palette; light: Palette } = {
  dark: {
    bg: '#0a0d12', 'bg-elev': '#0f131a', surface: '#11161f', 'surface-hover': '#181f2b', border: '#1b1e23', 'border-strong': '#313337',
    text: '#e7eaf0', 'text-muted': '#94a0b3', 'text-faint': '#8590a2', accent: '#22d3ee', 'on-accent': '#041016',
    ok: '#34d399', warn: '#fbbf24', bad: '#fb7185', unknown: '#7f8b9e',
  },
  light: {
    bg: '#eef1f5', 'bg-elev': '#ffffff', surface: '#ffffff', 'surface-hover': '#f6f8fa', border: '#dce0e5', 'border-strong': '#cacfd5',
    text: '#0f172a', 'text-muted': '#55627a', 'text-faint': '#556072', accent: '#0e7490', 'on-accent': '#ffffff',
    ok: '#047857', warn: '#a4560a', bad: '#be123c', unknown: '#556070',
  },
}

const TEXT = ['text', 'text-muted', 'text-faint', 'accent', 'ok', 'warn', 'bad', 'unknown']
const GROUNDS = ['bg', 'bg-elev', 'surface']

/** What in a theme is drawn as text and falls below 4.5:1: the same rule the server keeps. */
export function weakSpots(theme: Theme | null | undefined): WeakSpot[] {
  const found: WeakSpot[] = []
  for (const mode of ['dark', 'light'] as const) {
    const palette = theme?.[mode]
    if (!palette) continue
    for (const token of TEXT) {
      if (!palette[token]) continue
      const ratios = GROUNDS.filter((ground) => palette[ground]).map((ground) => contrast(palette[token], palette[ground]))
      const worst = Math.min(21, ...ratios)
      if (worst < 4.5) found.push({ mode, token, ratio: Math.round(worst * 100) / 100 })
    }
    if (palette.accent && palette['on-accent'] && contrast(palette.accent, palette['on-accent']) < 4.5) {
      found.push({ mode, token: 'on-accent', ratio: Math.round(contrast(palette.accent, palette['on-accent']) * 100) / 100 })
    }
  }
  return found
}

/** A theme read from pasted JSON, or an error in words. Only the three known parts are kept. */
export function readTheme(text: string): { theme: Theme } | { error: string } {
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    return { error: 'json' }
  }
  if (!parsed || typeof parsed !== 'object') return { error: 'shape' }
  const { name, dark, light } = parsed as Record<string, unknown>
  if (typeof name !== 'string' || !name.trim() || (!dark && !light)) return { error: 'shape' }
  const palette = (value: unknown) => (value && typeof value === 'object' ? (value as Palette) : undefined)
  return { theme: { name: name.trim().slice(0, 40), dark: palette(dark), light: palette(light) } }
}

/** The theme as the file it is shared as. */
export function themeFile(theme: Theme): string {
  return JSON.stringify({ nexdeck_theme: 1, name: theme.name, dark: theme.dark, light: theme.light }, null, 2)
}

/**
 * The whole look as the text it is shared as: the theme, a colour of one's
 * own, the cards. No style sheet: a sheet written for one installation can
 * break another, and it is the one part that is code.
 */
export function lookFile(look: Appearance): string {
  return JSON.stringify({
    nexdeck_look: 1,
    theme: look.theme ? { name: look.theme.name, dark: look.theme.dark, light: look.theme.light } : null,
    accent: HEX.test(look.accent ?? '') ? look.accent : '',
    card_style: look.card_style ?? 'glass',
    refraction: look.refraction !== false,
    radius: look.radius ?? 16,
    gap: look.gap ?? 12,
    font: fontOf(look.font).key,
    retro: retroOf(look.retro),
  })
}

/**
 * A look read from pasted text, or an error in words. A theme on its own, as
 * it was shared before looks existed, is taken as a look with that theme.
 * Numbers out of bounds and unknown styles fall back rather than fail; the
 * server checks again on saving.
 */
export function readLook(text: string): { look: Partial<Appearance> } | { error: string } {
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    return { error: 'json' }
  }
  if (!parsed || typeof parsed !== 'object') return { error: 'shape' }
  const value = parsed as Record<string, unknown>
  if (!('nexdeck_look' in value)) {
    const theme = readTheme(text)
    return 'error' in theme ? theme : { look: { theme: theme.theme } }
  }
  const look: Partial<Appearance> = {}
  if (value.theme) {
    const theme = readTheme(JSON.stringify(value.theme))
    if ('error' in theme) return theme
    look.theme = theme.theme
  } else look.theme = null
  look.accent = typeof value.accent === 'string' && HEX.test(value.accent) ? value.accent : ''
  look.card_style = STYLES.includes(value.card_style as CardStyle) ? (value.card_style as CardStyle) : 'glass'
  look.refraction = value.refraction !== false
  const within = (number: unknown, low: number, high: number, fallback: number) => (typeof number === 'number' && Number.isInteger(number) && number >= low && number <= high ? number : fallback)
  look.radius = within(value.radius, 0, 28, 16)
  look.gap = within(value.gap, 4, 28, 12)
  // A look shared before fonts could be chosen leaves the font as it is.
  if (typeof value.font === 'string') look.font = fontOf(value.font).key
  if (value.retro && typeof value.retro === 'object') look.retro = retroOf(value.retro)
  return { look }
}

