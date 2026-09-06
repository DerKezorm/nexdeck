/**
 * The look of the installation, painted onto the page.
 *
 * nexdeck ships one look in two brightnesses. An accent colour and a style
 * sheet of the operator's own are enough to make it belong in the room it
 * hangs in, and both come from one setting that everybody may read.
 *
 * The accent is written into the four variables the whole interface builds
 * on, in both brightnesses, so a light board follows the same colour.
 */
export interface Appearance {
  preset: string
  accent: string
  css: string
  colour: string
  presets?: Record<string, string>
}

const STYLE_ID = 'nexdeck-appearance'
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

/**
 * Paint it on. The accent goes onto the root element, where it beats the
 * style sheet's own value in both brightnesses; the operator's style sheet
 * goes into one tag of its own at the end of the head, so it wins over
 * everything nexdeck ships and nothing else has to move.
 */
export function applyAppearance(look: Appearance | null | undefined): void {
  const root = document.documentElement
  const variables = accentVariables(look?.colour ?? '')
  for (const name of ['--nd-accent', '--nd-accent-strong', '--nd-accent-soft', '--nd-accent-glow', '--nd-aurora-1']) {
    if (variables[name]) root.style.setProperty(name, variables[name])
    else root.style.removeProperty(name)
  }

  const css = (look?.css ?? '').trim()
  let tag = document.getElementById(STYLE_ID) as HTMLStyleElement | null
  if (!css) {
    tag?.remove()
    return
  }
  if (!tag) {
    tag = document.createElement('style')
    tag.id = STYLE_ID
    document.head.append(tag)
  }
  tag.textContent = css
}
