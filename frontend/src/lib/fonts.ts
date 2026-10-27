/**
 * The type the interface is set in.
 *
 * Inter is what nexdeck has always been set in, and with JetBrains Mono for
 * the numbers it is in the first style sheet already. The system's own needs
 * nothing. The others ship with nexdeck (SIL Open Font License, from
 * Fontsource) and their style sheet is loaded only by a browser that shows
 * them: the first visit stays as light as it was, and nothing is ever
 * fetched from anywhere but nexdeck itself.
 *
 * A font to come is one more entry here and one more name in
 * `appearance.FONTS` on the server. `data-font` on the root lets the style
 * sheet set it a little differently where it needs to. The pixel face is
 * also what 1984 sets its titles in (lib/retro.ts asks for it there).
 */
export interface FontChoice {
  key: string
  /** Its own name, the same in every language; the system's is said in words. */
  name: string
  /** The CSS family, with nothing after it: the sheet puts the fallbacks behind. */
  family: string
  /** Every letter as wide as the next. */
  mono?: boolean
  /** Its faces, fetched the first time it is shown. */
  load?: () => Promise<unknown>
}

export const FONTS: FontChoice[] = [
  { key: 'inter', name: 'Inter', family: "'Inter Variable'" },
  { key: 'system', name: '', family: "system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue'" },
  { key: 'plex', name: 'IBM Plex Sans', family: "'IBM Plex Sans Variable'", load: () => import('@fontsource-variable/ibm-plex-sans') },
  { key: 'atkinson', name: 'Atkinson Hyperlegible', family: "'Atkinson Hyperlegible Next Variable'", load: () => import('@fontsource-variable/atkinson-hyperlegible-next') },
  { key: 'geist', name: 'Geist', family: "'Geist Variable'", load: () => import('@fontsource-variable/geist') },
  { key: 'mono', name: 'JetBrains Mono', family: "'JetBrains Mono Variable'", mono: true },
  { key: 'pixel', name: 'Pixelify Sans', family: "'Pixelify Sans Variable'", load: () => import('@fontsource-variable/pixelify-sans') },
]

export const DEFAULT_FONT = FONTS[0].key

export function fontOf(key: unknown): FontChoice {
  return FONTS.find((font) => font.key === key) ?? FONTS[0]
}

/** The ones already asked for, so a second choice of the same costs nothing. */
const loading = new Map<string, Promise<unknown>>()
/** The font chosen last: a choice that comes while another loads wins. */
let chosen = DEFAULT_FONT

/** Its faces, asked for once. A face that cannot be had leaves the fallbacks in the family. */
export function loadFace(key: unknown): Promise<unknown> {
  const font = fontOf(key)
  if (!font.load) return Promise.resolve()
  if (!loading.has(font.key)) loading.set(font.key, font.load().catch(() => undefined))
  return loading.get(font.key)!
}

/**
 * Set the interface in a font. Its faces are asked for first, so the change
 * happens once and in the new type, not in a fallback and again a moment
 * later.
 */
export async function setFont(key: unknown): Promise<void> {
  const font = fontOf(key)
  chosen = font.key
  await loadFace(font.key)
  if (chosen !== font.key) return
  const root = document.documentElement
  if (font.key === DEFAULT_FONT) {
    root.style.removeProperty('--nd-font')
    delete root.dataset.font
  } else {
    root.style.setProperty('--nd-font', font.family)
    root.dataset.font = font.key
  }
}
