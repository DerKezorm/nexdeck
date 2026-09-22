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
}

const STYLE_ID = 'nexdeck-appearance'
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
