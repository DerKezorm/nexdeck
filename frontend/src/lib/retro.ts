/**
 * 1984: the window style, which redraws the whole interface and not only the
 * cards. Every card a window with a striped title bar, the bar a menu bar, the
 * page a dotted desk, titles in pixels, one bit of black and white, and colour
 * left only to the small symbols that say how a card is.
 *
 * Its style sheet (`styles/retro.css`) and its pixel type are fetched the
 * first time the style is shown, never with the first visit: a browser that
 * never sees 1984 never loads a byte of it. Every rule in that sheet starts
 * with `:root[data-cards='window']`, so every other look is left as it was
 * (the guard is `styles/retro.test.ts`).
 *
 * The four choices are marks on the root the sheet answers to:
 * `data-r-status` (symbol, tint, pattern), `data-r-icons` (colour, mono),
 * `data-r-desk` (dither, weave, grey) and `data-r-type` (titles, all).
 */
import { loadFace } from './fonts'

export interface RetroChoices {
  /** How a yellow or red card says so: a coloured symbol, a touch of colour on the window as well, or the shape alone. */
  status: 'symbol' | 'tint' | 'pattern'
  /** Logos in their colours, or in black and white. */
  icons: 'colour' | 'mono'
  /** The ground of the desk: a fine dither, a woven pattern, or plain grey. */
  desk: 'dither' | 'weave' | 'grey'
  /** The pixel type for titles and menus only, or for everything. */
  type: 'titles' | 'all'
}

/** Each choice with its options, the first the default: the mock-up as it was approved. The same as `appearance.RETRO`. */
export const RETRO_CHOICES: { [K in keyof RetroChoices]: readonly RetroChoices[K][] } = {
  status: ['symbol', 'tint', 'pattern'],
  icons: ['colour', 'mono'],
  desk: ['dither', 'weave', 'grey'],
  type: ['titles', 'all'],
}

export const RETRO_DEFAULTS: RetroChoices = { status: 'symbol', icons: 'colour', desk: 'dither', type: 'titles' }

/** Stored choices as the sheet knows them; anything else is its default. */
export function retroOf(value: unknown): RetroChoices {
  const given = value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
  const result = { ...RETRO_DEFAULTS }
  for (const key of Object.keys(RETRO_CHOICES) as (keyof RetroChoices)[]) {
    if ((RETRO_CHOICES[key] as readonly unknown[]).includes(given[key])) (result as Record<string, unknown>)[key] = given[key]
  }
  return result
}

const MARKS: Record<keyof RetroChoices, string> = { status: 'rStatus', icons: 'rIcons', desk: 'rDesk', type: 'rType' }

/** The sheet, asked for once. */
let sheet: Promise<unknown> | null = null
export function loadRetroSheet(): Promise<unknown> {
  sheet ??= import('../styles/retro.css').catch(() => {
    // A sheet that could not be had (a deploy in between) is asked for again next time.
    sheet = null
  })
  return sheet
}

/**
 * The size of one pixel of the screen, in CSS pixels, rounded to whole ones.
 *
 * ⚠️ A dither of one CSS pixel at 125 % zoom is 1.25 screen pixels: every
 * fourth dot comes out twice as wide, and the desk shows stripes (moiré). The
 * same lesson as the bent glass (lib/refraction.ts), which ran in screen
 * pixels for the same reason. The patterns are drawn in whole screen pixels
 * instead: one at 100 % and 125 %, two at 150 % and 200 %.
 */
export function pixelSize(ratio: number): number {
  const dots = Math.max(1, Math.round(ratio || 1))
  return dots / (ratio || 1)
}

const PATTERNS = 'nd-r-patterns'

/**
 * Two patterns for the area under a line in a chart, as an SVG anywhere on
 * the page that every chart can point its fill at: a dither, and rows of
 * lines for a chart stretched sideways (`preserveAspectRatio="none"`), where
 * a dither would come out as dashes. Sized in whole screen pixels like the
 * desk.
 */
function patterns(size: number): void {
  let holder: Element | null = document.getElementById(PATTERNS)
  if (!holder) {
    holder = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
    holder.id = PATTERNS
    holder.setAttribute('aria-hidden', 'true')
    holder.setAttribute('width', '0')
    holder.setAttribute('height', '0')
    holder.setAttribute('style', 'position:absolute;width:0;height:0;overflow:hidden')
    document.body.append(holder)
  }
  const one = size.toFixed(4)
  const two = (2 * size).toFixed(4)
  holder.innerHTML =
    `<defs><pattern id="nd-r-dither" width="${two}" height="${two}" patternUnits="userSpaceOnUse">` +
    `<rect width="${one}" height="${one}"/><rect x="${one}" y="${one}" width="${one}" height="${one}"/></pattern>` +
    `<pattern id="nd-r-lines" width="8" height="${two}" patternUnits="userSpaceOnUse"><rect width="8" height="${one}"/></pattern></defs>`
}

let watching: MediaQueryList | null = null
function measure(): void {
  const ratio = window.devicePixelRatio || 1
  document.documentElement.style.setProperty('--r-px', `${pixelSize(ratio)}px`)
  patterns(pixelSize(ratio))
  // A zoom changes the ratio; the query of the old one says so once.
  watching?.removeEventListener('change', measure)
  watching = typeof window.matchMedia === 'function' ? window.matchMedia(`(resolution: ${ratio}dppx)`) : null
  watching?.addEventListener('change', measure)
}

/** 1984 on the page with its choices, or off it again. */
export function paintRetro(on: boolean, choices?: unknown): void {
  const root = document.documentElement
  if (!on) {
    for (const mark of Object.values(MARKS)) delete root.dataset[mark]
    root.style.removeProperty('--r-px')
    watching?.removeEventListener('change', measure)
    watching = null
    document.getElementById(PATTERNS)?.remove()
    return
  }
  const chosen = retroOf(choices)
  for (const [key, mark] of Object.entries(MARKS) as [keyof RetroChoices, string][]) root.dataset[mark] = chosen[key]
  measure()
  void loadRetroSheet()
  void loadFace('pixel')
}
